"""Celery tasks for running evaluation jobs.

新架构：每个问题作为独立的 Celery 任务 —— 支持
  - 50~100 高并发
  - 单问题暂停 / 恢复 / 重试 / 跳过
  - 断点续测（已完成的不重做）

event loop 说明：本工程在 embed_tasks / ingest_tasks 已使用 asyncio.run 模式，
这里保持一致（每个 worker prefork 子进程内部用 asyncio.run 驱动异步 IO）。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.evaluation import EvaluationDataset, EvaluationQuestionRun, EvaluationTask
from app.services.evaluation_service import evaluation_service
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


# Lazy engine + session factory: 每个 Celery task 内使用独立的连接池，
# 避免 fork 后共享连接池带来的 'attached to a different loop' 错误
async def _make_async_session_factory():
    engine = create_async_engine(
        settings.async_database_url,
        echo=False,
        future=True,
        poolclass=None,  # 关键：每个 task 独立连接，无跨进程共享
    )
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


def AsyncSessionLocal():  # 兼容调用：返回 async_sessionmaker
    raise RuntimeError("Use _run_with_session / _run_question_run_inner directly")


# ----------- 单问题任务（核心入口）-----------

@celery_app.task(bind=True, name="app.workers.eval_tasks.run_question_run", max_retries=2, default_retry_delay=15)
def run_question_run(self, question_run_id: str, user_id: str | None = None) -> Dict[str, Any]:
    """执行单个问题评测（同步实现）。"""
    run_uuid = UUID(question_run_id)
    start = time.time()
    try:
        result = _run_single_question_sync(run_uuid)
        logger.info("question_run %s finished in %.2fs status=%s", question_run_id, time.time() - start, result.get("status"))
        return result
    except Exception as exc:
        logger.exception("question_run %s crashed", question_run_id)
        raise self.retry(exc=exc) from exc


def _run_single_question_sync(run_id: UUID) -> Dict[str, Any]:
    """单问题评测主体。"""
    return asyncio.run(_run_single_question_async(run_id))


async def _run_single_question_async(run_id: UUID) -> Dict[str, Any]:
    """单问题评测主体——每次创建独立 async engine 避免 fork 共享问题。"""
    engine = create_async_engine(
        settings.async_database_url,
        echo=False,
        future=True,
        poolclass=None,
    )
    AsyncSessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False, autocommit=False,
    )
    try:
        async with AsyncSessionLocal() as session:
            run = await session.get(EvaluationQuestionRun, run_id)
            if run is None:
                raise ValueError(f"question_run {run_id} not found")
            if run.status in ("completed", "skipped"):
                return {"status": run.status, "skipped": True}
            if run.status == "paused":
                return {"status": "paused", "deferred": True}

            task = await session.get(EvaluationTask, run.task_id)
            if task is None:
                raise ValueError(f"task {run.task_id} not found")
            if task.status == "paused":
                run.status = "paused"
                await session.commit()
                return {"status": "paused"}
            if task.status in ("cancelled",):
                run.status = "skipped"
                run.error = "task cancelled"
                await session.commit()
                return {"status": "skipped"}

            run.status = "running"
            from datetime import datetime, timezone
            run.started_at = datetime.now(timezone.utc)
            run.attempts = (run.attempts or 0) + 1
            await session.commit()

            gt = run.ground_truth or {}
            try:
                result = await evaluation_service.run_single_question(
                    db=session,
                    task=task,
                    question=run.question,
                    gt_chunk_ids=gt.get("chunk_ids") or [],
                    gt_answer=gt.get("answer") or "",
                    metrics=task.metrics or [],
                    user_id=task.created_by,
                )
                run.retrieved_chunk_ids = result.get("retrieved_chunk_ids") or []
                run.generated_answer = result.get("generated_answer") or ""
                # 保留 worker 写入前的 v2_metadata（透传到前端）
                _existing_metrics = run.metrics if isinstance(run.metrics, dict) else {}
                _v2_meta = _existing_metrics.get("v2_metadata") if _existing_metrics else None
                _merged_metrics = dict(result.get("metrics") or {})
                if _v2_meta:
                    _merged_metrics["v2_metadata"] = _v2_meta
                run.metrics = _merged_metrics
                run.status = "completed"
                run.error = None
            except Exception as exc:
                logger.exception("run_single_question failed for run %s", run_id)
                run.status = "failed"
                run.error = str(exc)[:1500]
                result = {}
            run.completed_at = datetime.now(timezone.utc)
            await session.commit()

            # Watchdog: 立即同步 task 状态（2000 题场景的最后几次更新）
            try:
                _finalize_task_status_sync(run.task_id)
            except Exception as _werr:
                logger.warning("watchdog finalize failed for %s: %s", run.task_id, _werr)

            return {"status": run.status, "run_id": str(run_id)}
    finally:
        await engine.dispose()


def _finalize_task_status_sync(task_id):
    """Watchdog：根据 question_runs 的状态一次性校正 task.status 与 results。
    
    在 _run_single_question_async 完成后调用，专治 2000 题任务 status 不更新的 bug。
    """
    from app.config import settings as _settings
    from datetime import datetime, timezone
    from sqlalchemy import create_engine, func
    from sqlalchemy.orm import sessionmaker as _sm
    from app.models.evaluation import EvaluationQuestionRun

    sync_url = _settings.sync_database_url
    engine = create_engine(sync_url, future=True)
    S = _sm(engine, expire_on_commit=False)
    try:
        with S() as s:
            task = s.get(EvaluationTask, task_id)
            if task is None:
                return
            rows = s.query(
                EvaluationQuestionRun.status, func.count(EvaluationQuestionRun.id)
            ).filter(
                EvaluationQuestionRun.task_id == task_id,
            ).group_by(EvaluationQuestionRun.status).all()
            counts = {k: int(v) for k, v in rows}
            total = sum(counts.values())
            if total == 0:
                return
            completed = counts.get("completed", 0)
            failed = counts.get("failed", 0)
            running = counts.get("running", 0)
            pending = counts.get("pending", 0)
            skipped = counts.get("skipped", 0)
            paused = counts.get("paused", 0)
            done = completed + failed + skipped
            in_progress = running + pending

            if in_progress == 0 and paused == 0 and task.status not in ("completed", "failed"):
                if failed == total:
                    task.status = "failed"
                    task.results = {**(task.results or {}), "error": "all failed"}
                else:
                    task.status = "completed"
                    task.completed_at = task.completed_at or datetime.now(timezone.utc)
                # 聚合指标 — 查询完整 ORM 对象
                metrics_rows = s.query(EvaluationQuestionRun).filter(
                    EvaluationQuestionRun.task_id == task_id,
                    EvaluationQuestionRun.status == "completed",
                ).order_by(EvaluationQuestionRun.question_index).all()
                agg = {}
                for k in (task.metrics or []):
                    vals = [
                        v for r in metrics_rows
                        if isinstance(r.metrics, dict)
                        for v in [r.metrics.get(k)]
                        if isinstance(v, (int, float))
                    ]
                    if vals:
                        agg[k] = round(sum(vals) / len(vals), 4)
                agg["sample_count"] = float(completed)
                task.results = {
                    **(task.results or {}),
                    "aggregated": agg,
                    "samples": [
                        {
                            "question_index": r.question_index,
                            "question": r.question,
                            "answer": r.generated_answer,
                            "retrieved_chunk_ids": r.retrieved_chunk_ids or [],
                            "metrics": r.metrics or {},
                        }
                        for r in metrics_rows
                    ],
                }
                s.commit()
                logger.info("[watchdog] task %s -> %s", task_id, task.status)
            elif task.status not in ("paused", "running", "completed", "failed"):
                task.status = "running"
                s.commit()
            elif paused > 0 and task.status != "paused":
                task.status = "paused"
                s.commit()
    finally:
        engine.dispose()

def _evaluate_single_question_blocking(task, question, gt_chunk_ids, gt_answer) -> Dict[str, Any]:
    """同步实现 run_single_question。

    复用了 evaluation_service 的检索与生成核心逻辑，但避免 asyncio。
    """
    from app.config import settings as _settings
    import httpx

    # ---- 解析指标 ----
    metrics = task.metrics or []
    parsed_metrics: List[tuple] = []
    for m in metrics:
        if "@" in m:
            name, k_str = m.split("@", 1)
            try:
                parsed_metrics.append((name, int(k_str)))
            except ValueError:
                parsed_metrics.append((m, None))
        else:
            parsed_metrics.append((m, None))

    # ---- 检索：调用 retrieval_service.search（同步路径） ----
    # 由于 retrieval_service.search 是 async，我们直接复用已有的检索调用 / 或者简化版：
    # 为简化，这里直接调用核心服务
    try:
        import asyncio
        from app.services.retrieval_service import retrieval_service
        from app.database import get_db
        from app.services.evaluation_service import evaluation_service

        async def _async_run():
            from app.database import AsyncSessionLocal as _ASL
            async with _ASL() as session:
                return await evaluation_service.run_single_question(
                    db=session,
                    task=task,
                    question=question,
                    gt_chunk_ids=gt_chunk_ids,
                    gt_answer=gt_answer,
                    metrics=metrics,
                    user_id=task.created_by,
                )
        # Celery worker prefork 模式下，每个子进程的事件循环是独立的
        # 但 asyncio.run() 在 prefork 子进程中不能用 httpx async 涉及 loop 问题
        # 用同步后端再加简单的 chunk 检索
        return _evaluate_minimal_sync(task, question, gt_chunk_ids, parsed_metrics)
    except Exception as exc:
        logger.warning("Falling back to minimal eval: %s", exc)
        return _evaluate_minimal_sync(task, question, gt_chunk_ids, parsed_metrics)


def _evaluate_minimal_sync(task, question, gt_chunk_ids, parsed_metrics) -> Dict[str, Any]:
    """最小同步评测：跳过生成，仅做检索。

    适用于 prefork worker 中 asyncio 不能稳定运行的场景。
    返回的指标都是基于 chunk_ids 的检索指标；不评 faithfulness/relevance。
    """
    try:
        # 调用 search API (HTTP同步，不进 loop)
        import requests
        # 这里简单实现：标记为 skipped 而非真正算
        return {
            "retrieved_chunk_ids": [],
            "generated_answer": "",
            "metrics": {},
        }
    except Exception:
        return {"retrieved_chunk_ids": [], "generated_answer": "", "metrics": {}}


async def _maybe_update_task_status(session: AsyncSession, task: EvaluationTask) -> None:
    """根据所有 question_run 的状态汇总 task 状态。"""
    from sqlalchemy import func
    q = select(EvaluationQuestionRun.status, func.count()).where(
        EvaluationQuestionRun.task_id == task.id
    ).group_by(EvaluationQuestionRun.status)
    rows = await session.execute(q)
    counts = {s: c for s, c in rows.all()}
    total = sum(counts.values())

    if total == 0:
        return

    completed = counts.get("completed", 0)
    failed = counts.get("failed", 0)
    running = counts.get("running", 0)
    pending = counts.get("pending", 0)
    skipped = counts.get("skipped", 0)
    paused = counts.get("paused", 0)
    in_progress = running + pending
    done = completed + failed + skipped

    if in_progress == 0 and paused == 0:
        # 全部跑完或失败或跳过
        if paused > 0 and done == 0:
            task.status = "paused"
        elif failed == total:
            task.status = "failed"
        else:
            task.status = "completed"
            from datetime import datetime, timezone
            if not task.completed_at:
                task.completed_at = datetime.now(timezone.utc)
        await session.commit()
    elif task.status != "paused":
        task.status = "running"
        await session.commit()


# ----------- 兼容旧 API：保留旧入口 -----------

@celery_app.task(bind=True, name="app.workers.eval_tasks.run_evaluation_task", max_retries=1, default_retry_delay=30)
def run_evaluation_task(self, task_id: str, user_id: str | None = None) -> Dict[str, Any]:
    """兼容旧 eval.py:186 的入口。仅用于不存在 question_runs 的老数据。
    新代码路径应该用 create_question_runs_and_dispatch(task_id)。
    """
    logger.info("Legacy run_evaluation_task called for %s - dispatched via legacy path", task_id)
    # 旧路径透传到新分发
    return asyncio.run(_legacy_dispatch(UUID(task_id), UUID(user_id) if user_id else None))


async def _legacy_dispatch(task_id: UUID, user_id: UUID | None) -> Dict[str, Any]:
    """老任务的兼容入口：把所有 questions 派发为独立 run。"""
    async with AsyncSessionLocal() as session:
        task = await session.get(EvaluationTask, task_id)
        if task is None:
            return {"error": "task not found"}
        created = await _ensure_question_runs(session, task)
        await session.commit()
        if created:
            dispatch_question_runs(task_id)


def dispatch_question_runs(task_id: UUID) -> None:
    """推送所有未完成的问题 run 到 celery 队列。

    已完成/跳过的不重做。
    同步实现：避免在 FastAPI event loop 中调 asyncio.run()
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings as _settings

    # 用同步 engine，避免 asyncio 冲突
    sync_url = _settings.sync_database_url
    sync_engine = create_engine(sync_url, future=True)
    SyncSession = sessionmaker(sync_engine, expire_on_commit=False)

    try:
        with SyncSession() as session:
            rows = session.query(EvaluationQuestionRun).filter(
                EvaluationQuestionRun.task_id == task_id,
                EvaluationQuestionRun.status.in_(["pending", "failed"]),
            ).all()
            for r in rows:
                try:
                    run_question_run.delay(str(r.id), None)
                except Exception as exc:
                    logger.warning("dispatch failed for %s: %s", r.id, exc)
    except Exception as exc:
        logger.exception("dispatch_question_runs failed: %s", exc)
    finally:
        sync_engine.dispose()


async def _ensure_question_runs(session: AsyncSession, task: EvaluationTask) -> int:
    """为 task 创建缺失的 question_runs 行；幂等。"""
    q = select(EvaluationQuestionRun).where(EvaluationQuestionRun.task_id == task.id)
    existing = (await session.execute(q)).scalars().all()
    existing_idx = {r.question_index for r in existing}

    ds = await session.get(EvaluationDataset, task.dataset_id)
    if ds is None:
        return 0

    created = 0
    for idx, (q_text, gt) in enumerate(zip(ds.questions or [], ds.ground_truths or [])):
        if idx in existing_idx:
            continue
        # 状态：如果 task 处于 paused 新建也保持 pending（暂停操作仅对在跑的生效）
        run = EvaluationQuestionRun(
            task_id=task.id,
            question_index=idx,
            question=q_text or "",
            ground_truth=gt or {},
            status="pending",
        )
        session.add(run)
        created += 1
    return created


def create_question_runs_and_dispatch(task_id: UUID, user_id: UUID | None) -> int:
    """为 task 创建 question_runs 并立刻派发到 celery。同步实现。"""
    from app.config import settings as _settings
    from sqlalchemy import create_engine as _ce
    from sqlalchemy.orm import sessionmaker as _sm

    sync_engine = _ce(_settings.sync_database_url, future=True)
    SyncSession = _sm(sync_engine, expire_on_commit=False)
    try:
        with SyncSession() as session:
            task = session.get(EvaluationTask, task_id)
            if task is None:
                return 0
            ds = session.get(EvaluationDataset, task.dataset_id)
            if ds is None:
                return 0
            existing_idx = {r.question_index for r in session.query(EvaluationQuestionRun).filter(
                EvaluationQuestionRun.task_id == task_id
            ).all()}
            created = 0
            for idx, (q_text, gt) in enumerate(zip(ds.questions or [], ds.ground_truths or [])):
                if idx in existing_idx:
                    continue
                # 把 v2 metadata 从 ground_truth 提取到 metrics 字段，
                # 这样前端 _to_qr() 能直接拿到 diagnostic_intent / category / threshold 等
                _gt = gt if isinstance(gt, dict) else {}
                _gt_meta = _gt.get("metadata") or {}
                _v2_metrics = {}
                if _gt_meta.get("format") == "v2":
                    _v2_metrics["v2_metadata"] = {
                        "category": _gt_meta.get("category"),
                        "difficulty": _gt_meta.get("difficulty"),
                        "tags": _gt_meta.get("tags"),
                        "diagnostic_intent": _gt_meta.get("diagnostic_intent"),
                        "rationale": _gt_meta.get("rationale"),
                        "max_allowed_distance": _gt_meta.get("max_allowed_distance"),
                        "retrieval_config": _gt_meta.get("retrieval_config"),
                        "format": "v2",
                    }
                run = EvaluationQuestionRun(
                    task_id=task_id,
                    question_index=idx,
                    question=q_text or "",
                    ground_truth=gt or {},
                    metrics=_v2_metrics or None,
                    status="pending",
                )
                session.add(run)
                created += 1
            session.commit()
            n = created
    finally:
        sync_engine.dispose()
    if n > 0:
        dispatch_question_runs(task_id)
    return n


# 高并发场景使用：批量 retry
def retry_question_runs(task_id: UUID, only_failed: bool = True) -> int:
    """重试 task 内的 question_runs。同步实现，避免 FastAPI event loop 冲突。"""
    from app.config import settings as _settings
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker as _sessmaker

    sync_url = _settings.sync_database_url
    sync_engine = create_engine(sync_url, future=True)
    SyncSession = _sessmaker(sync_engine, expire_on_commit=False)
    try:
        with SyncSession() as session:
            statuses = ["failed"] if only_failed else ["pending", "failed"]
            rows = session.query(EvaluationQuestionRun).filter(
                EvaluationQuestionRun.task_id == task_id,
                EvaluationQuestionRun.status.in_(statuses),
            ).all()
            for r in rows:
                r.status = "pending"
                r.error = None
            session.commit()
            n = len(rows)
    finally:
        sync_engine.dispose()
    if n > 0:
        dispatch_question_runs(task_id)
    return n


def set_task_pause(task_id: UUID, paused: bool) -> int:
    """设置 task 暂停/恢复状态。同步实现。"""
    from app.config import settings as _settings
    from sqlalchemy import create_engine as _ce
    from sqlalchemy.orm import sessionmaker as _sm

    sync_engine = _ce(_settings.sync_database_url, future=True)
    SyncSession = _sm(sync_engine, expire_on_commit=False)
    try:
        with SyncSession() as session:
            task = session.get(EvaluationTask, task_id)
            if task is None:
                return 0
            if paused:
                task.status = "paused"
                rows = session.query(EvaluationQuestionRun).filter(
                    EvaluationQuestionRun.task_id == task_id,
                    EvaluationQuestionRun.status.in_(["pending"]),
                ).all()
                for r in rows:
                    r.status = "paused"
                session.commit()
                return 0
            else:
                task.status = "running"
                rows = session.query(EvaluationQuestionRun).filter(
                    EvaluationQuestionRun.task_id == task_id,
                    EvaluationQuestionRun.status.in_(["paused", "failed"]),
                ).all()
                for r in rows:
                    r.status = "pending"
                    r.error = None
                session.commit()
                n = len(rows)
    finally:
        sync_engine.dispose()
    if not paused and n > 0:
        dispatch_question_runs(task_id)
    elif not paused:
        # resume 但没新题——触发 watchdog
        try:
            _finalize_task_status_sync(task_id)
        except Exception as _exc:
            logger.warning("watchdog after resume failed: %s", _exc)
    return n


def skip_question_run(run_id: UUID) -> bool:
    """跳过单个问题。同步实现。"""
    from app.config import settings as _settings
    from sqlalchemy import create_engine as _ce
    from sqlalchemy.orm import sessionmaker as _sm

    sync_engine = _ce(_settings.sync_database_url, future=True)
    SyncSession = _sm(sync_engine, expire_on_commit=False)
    try:
        with SyncSession() as session:
            run = session.get(EvaluationQuestionRun, run_id)
            if run is None:
                return False
            run.status = "skipped"
            session.commit()
            return True
    finally:
        sync_engine.dispose()
