"""Conversation and message service."""
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.message import Message


class ConversationService:
    """会话管理服务：创建/查询/删除会话以及消息增删改查。"""

    async def create_conversation(
        self,
        db: AsyncSession,
        user_id: UUID,
        title: str,
        kb_ids: List[UUID],
    ) -> Conversation:
        """创建新会话。"""
        conversation = Conversation(
            user_id=user_id,
            title=title or "新会话",
            kb_ids=[str(k) for k in kb_ids],
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        return conversation

    async def list_conversations(
        self,
        db: AsyncSession,
        user_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Conversation]:
        """列出用户的会话，按更新时间倒序。"""
        result = await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(desc(Conversation.updated_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_conversation(
        self,
        db: AsyncSession,
        conversation_id: UUID,
        user_id: UUID,
    ) -> Optional[Conversation]:
        """获取单个会话并校验归属。"""
        result = await db.execute(
            select(Conversation).where(
                and_(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def delete_conversation(
        self,
        db: AsyncSession,
        conversation_id: UUID,
        user_id: UUID,
    ) -> bool:
        """删除会话（级联删除消息）。"""
        conversation = await self.get_conversation(db, conversation_id, user_id)
        if not conversation:
            return False
        await db.delete(conversation)
        await db.commit()
        return True

    async def add_message(
        self,
        db: AsyncSession,
        conversation_id: UUID,
        role: str,
        content: str,
        sources: Optional[List[Dict[str, Any]]] = None,
        candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> Message:
        """向会话中添加一条消息。

        candidates 为可选参数（仅 assistant 消息使用），存的是已过五级穿透、
        L5 降级后的候选列表，写入前不再二次取原文（五级兼容 P1/P2）。
        不传或传 None 时行为与原逻辑完全一致（candidates 列保持 NULL）。
        """
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            sources=sources or [],
            candidates=candidates,
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        return message

    async def get_messages(
        self,
        db: AsyncSession,
        conversation_id: UUID,
        user_id: UUID,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Message]:
        """获取会话中的消息，按创建时间正序。"""
        # 校验会话归属
        conversation = await self.get_conversation(db, conversation_id, user_id)
        if not conversation:
            return []
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def update_feedback(
        self,
        db: AsyncSession,
        message_id: UUID,
        user_id: UUID,
        rating: int,
        comment: Optional[str] = None,
    ) -> Optional[Message]:
        """更新消息反馈。"""
        result = await db.execute(
            select(Message)
            .join(Conversation)
            .where(
                and_(
                    Message.id == message_id,
                    Conversation.user_id == user_id,
                )
            )
        )
        message = result.scalar_one_or_none()
        if not message:
            return None
        message.feedback_rating = rating
        message.feedback_comment = comment
        await db.commit()
        await db.refresh(message)
        return message

    async def build_history_messages(
        self,
        db: AsyncSession,
        conversation_id: UUID,
        user_id: UUID,
        max_history_turns: int = 10,
    ) -> List[Dict[str, str]]:
        """
        将会话历史构建为 LLM 可用的 messages 列表。
        每个 user/assistant 消息为一个消息对（turn），最多保留最近 max_history_turns 对。
        """
        messages = await self.get_messages(db, conversation_id, user_id)
        # 排除系统消息，按时间顺序
        history = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        # 保持为完整的 user/assistant 消息对，避免最后一条未完成的 assistant 消息重复
        # 保留最近的 max_history_turns 对，即 2 * max_history_turns 条消息
        max_len = max_history_turns * 2
        return history[-max_len:]


conversation_service = ConversationService()
