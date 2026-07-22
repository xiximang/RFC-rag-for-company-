"""Evaluation service: datasets, tasks and metric calculation."""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import EvaluationDataset, EvaluationTask
from app.models.knowledge_base import KnowledgeBase
from app.services.generation_service import generation_service
from app.services.llm_client import llm_client
from app.services.retrieval_service import retrieval_service

logger = logging.getLogger(__name__)

_PROMPT_INJECTION_BLOCKED_RESPONSE = "此问题被安全策略拦截，未生成答案"
_DEFAULT_METRICS = ["recall@3", "mrr", "ndcg@3", "faithfulness", "relevance", "coherence"]

_METRIC_DESCRIPTIONS = [
    {
        "name": "recall@k",
        "params": [{"name": "k", "type": "int", "default": 3}],
        "description": "召回率：ground truth 相关片段中出现在前 K 个检索结果里的比例",
    },
    {
        "name": "mrr",
        "description": "平均倒数排名：首个相关片段排名的倒数均值",
    },
    {
        "name": "ndcg@k",
        "params": [{"name": "k", "type": "int", "default": 3}],
        "description": "归一化折损累计增益：考虑相关片段在排序中的位置",
    },
    {
        "name": "faithfulness",
        "description": "忠实度：生成答案是否被检索上下文支持（LLM judge + 关键词回退）",
    },
    {
        "name": "relevance",
        "description": "相关性：生成答案是否与问题相关（LLM judge + 关键词回退）",
    },
    {
        "name": "coherence",
        "description": "连贯性：生成答案是否通顺连贯（LLM judge + 统计回退）",
    },
]


def _tokenize(text: str) -> set:
    """简单中文/英文分词：按非字母数字汉字切分。"""
    return set(re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower()))


def _extract_score(text: str) -> Optional[float]:
    """从 LLM 输出中提取 0-1 之间的分数。"""
    matches = re.findall(r"[-+]?\d*\.?\d+", text)
    for m in matches:
        try:
            value = float(m)
            if 0.0 <= value <= 1.0:
                return value
            if 0 <= value <= 100:
                return value / 100.0
        except ValueError:
            continue
    return None


class EvaluationService:
    """评测服务：管理数据集、任务并执行评测。"""

    # ---------- dataset CRUD ----------

    async def create_dataset(
        self,
        db: AsyncSession,
        kb_id: UUID,
        name: str,
        questions: List[str],
        ground_truths: List[Dict[str, Any]],
        created_by: Optional[UUID] = None,
    ) -> EvaluationDataset:
        """Create an evaluation dataset."""
        dataset = EvaluationDataset(
            kb_id=kb_id,
            name=name,
            questions=questions or [],
            ground_truths=ground_truths or [],
            created_by=created_by,
        )
        db.add(dataset)
        await db.commit()
        await db.refresh(dataset)
        return dataset

    async def list_datasets(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        created_by: Optional[UUID] = None,
    ) -> List[EvaluationDataset]:
        """List evaluation datasets."""
        stmt = select(EvaluationDataset)
        if created_by is not None:
            stmt = stmt.where(EvaluationDataset.created_by == created_by)
        stmt = stmt.offset(skip).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_dataset(self, db: AsyncSession, dataset_id: UUID) -> Optional[EvaluationDataset]:
        """Fetch a dataset by ID."""
        return await db.get(EvaluationDataset, dataset_id)

    # ---------- task CRUD ----------

    async def create_task(
        self,
        db: AsyncSession,
        dataset_id: UUID,
        kb_id: UUID,
        metrics: Optional[List[str]] = None,
        created_by: Optional[UUID] = None,
    ) -> EvaluationTask:
        """Create an evaluation task record."""
        task = EvaluationTask(
            dataset_id=dataset_id,
            kb_id=kb_id,
            status="pending",
            metrics=metrics or _DEFAULT_METRICS,
            results={},
            created_by=created_by,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task

    async def list_tasks(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        created_by: Optional[UUID] = None,
    ) -> List[EvaluationTask]:
        """List evaluation tasks."""
        stmt = select(EvaluationTask)
        if created_by is not None:
            stmt = stmt.where(EvaluationTask.created_by == created_by)
        stmt = stmt.offset(skip).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_task(self, db: AsyncSession, task_id: UUID) -> Optional[EvaluationTask]:
        """Fetch a task by ID."""
        return await db.get(EvaluationTask, task_id)

    async def update_task_status(
        self,
        db: AsyncSession,
        task: EvaluationTask,
        status: str,
        results: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update task status and optionally merge results."""
        task.status = status
        if results is not None:
            task.results = {**(task.results or {}), **results}
        if status in ("completed", "failed"):
            task.completed_at = datetime.now(timezone.utc)
        await db.commit()

    async def verify_kb(self, db: AsyncSession, kb_id: UUID) -> bool:
        """Verify that the target knowledge base exists."""
        kb = await db.get(KnowledgeBase, kb_id)
        return kb is not None

    # ---------- metric calculation ----------

    @staticmethod
    def recall_at_k(retrieved_ids: List[str], ground_truth_ids: List[str], k: int) -> float:
        """Recall@K: relevant retrieved / total relevant."""
        if not ground_truth_ids:
            return 0.0
        relevant = set(ground_truth_ids)
        retrieved_top_k = set(retrieved_ids[:k])
        if not relevant:
            return 0.0
        return len(relevant & retrieved_top_k) / len(relevant)

    @staticmethod
    def mrr(retrieved_ids: List[str], ground_truth_ids: List[str]) -> float:
        """Mean Reciprocal Rank: 1 / rank of first relevant item."""
        relevant = set(ground_truth_ids)
        for idx, rid in enumerate(retrieved_ids, start=1):
            if rid in relevant:
                return 1.0 / idx
        return 0.0

    @staticmethod
    def ndcg_at_k(retrieved_ids: List[str], ground_truth_ids: List[str], k: int) -> float:
        """NDCG@K with binary relevance."""
        relevant = set(ground_truth_ids)
        dcg = 0.0
        for idx, rid in enumerate(retrieved_ids[:k], start=1):
            rel = 1.0 if rid in relevant else 0.0
            dcg += rel / math.log2(idx + 1)

        ideal_rels = [1.0] * min(len(relevant), k)
        idcg = sum(rel / math.log2(idx + 1) for idx, rel in enumerate(ideal_rels, start=1))
        if idcg == 0.0:
            return 0.0
        return dcg / idcg

    async def llm_judge(
        self,
        prompt: str,
        fallback: float,
    ) -> float:
        """Call LLM as a judge and fall back to a heuristic score on failure."""
        try:
            response = await llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=100,
            )
            content = (
                response.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            score = _extract_score(content)
            if score is not None:
                return score
        except Exception as exc:
            logger.warning("LLM judge failed, using fallback: %s", exc)
        return fallback

    async def faithfulness_score(
        self,
        answer: str,
        context: str,
    ) -> float:
        """Faithfulness: answer supported by context."""
        answer_tokens = _tokenize(answer)
        context_tokens = _tokenize(context)
        if not answer_tokens:
            fallback = 0.0
        else:
            fallback = len(answer_tokens & context_tokens) / len(answer_tokens)

        prompt = (
            "请判断以下回答是否完全基于给定上下文，没有引入上下文外的信息。"
            "只返回 0 到 1 之间的一个数字，1 表示完全忠实，0 表示完全不忠实。\n\n"
            f"上下文：\n{context[:2000]}\n\n"
            f"回答：\n{answer[:1000]}\n\n"
            "分数："
        )
        return await self.llm_judge(prompt, fallback)

    async def relevance_score(
        self,
        question: str,
        answer: str,
    ) -> float:
        """Relevance: answer relevant to question."""
        question_tokens = _tokenize(question)
        answer_tokens = _tokenize(answer)
        union = question_tokens | answer_tokens
        fallback = len(question_tokens & answer_tokens) / len(union) if union else 0.0

        prompt = (
            "请判断以下回答是否与问题相关并有效回答了问题。"
            "只返回 0 到 1 之间的一个数字，1 表示完全相关，0 表示完全不相关。\n\n"
            f"问题：\n{question}\n\n"
            f"回答：\n{answer[:1000]}\n\n"
            "分数："
        )
        return await self.llm_judge(prompt, fallback)

    async def coherence_score(self, answer: str) -> float:
        """Coherence: answer is fluent and coherent."""
        sentences = re.split(r"[。！？.!?]", answer)
        sentences = [s.strip() for s in sentences if s.strip()]
        tokens = _tokenize(answer)
        if len(sentences) >= 2 and len(tokens) >= 5:
            fallback = min(1.0, 0.5 + 0.1 * len(sentences))
        else:
            fallback = min(1.0, max(0.0, len(tokens) / 10.0))

        prompt = (
            "请判断以下回答是否通顺、连贯、易于理解。"
            "只返回 0 到 1 之间的一个数字，1 表示非常连贯，0 表示完全不连贯。\n\n"
            f"回答：\n{answer[:1000]}\n\n"
            "分数："
        )
        return await self.llm_judge(prompt, fallback)

    # ---------- evaluation runner ----------

    async def run_evaluation(
        self,
        db: AsyncSession,
        task: EvaluationTask,
        user_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Run the evaluation task and return aggregated results."""
        await self.update_task_status(db, task, "running")

        dataset = await self.get_dataset(db, task.dataset_id)
        if dataset is None:
            raise ValueError(f"Dataset {task.dataset_id} not found")

        metrics = task.metrics or _DEFAULT_METRICS
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

        questions: List[str] = dataset.questions or []
        ground_truths: List[Dict[str, Any]] = dataset.ground_truths or []
        if len(questions) != len(ground_truths):
            raise ValueError("questions and ground_truths must have the same length")

        sample_results: List[Dict[str, Any]] = []
        metric_accumulators: Dict[str, List[float]] = {}

        for idx, (question, gt) in enumerate(zip(questions, ground_truths)):
            gt = gt or {}
            gt_chunk_ids = gt.get("chunk_ids") or []
            gt_answer = gt.get("answer") or ""

            sample: Dict[str, Any] = {"question_index": idx, "question": question}

            try:
                retrieved = await retrieval_service.search(
                    db=db,
                    user_id=user_id,
                    query=question,
                    kb_ids=[task.kb_id],
                    modalities=["text", "table", "link"],
                    top_k=10,
                    rerank_top_k=5,
                )
            except Exception as exc:
                logger.warning("Retrieval failed for question %s: %s", idx, exc)
                retrieved = []

            retrieved_ids = [str(r.get("chunk_id") or r.get("id")) for r in retrieved]
            sample["retrieved_chunk_ids"] = retrieved_ids

            # Retrieval metrics
            for metric_name, k in parsed_metrics:
                if metric_name == "recall" and k is not None:
                    score = self.recall_at_k(retrieved_ids, gt_chunk_ids, k)
                    key = f"recall@{k}"
                    sample[key] = score
                    metric_accumulators.setdefault(key, []).append(score)
                elif metric_name == "mrr":
                    score = self.mrr(retrieved_ids, gt_chunk_ids)
                    sample["mrr"] = score
                    metric_accumulators.setdefault("mrr", []).append(score)
                elif metric_name == "ndcg" and k is not None:
                    score = self.ndcg_at_k(retrieved_ids, gt_chunk_ids, k)
                    key = f"ndcg@{k}"
                    sample[key] = score
                    metric_accumulators.setdefault(key, []).append(score)

            # Generation and QA metrics
            qa_metrics = [m for m, _ in parsed_metrics if m in ("faithfulness", "relevance", "coherence")]
            if qa_metrics:
                try:
                    gen_result = await generation_service.generate_answer(
                        db=db,
                        query=question,
                        context_chunks=retrieved,
                        user_id=user_id,
                        stream=False,
                    )
                    answer = gen_result.get("answer", "")
                    intercepted = gen_result.get("intercepted", False)
                except Exception as exc:
                    logger.warning("Generation failed for question %s: %s", idx, exc)
                    answer = ""
                    intercepted = True

                sample["answer"] = answer
                sample["intercepted"] = intercepted
                context_text = "\n\n".join(r.get("content", "") for r in retrieved)

                for metric_name in qa_metrics:
                    if metric_name == "faithfulness":
                        score = await self.faithfulness_score(answer, context_text)
                    elif metric_name == "relevance":
                        score = await self.relevance_score(question, answer)
                    elif metric_name == "coherence":
                        score = await self.coherence_score(answer)
                    else:
                        continue
                    sample[metric_name] = score
                    metric_accumulators.setdefault(metric_name, []).append(score)

            sample_results.append(sample)

        aggregated: Dict[str, Any] = {
            key: round(sum(values) / len(values), 4) if values else 0.0
            for key, values in metric_accumulators.items()
        }
        aggregated["sample_count"] = len(sample_results)
        aggregated["samples"] = sample_results

        results = {
            "aggregated": aggregated,
            "metrics": list(metric_accumulators.keys()),
        }
        await self.update_task_status(db, task, "completed", results)
        return results

    # 单问题执行：用于新细粒度调度
    # ----------------------------------------------------------------

    async def run_single_question(
        self,
        db: AsyncSession,
        task: EvaluationTask,
        question: str,
        gt_chunk_ids: List[str],
        gt_answer: str,
        metrics: List[str],
        user_id: UUID | None = None,
    ) -> Dict[str, Any]:
        """执行单个问题的检索与生成，返回该问题的指标字典与原文。"""
        # ---- 1) 解析指标 ----
        parsed_metrics: List[tuple] = []
        for m in metrics or []:
            if "@" in m:
                name, k_str = m.split("@", 1)
                try:
                    parsed_metrics.append((name, int(k_str)))
                except ValueError:
                    parsed_metrics.append((m, None))
            else:
                parsed_metrics.append((m, None))

        # ---- 2) 检索 ----
        try:
            retrieved = await retrieval_service.search(
                db=db,
                user_id=user_id,
                query=question,
                kb_ids=[task.kb_id],
                modalities=["text", "table", "link"],
                top_k=10,
                rerank_top_k=5,
            )
        except Exception as exc:
            logger.warning("Retrieval failed for question: %s", exc)
            retrieved = []

        retrieved_ids = [str(r.get("chunk_id") or r.get("id")) for r in retrieved]
        retrieved_chunks_payload = [
            {"chunk_id": str(r.get("chunk_id") or r.get("id")), "content": r.get("content", "")}
            for r in retrieved
        ]

        metric_scores: Dict[str, float] = {}

        # ---- 3) 检索指标 ----
        for metric_name, k in parsed_metrics:
            if metric_name == "recall" and k is not None:
                score = self.recall_at_k(retrieved_ids, gt_chunk_ids, k)
                metric_scores[f"recall@{k}"] = score
            elif metric_name == "mrr":
                metric_scores["mrr"] = self.mrr(retrieved_ids, gt_chunk_ids)
            elif metric_name == "ndcg" and k is not None:
                metric_scores[f"ndcg@{k}"] = self.ndcg_at_k(retrieved_ids, gt_chunk_ids, k)

        # ---- 4) 生成 + 生成指标 ----
        qa_metrics = [m for m, _ in parsed_metrics if m in ("faithfulness", "relevance", "coherence")]
        generated_answer = ""
        intercepted = False
        if qa_metrics:
            try:
                generated_answer, intercepted = await self._generate_answer(
                    db=db, question=question, retrieved=retrieved_chunks_payload
                )
            except Exception as exc:
                logger.warning("Answer generation failed: %s", exc)
                generated_answer = ""
                intercepted = True
            context_text = "\n\n".join(c["content"] for c in retrieved_chunks_payload)
            for metric_name in qa_metrics:
                if metric_name == "faithfulness":
                    metric_scores["faithfulness"] = await self.faithfulness_score(generated_answer, context_text)
                elif metric_name == "relevance":
                    metric_scores["relevance"] = await self.relevance_score(question, generated_answer)
                elif metric_name == "coherence":
                    metric_scores["coherence"] = await self.coherence_score(generated_answer)

        # 转换所有 numpy / float 值为原生 float 便于 JSON 序列化
        out_metrics: Dict[str, float] = {}
        for k, v in metric_scores.items():
            try:
                out_metrics[k] = round(float(v), 4)
            except Exception:
                pass

        return {
            "retrieved_chunk_ids": retrieved_ids,
            "generated_answer": generated_answer,
            "metrics": out_metrics,
        }

    async def _generate_answer(self, db: AsyncSession, question: str, retrieved: list) -> tuple[str, bool]:
        """生成答案（与 run_evaluation 同样的方式，但只针对单问题）。"""
        from app.services.llm_client import llm_client
        from app.services.evaluation_service import _PROMPT_INJECTION_BLOCKED_RESPONSE

        context_text = "\n\n".join(c["content"] for c in retrieved)
        if not context_text:
            context_text = "（无相关上下文）"

        # Prompt injection 检测（与现有 L4 逻辑保持一致）
        try:
            from app.core.prompt_injection import check_prompt_injection
            question_safe, was_intercepted, _ = await check_prompt_injection(question)
            if not question_safe:
                return _PROMPT_INJECTION_BLOCKED_RESPONSE, True
        except Exception:
            pass

        try:
            response = await llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": "你是一名严谨的助手，根据上下文回答用户的问题。如果上下文不足，请回答'没有足够信息'。"},
                    {"role": "user", "content": f"问题：{question}\n\n上下文：\n{context_text[:3000]}\n\n回答："},
                ],
                temperature=0.1,
                max_tokens=500,
            )
            return (
                response.get("choices", [{}])[0].get("message", {}).get("content", ""),
                False,
            )
        except Exception as exc:
            logger.warning("LLM generation failed: %s", exc)
            return "", True
    def available_metrics(self) -> List[Dict[str, Any]]:
        """Return metadata for all supported metrics."""
        return list(_METRIC_DESCRIPTIONS)


evaluation_service = EvaluationService()
