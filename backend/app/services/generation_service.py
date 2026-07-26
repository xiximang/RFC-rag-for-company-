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
        history: Optional[List[Dict[str, str]]] = None
    ) -> Any:
        """生成回答"""
        import time

        start = time.perf_counter()
        model = get_model_config().get("LLM_MODEL") or getattr(settings, "LLM_MODEL", "unknown")
        status = "ok"
        try:
            return await self._generate_answer(
                db, query, context_chunks, user_id, stream, history
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
        history: Optional[List[Dict[str, str]]] = None
    ) -> Any:
        """Internal generation implementation."""
        context_text = self._build_context(context_chunks)
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
