from typing import List, Dict, Any, Optional, AsyncIterator
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipelines.keyword_annotator import KeywordAnnotator, LEVEL_ORDER
from app.config import settings
from app.core.metrics import rag_generation_duration_seconds
from app.core.runtime_config import get_model_config
from app.services.keyword_service import KeywordService
from app.services.llm_client import llm_client

class GenerationService:
    """生成服务：构造Prompt、调用LLM、后处理与关键词拦截"""

    SYSTEM_PROMPT = """你是一个企业级私有RAG助手。请基于以下检索到的上下文回答用户问题。
注意事项：
1. 仅使用提供的上下文，不要编造信息
2. 如果上下文不足，请明确说明
3. 注意上下文中的权限标记，不要泄露超出用户权限级别的敏感信息
4. 引用来源时标注[doc_index]
"""

    # 流式生成复用的全局 KeywordAnnotator，在应用启动时加载
    _stream_annotator: Optional[KeywordAnnotator] = None

    @classmethod
    def load_stream_annotator(cls, keywords: List[Any]) -> None:
        """加载关键词到流式拦截器。由应用启动时调用。"""
        annotator = KeywordAnnotator()
        annotator.load_keywords(keywords)
        cls._stream_annotator = annotator

    @classmethod
    def reset_stream_annotator(cls) -> None:
        """关键词变更后重置，下次使用前重新加载。"""
        cls._stream_annotator = None

    async def generate_answer(
        self,
        db: AsyncSession,
        query: str,
        context_chunks: List[Dict[str, Any]],
        user_id: UUID,
        stream: bool = False,
        history: Optional[List[Dict[str, str]]] = None,
        max_context_tokens: int = 4000,
    ) -> Any:
        """生成回答"""
        import time

        start = time.perf_counter()
        model = get_model_config().get("LLM_MODEL") or getattr(settings, "LLM_MODEL", "unknown")
        status = "ok"
        try:
            return await self._generate_answer(
                db, query, context_chunks, user_id, stream, history, max_context_tokens,
            )
        except Exception:
            status = "error"
            raise
        finally:
            rag_generation_duration_seconds.labels(
                model=model, status=status
            ).observe(time.perf_counter() - start)

    async def _generate_answer(
        self,
        db: AsyncSession,
        query: str,
        context_chunks: List[Dict[str, Any]],
        user_id: UUID,
        stream: bool = False,
        history: Optional[List[Dict[str, str]]] = None,
        max_context_tokens: int = 4000,
    ) -> Any:
        """Internal generation implementation."""
        context_text = self._build_context(context_chunks)

        # ── Prompt 裁剪：超预算时压缩早期对话轮次 ──
        # 总预算 = max_context_tokens × 3（粗略 chars→tokens 换算）
        # 优先级（高→低）：query > system > context > 近期完整历史 > 早期摘要
        if history:
            budget_chars = max_context_tokens * 3
            fixed_chars = len(self.SYSTEM_PROMPT) + len(context_text) + len(query)
            history_budget = budget_chars - fixed_chars
            if history_budget < 200:
                history_budget = 200  # 至少留 200 chars 给历史，不返回空
            history = self._trim_history(history, history_budget)

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
        ]
        if history:
            messages.extend(history)
        messages.append(
            {"role": "user", "content": f"上下文：\n{context_text}\n\n问题：{query}"}
        )

        if stream:
            return self._stream_with_intercept(messages, context_chunks, user_id)
        else:
            response = await llm_client.chat_completion(messages)
            answer = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            return await self._post_process(db, answer, context_chunks, user_id)
    
    async def _stream_with_intercept(
        self,
        messages: List[Dict[str, str]],
        context_chunks: List[Dict[str, Any]],
        user_id: UUID
    ) -> AsyncIterator[str]:
        """流式生成，实时关键词拦截"""
        buffer = ""
        async for token in llm_client.chat_completion_stream(messages):
            buffer += token
            # 检查最近200字符是否触发敏感词
            check_text = buffer[-200:]
            result = await self._check_stream_intercept(check_text, user_id)
            if result:
                yield "\n[检测到敏感内容，输出已截断]"
                break
            yield token
    
    async def _check_stream_intercept(self, text: str, user_id: UUID) -> bool:
        """检查流式输出片段是否需要拦截。

        使用全局 KeywordAnnotator 检测文本中是否出现超出用户安全等级的敏感关键词。
        拦截器未加载时默认放行，避免阻塞正常输出。
        """
        from app.services.permission_service import PermissionService

        if not self._stream_annotator:
            return False

        result = self._stream_annotator.annotate(text)
        if not result.matches:
            return False

        # 获取用户安全等级，判断关键词等级是否超出
        # 流式场景没有 db session，使用缓存或默认 L0
        from app.core.cache import CacheManager
        cache = CacheManager()
        user_level = await cache.get_user_security_level(str(user_id))
        user_level = user_level or "L0"

        for match in result.matches:
            if LEVEL_ORDER.get(match.level, 0) > LEVEL_ORDER.get(user_level, 0):
                return True
        return False
    
    def _build_context(self, chunks: List[Dict[str, Any]]) -> str:
        parts = []
        for i, chunk in enumerate(chunks):
            content = chunk.get("content", "")
            level = chunk.get("max_keyword_level", "L0")
            perm_tag = f'<perm level="{level}"/>'
            parts.append(f"[{i}] {perm_tag} {content}")
        return "\n\n".join(parts)

    @staticmethod
    def _estimate_chars(text: str) -> int:
        """粗略估算字符数（中英文混合）。"""
        return len(text)

    @staticmethod
    def _trim_history(
        history: List[Dict[str, str]],
        budget_chars: int,
    ) -> List[Dict[str, str]]:
        """按字符预算裁剪历史。

        超出预算时，从最老的对话轮次开始压缩为单行摘要。
        预算充足时不做任何改动。
        """
        if not history:
            return history

        current = sum(len(m["content"]) for m in history)
        if current <= budget_chars:
            return history

        result = list(history)
        while result and sum(len(m["content"]) for m in result) > budget_chars:
            if len(result) < 2:
                # 只剩一条，直接截断
                if len(result[0]["content"]) > budget_chars:
                    result[0]["content"] = result[0]["content"][:budget_chars] + "…"
                break

            # 从最早的一对 (user, assistant) 开始压缩
            user_msg = result.pop(0)
            asst_msg = result.pop(0)
            summary = (
                f"[历史] Q: {user_msg['content'][:40]}… "
                f"A: {asst_msg['content'][:60]}…"
            )
            result.insert(0, {"role": "user", "content": summary})

        return result
    
    async def _post_process(
        self,
        db: AsyncSession,
        answer: str,
        context_chunks: List[Dict[str, Any]],
        user_id: UUID
    ) -> Dict[str, Any]:
        """后处理：关键词拦截、权限检查"""
        keyword_service = KeywordService(db)
        
        # 构造Chunk对象列表用于拦截检查（这里用简化dict模拟）
        # keyword_service.intercept_response 期望 List[Chunk]，我们构造伪Chunk
        pseudo_chunks = []
        for chunk in context_chunks:
            from app.models.chunk import Chunk
            c = Chunk(id=UUID(chunk["chunk_id"]), content=chunk["content"])
            c.metadata_ = {
                "max_keyword_level": chunk.get("max_keyword_level", "L0"),
                "max_keyword_level_value": chunk.get("max_keyword_level_value", 0),
            }
            pseudo_chunks.append(c)
        
        intercept = await keyword_service.intercept_response(answer, pseudo_chunks, user_id)
        if not intercept.allowed:
            return {
                "answer": intercept.message or "对不起，无法回答该问题。",
                "intercepted": True,
                "sources": []
            }
        
        sources = []
        for chunk in context_chunks:
            position_info = chunk.get("position_info") or {}
            score = chunk.get("rerank_score")
            if score is None:
                score = chunk.get("score", 0)
            sources.append({
                "doc_id": chunk.get("doc_id"),
                "chunk_id": chunk.get("chunk_id"),
                "content": chunk.get("content", "")[:200],
                "score": score,
                "modality": chunk.get("modality", "text"),
                "position_info": position_info,
                "page": position_info.get("page"),
                "sheet": position_info.get("sheet"),
                "timestamp": position_info.get("timestamp"),
            })

        return {
            "answer": answer,
            "intercepted": False,
            "sources": sources
        }

generation_service = GenerationService()
