"""IM 集成 API 请求/响应模型（P2 占位）。"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class IMSendRequest(BaseModel):
    platform: str = Field(
        ...,
        pattern="^(wecom|feishu|dingtalk)$",
        description="IM 平台：wecom / feishu / dingtalk",
    )
    user_id: str = Field(..., min_length=1, description="接收用户 ID")
    message: str = Field(..., min_length=1, description="消息内容")


class IMSendResponse(BaseModel):
    platform: str
    user_id: Optional[str] = None
    message: Optional[str] = None
    status: str
    msg_id: Optional[str] = None
    detail: Optional[str] = None


class IMWebhookResponse(BaseModel):
    platform: str
    event: Optional[str] = None
    handled: bool = True
    status: str
    detail: Optional[str] = None
