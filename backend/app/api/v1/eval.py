"""Evaluation endpoints — 新细粒度版本。

每个问题作为独立 Celery 任务 —— 支持
- 50~100 高并发（celery worker 启动 -c N 控制并发数）
- 单问题：暂停 / 恢复 / 重试 / 跳过
- 断点续测：已完成的不重做
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.exceptions import NotFoundException, ValidationException
from app.database import get_db
from app.models.evaluation import EvaluationDataset, EvaluationQuestionRun, EvaluationTask
from app.schemas.evaluation import (
    DatasetUploadResponse,
    EvaluationDatasetCreate,
    EvaluationDatasetV2Create,
    EvaluationDatasetResponse,
    EvaluationMetricsResponse,
    EvaluationTaskCreate,
    EvaluationTaskResponse,
    QuestionRunResponse,
)
from app.schemas.user import UserResponse
from app.services.dataset_validator import parse_and_validate, to_dataset_create_payload
from app.services.evaluation_service import evaluation_service
from app.workers.eval_tasks import (
    create_question_runs_and_dispatch,
    dispatch_question_runs,
    retry_question_runs,
    set_task_pause,
    skip_question_run,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["evaluation"])

MAX_DATASET_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


# -------------- 数据集相关（保留） --------------

@router.post(
    "/evaluation/datasets/validate",
    response_model=DatasetUploadResponse,
)
async def validate_dataset_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    _ensure_json_filename(file)
    raw = await _read_upload(file)
    return parse_and_validate(raw, fallback_name=_strip_ext(file.filename))


@router.post(
    "/evaluation/datasets/upload",
    response_model=EvaluationDatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_dataset(
    kb_id: UUID = Form(...),
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    if not await evaluation_service.verify_kb(db, kb_id):
        raise NotFoundException(f"Knowledge base {kb_id} not found")
    _ensure_json_filename(file)
    raw = await _read_upload(file)
    fallback = name or _strip_ext(file.filename) if file.filename else None
    parsed = parse_and_validate(raw, fallback_name=fallback, fallback_kb_id=kb_id)
    if not parsed.valid:
        raise ValidationException("JSON 数据集校验失败：\n" + "\n".join(parsed.errors))
    final_name = (name or parsed.name or fallback or "未命名数据集")[:200]
    questions, ground_truths = to_dataset_create_payload(parsed, name=final_name, kb_id=kb_id)
    return await evaluation_service.create_dataset(
        db=db,
        kb_id=kb_id,
        name=final_name,
        questions=questions,
        ground_truths=ground_truths,
        created_by=current_user.id,
    )


def _ensure_json_filename(file: UploadFile) -> None:
    fname = (file.filename or "").lower()
    ct = (file.content_type or "").lower()
    if not (fname.endswith(".json") or "json" in ct):
        raise ValidationException(f"仅支持 JSON 文件：{file.filename}")


async def _read_upload(file: UploadFile) -> bytes:
    raw = await file.read()
    if not raw:
        raise ValidationException("上传的文件为空")
    if len(raw) > MAX_DATASET_FILE_SIZE:
        raise ValidationException(f"文件过大 {len(raw)} bytes")
    return raw


def _strip_ext(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    if filename.lower().endswith(".json"):
        return filename[:-5]
    return filename


@router.post(
    "/evaluation/datasets",
    response_model=EvaluationDatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_dataset(
    payload: EvaluationDatasetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    if not await evaluation_service.verify_kb(db, payload.kb_id):
        raise NotFoundException(f"Knowledge base {payload.kb_id} not found")
    return await evaluation_service.create_dataset(
        db=db,
        kb_id=payload.kb_id,
        name=payload.name,
        questions=payload.questions,
        ground_truths=payload.ground_truths,
        created_by=current_user.id,
    )


@router.post(
    "/evaluation/datasets/v2",
    status_code=status.HTTP_201_CREATED,
)
async def create_dataset_v2(
    payload: EvaluationDatasetV2Create,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """创建 v2 架构对齐评测数据集。

    顶层结构与 scripts/eval/datasets/ups_v2_arch_aligned.json 一致：
    - questions[] 每项含 question / ground_truth / metadata / retrieval_config / quality
    - _dataset_meta 携带 rag_arch_fingerprint
    """
    if not await evaluation_service.verify_kb(db, payload.kb_id):
        raise NotFoundException(f"Knowledge base {payload.kb_id} not found")

    # 转 v2 → 内部 v1 存储形式（向后兼容 DB）
    internal_questions = []
    internal_ground_truths = []
    for q in payload.questions:
        text = q.get("question") or q.get("query") or ""
        if not text:
            continue
        gt = q.get("ground_truth") or {}
        # 把 v2 metadata 也压成 ground_truth 的 metadata 字段，供后续访问
        if isinstance(gt, dict):
            gt_meta = dict(gt.get("metadata") or {})
            # 透传 quality 阈值 / diagnostic_intent / retrieval_config
            q_quality = q.get("quality") or {}
            q_meta = q.get("metadata") or {}
            q_cfg = q.get("retrieval_config") or {}
            gt_meta.update({
                "format": "v2",
                "chunk_ids": gt.get("chunk_ids") or [],
                "answer": gt.get("answer", ""),
                "category": q_meta.get("category"),
                "difficulty": q_meta.get("difficulty"),
                "tags": q_meta.get("tags"),
                "diagnostic_intent": q_quality.get("diagnostic_intent"),
                "rationale": q_quality.get("rationale"),
                "max_allowed_distance": q_quality.get("max_allowed_distance"),
                "retrieval_config": q_cfg,
            })
            gt_out = {**gt, "metadata": gt_meta}
        else:
            gt_out = {"chunks": [], "metadata": {"format": "v2"}}
        internal_questions.append(text)
        internal_ground_truths.append(gt_out)

    if not internal_questions:
        raise ValidationException("v2 数据集 questions 不能为空")

    dataset = await evaluation_service.create_dataset(
        db=db,
        kb_id=payload.kb_id,
        name=payload.name,
        questions=internal_questions,
        ground_truths=internal_ground_truths,
        created_by=current_user.id,
    )
    # 返回 v2 原始 payload 供前端识别（叠加 id）
    return {
        "id": str(dataset.id),
        "format": "v2",
        "version": payload.version,
        "name": dataset.name,
        "kb_id": str(dataset.kb_id),
        "questions_count": len(internal_questions),
        "_dataset_meta": payload._dataset_meta,
    }


@router.get(
    "/evaluation/datasets",
    response_model=List[EvaluationDatasetResponse],
)
async def list_datasets(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    return await evaluation_service.list_datasets(db, skip=skip, limit=limit, created_by=current_user.id)


# -------------- 任务相关（核心） --------------

@router.post(
    "/evaluation/tasks",
    response_model=EvaluationTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    payload: EvaluationTaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """创建任务并立即派发所有问题到 celery（高并发）。"""
    dataset = await evaluation_service.get_dataset(db, payload.dataset_id)
    if dataset is None:
        raise NotFoundException(f"Dataset {payload.dataset_id} not found")
    if not await evaluation_service.verify_kb(db, payload.kb_id):
        raise NotFoundException(f"Knowledge base {payload.kb_id} not found")

    task = await evaluation_service.create_task(
        db=db,
        dataset_id=payload.dataset_id,
        kb_id=payload.kb_id,
        metrics=payload.metrics,
        created_by=current_user.id,
    )
    # 创建 question_runs 并分发
    try:
        n = create_question_runs_and_dispatch(task.id, current_user.id)
        logger.info("Task %s: dispatched %s question runs", task.id, n)
    except Exception as exc:
        logger.exception("Dispatch failed: %s", exc)
        # 不致命，标记 task 失败
        await evaluation_service.update_task_status(db, task, "failed", {"error": f"Dispatch failed: {exc}"})

    return task


@router.get(
    "/evaluation/tasks",
    response_model=List[EvaluationTaskResponse],
)
async def list_tasks(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    return await evaluation_service.list_tasks(db, skip=skip, limit=limit, created_by=current_user.id)


@router.get(
    "/evaluation/tasks/{task_id}",
    response_model=EvaluationTaskResponse,
)
async def get_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    task = await evaluation_service.get_task(db, task_id)
    if task is None:
        raise NotFoundException(f"Evaluation task {task_id} not found")
    return task


@router.get(
    "/evaluation/metrics",
    response_model=EvaluationMetricsResponse,
)
async def list_metrics(current_user: UserResponse = Depends(get_current_user)):
    return {"metrics": evaluation_service.available_metrics()}


# -------------- 细粒度控制 --------------

@router.get(
    "/evaluation/tasks/{task_id}/questions",
    response_model=List[QuestionRunResponse],
)
async def list_question_runs(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """列出任务的所有问题运行状态（供前端状态栏轮询）。"""
    task = await evaluation_service.get_task(db, task_id)
    if task is None:
        raise NotFoundException(f"Evaluation task {task_id} not found")
    q = select(EvaluationQuestionRun).where(
        EvaluationQuestionRun.task_id == task_id,
    ).order_by(EvaluationQuestionRun.question_index)
    rows = (await db.execute(q)).scalars().all()
    return [_to_qr(r) for r in rows]


@router.post(
    "/evaluation/tasks/{task_id}/pause",
)
async def pause_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """暂停任务。未开始的 pending 问题将立即标记为 paused。"""
    task = await evaluation_service.get_task(db, task_id)
    if task is None:
        raise NotFoundException(f"Evaluation task {task_id} not found")
    set_task_pause(task_id, paused=True)
    await db.refresh(task)
    return {"task_id": str(task.id), "status": task.status}


@router.post(
    "/evaluation/tasks/{task_id}/resume",
)
async def resume_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """恢复任务。重置 paused 状态为 pending 并重新分发。"""
    task = await evaluation_service.get_task(db, task_id)
    if task is None:
        raise NotFoundException(f"Evaluation task {task_id} not found")
    n = set_task_pause(task_id, paused=False)
    return {"task_id": str(task_id), "re_dispatched": n, "status": "running"}


@router.post(
    "/evaluation/tasks/{task_id}/retry",
)
async def retry_task(
    task_id: UUID,
    only_failed: bool = Query(True, description="True=只重试失败的；False=全部非 completed 的"),
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """断点续测：重试 task 内的失败/未完成问题。"""
    task = await evaluation_service.get_task(db, task_id)
    if task is None:
        raise NotFoundException(f"Evaluation task {task_id} not found")
    n = await retry_question_runs(task_id, only_failed=only_failed)
    # 即便没有可重试的题，也触发 finalize（解决历史 task 卡在 pending 的问题）
    from app.workers.eval_tasks import _finalize_task_status_sync
    _finalize_task_status_sync(task_id)
    return {"task_id": str(task_id), "re_dispatched": n}


@router.post(
    "/evaluation/tasks/{task_id}/finalize",
)
async def finalize_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """手动触发 watchdog finalize（用于修复历史 task 卡在 pending 但所有题已 completed 的情况）。"""
    from app.workers.eval_tasks import _finalize_task_status_sync
    _finalize_task_status_sync(task_id)
    return {"task_id": str(task_id), "status": "finalized"}


@router.post(
    "/evaluation/questions/{run_id}/retry",
)
async def retry_single_question(
    run_id: UUID,
    current_user: UserResponse = Depends(get_current_user),
):
    """重试单个问题。"""
    from app.workers.eval_tasks import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        run = await session.get(EvaluationQuestionRun, run_id)
        if run is None:
            raise NotFoundException(f"Question run {run_id} not found")
        run.status = "pending"
        run.error = None
        await session.commit()
        dispatch_question_runs(run.task_id)
    return {"run_id": str(run_id), "status": "pending"}


@router.post(
    "/evaluation/questions/{run_id}/skip",
)
async def skip_single_question(
    run_id: UUID,
    current_user: UserResponse = Depends(get_current_user),
):
    """跳过单个问题。"""
    ok = skip_question_run(run_id)
    if not ok:
        raise NotFoundException(f"Question run {run_id} not found")
    return {"run_id": str(run_id), "status": "skipped"}


@router.get(
    "/evaluation/worker/stats",
)
async def worker_stats(current_user: UserResponse = Depends(get_current_user)):
    """查看 celery worker 当前统计。"""
    from app.workers.celery_app import celery_app
    try:
        inspect = celery_app.control.inspect(timeout=1.5)
        active = inspect.active() or {}
        registered = inspect.registered() or {}
        return {
            "active_by_worker": {k: len(v) for k, v in active.items()},
            "registered_tasks": list(next(iter(registered.values()), [])),
            "total_workers": len(active),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _extract_v2_metadata(r: EvaluationQuestionRun) -> dict:
    """从 ground_truths metadata 字段提取 v2 元数据（透传给前端）。"""
    # 1. 优先从 metrics 拿
    metrics = r.metrics or {}
    if isinstance(metrics, dict) and metrics.get("v2_metadata"):
        return metrics["v2_metadata"]

    # 2. fall back: 找不到就走通用字段
    return {}


def _to_qr(r: EvaluationQuestionRun) -> dict:
    payload = {
        "id": r.id,
        "task_id": r.task_id,
        "question_index": r.question_index,
        "question": r.question,
        "status": r.status,
        "retrieved_chunk_ids": r.retrieved_chunk_ids or [],
        "generated_answer": r.generated_answer,
        "metrics": r.metrics or {},
        "error": r.error,
        "attempts": r.attempts,
        "started_at": r.started_at,
        "completed_at": r.completed_at,
    }
    # 透传 v2 metadata（category/diagnostic_intent/max_allowed_distance 等）
    v2_meta = _extract_v2_metadata(r)
    if v2_meta:
        payload["v2_metadata"] = v2_meta
    return payload


# ---------------------------------------------------------------------------
# v2 架构对齐评测数据集模板下载
# ---------------------------------------------------------------------------
# 模板从 scripts/eval/datasets/ups_v2_arch_aligned.json 读取，
# 让前端 EvalWorkbench 一键下载作为示例。
# ---------------------------------------------------------------------------

@router.get("/evaluation/templates/dataset")
async def get_dataset_template(
    version: str = Query("v2", description="模板版本：v1 (JSONL) 或 v2 (JSON+元数据)"),
):
    """下载评测数据集模板（v1 JSONL / v2 JSON 顶层）。

    GET /api/v1/evaluation/templates/dataset?version=v2

    返回原始 JSON，前端触发文件下载。
    """
    from pathlib import Path
    # backend/app/api/v1/eval.py → parents[4] 是 backend；parents[5] 是 repo 根
    # 但容器内只有 backend（/app），所以先尝试 repo 根，找不到再尝试 /app 相对路径
    repo_root = Path(__file__).resolve().parents[4]  # backend/
    candidates = {
        "v2": [
            repo_root / "scripts" / "eval" / "datasets" / "ups_v2_arch_aligned.json",
            repo_root.parent / "scripts" / "eval" / "datasets" / "ups_v2_arch_aligned.json",
            Path("/app/scripts/eval/datasets/ups_v2_arch_aligned.json"),
        ],
        "v1": [
            repo_root / "scripts" / "eval" / "datasets" / "ups_v1.jsonl",
            repo_root.parent / "scripts" / "eval" / "datasets" / "ups_v1.jsonl",
            Path("/app/scripts/eval/datasets/ups_v1.jsonl"),
        ],
    }
    # 取第一个存在的
    paths = {k: next((p for p in v if p.exists()), None) for k, v in candidates.items()}
    path = paths.get(version)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"模板不存在：version={version} (available: {list(candidates.keys())})",
        )
    content = path.read_text(encoding="utf-8")
    # 后端把 JSON 字符串原样返回（JSON content type），前端拿到后用 Blob 下载
    return JSONResponse(
        content={"version": version, "filename": path.name, "content": content},
    )
