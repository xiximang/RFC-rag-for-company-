"""评测数据集 JSON 标准格式校验器。

支持的 JSON 格式：

1. **直接数组（最简单）**
   ```json
   [
     {"question": "问题1", "ground_truth": {"chunk_ids": ["id1"], "answer": "答案1"}},
     {"question": "问题2", "ground_truth": {"answer": "答案2"}}
   ]
   ```

2. **包装格式（推荐）**
   ```json
   {
     "name": "数据集名（可选，不填则用 filename）",
     "kb_id": "uuid（可选，前端表单选择优先）",
     "questions": [
       {"question": "...", "ground_truth": {...}, "metadata": {...}}
     ]
   }
   ```

3. **兼容旧格式**
   ```json
   {
     "questions": ["问题1", "问题2"],
     "ground_truths": [{"chunk_ids": ["id1"]}, {"answer": "..."}]
   }
   ```
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError

from app.schemas.evaluation import (
    DatasetItem,
    DatasetUploadResponse,
    GroundTruthEntry,
)


def parse_and_validate(
    raw_bytes: bytes,
    *,
    fallback_name: Optional[str] = None,
    fallback_kb_id: Optional[UUID] = None,
) -> DatasetUploadResponse:
    """解析 JSON 字节流并按标准格式校验。

    返回 DatasetUploadResponse: 包含 valid、errors、warnings 与解析后的 items。
    - valid=True 表示校验通过，可直接用于创建数据集。
    - valid=False 表示 errors 非空，前端应展示给用户修改。
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1. 解析 JSON
    text = raw_bytes.decode("utf-8-sig", errors="replace").strip()
    if not text:
        return DatasetUploadResponse(
            valid=False, errors=["文件为空"]
        )

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return DatasetUploadResponse(
            valid=False, errors=[f"JSON 解析失败：{exc.msg} (第 {exc.lineno} 行第 {exc.colno} 列)"]
        )

    # 2. 适配三种格式
    name: Optional[str] = None
    kb_id: Optional[UUID] = None
    raw_items: List[Dict[str, Any]] = []

    if isinstance(data, list):
        # 格式 1：直接数组
        raw_items = [x for x in data if isinstance(x, dict)]
    elif isinstance(data, dict):
        name = data.get("name")
        if data.get("kb_id"):
            try:
                kb_id = UUID(str(data["kb_id"]))
            except (ValueError, TypeError):
                warnings.append(f"kb_id='{data['kb_id']}' 不是合法 UUID，已忽略")

        if "questions" in data and isinstance(data["questions"], list):
            # 格式 2/3：questions 字段
            qs = data["questions"]
            if qs and isinstance(qs[0], dict):
                # 格式 2：标准包装
                raw_items = list(qs)
            elif all(isinstance(q, str) for q in qs):
                # 格式 3：旧式 questions/ground_truths
                gts = data.get("ground_truths") or []
                if not isinstance(gts, list):
                    errors.append("ground_truths 必须是列表")
                    gts = []
                if gts and len(gts) != len(qs):
                    warnings.append(
                        f"ground_truths ({len(gts)}) 与 questions ({len(qs)}) 数量不一致，"
                        "将尝试按索引对齐（缺失项留空）"
                    )
                for idx, q in enumerate(qs):
                    gt = gts[idx] if idx < len(gts) and isinstance(gts[idx], dict) else {}
                    raw_items.append({"question": q, "ground_truth": gt})
            else:
                errors.append("questions 字段必须是字符串列表或对象列表")
        elif "items" in data and isinstance(data["items"], list):
            raw_items = [x for x in data["items"] if isinstance(x, dict)]
        else:
            errors.append("JSON 对象必须包含 'questions' 或 'items' 字段之一")
    else:
        return DatasetUploadResponse(
            valid=False, errors=[f"JSON 顶层必须是数组或对象，实际为 {type(data).__name__}"]
        )

    if not raw_items:
        return DatasetUploadResponse(valid=False, errors=["文件中没有任何问题条目"])

    # 3. 用 Pydantic 逐条校验
    items: List[DatasetItem] = []
    for idx, raw in enumerate(raw_items):
        try:
            # 兜底：如果用户写的是 question/q，统一为 question
            if "question" not in raw and "q" in raw:
                raw["question"] = raw.pop("q")
            # ground_truth 兜底为 gt
            if "ground_truth" not in raw and "gt" in raw:
                raw["ground_truth"] = raw.pop("gt")

            item = DatasetItem.model_validate(raw)
            items.append(item)
        except PydanticValidationError as exc:
            errs = exc.errors()
            msg = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in errs
            )
            errors.append(f"第 {idx + 1} 条：{msg}")

    # 4. 应用 fallback
    if not name and fallback_name:
        name = fallback_name
    if not kb_id and fallback_kb_id:
        kb_id = fallback_kb_id
    if not name:
        warnings.append("未提供 'name' 字段，请在创建时填写数据集名称")
    if not kb_id:
        warnings.append("未提供 'kb_id' 字段，请在创建时选择知识库")

    # 5. 统计警告
    no_chunk_ids = sum(1 for it in items if not it.ground_truth.chunk_ids)
    no_answer = sum(1 for it in items if not it.ground_truth.answer)
    if items and no_chunk_ids == len(items):
        warnings.append("所有条目都没有 'chunk_ids'，召回/mrr/ndcg 指标将无法计算")
    if items and no_answer == len(items):
        warnings.append("所有条目都没有 'answer'，faithfulness/relevance/coherence 指标将无法计算")

    return DatasetUploadResponse(
        valid=len(errors) == 0 and len(items) > 0,
        name=name,
        kb_id=kb_id,
        item_count=len(items),
        items=items,
        errors=errors,
        warnings=warnings,
    )


def to_dataset_create_payload(
    parsed: DatasetUploadResponse,
    *,
    name: str,
    kb_id: UUID,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """把校验通过的 items 转成 (questions, ground_truths) 元组，方便复用现有 service。"""
    questions = [it.question for it in parsed.items]
    ground_truths = []
    for it in parsed.items:
        gt: Dict[str, Any] = {}
        if it.ground_truth.chunk_ids:
            gt["chunk_ids"] = list(it.ground_truth.chunk_ids)
        if it.ground_truth.answer:
            gt["answer"] = it.ground_truth.answer
        # 透传额外字段
        for k, v in it.ground_truth.model_extra.items() if hasattr(it.ground_truth, "model_extra") else []:
            gt[k] = v
        if it.metadata:
            gt["metadata"] = it.metadata
        ground_truths.append(gt)
    return questions, ground_truths
