"""IM 集成 API（P2 占位实现）。

所有端点均为最小可运行占位，便于与 IM 平台 webhook 调试。
后续会替换为真实的企业微信/飞书/钉钉 OpenAPI 调用与回调验签。
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.api.v1.auth import get_current_user
from app.schemas.im_integration import IMSendRequest, IMSendResponse, IMWebhookResponse
from app.schemas.user import UserResponse
from app.services.im_integration_service import im_integration_service

router = APIRouter(prefix="/im", tags=["im-integration"])


@router.post("/webhook/{platform}", response_model=IMWebhookResponse)
async def im_webhook(platform: str, payload: Dict[str, Any]):
    """接收 IM 平台推送的 webhook 事件（占位）。

    注意：真实环境中应先校验签名/解密，再解析事件。
    本占位端点允许匿名访问以方便调试。
    """
    result = await im_integration_service.handle_webhook(platform, payload)
    return IMWebhookResponse(**result)


@router.post("/send", response_model=IMSendResponse)
async def im_send(
    request: IMSendRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """通过指定 IM 平台给用户发送消息（占位）。"""
    result = await im_integration_service.send_message(
        request.platform, request.user_id, request.message
    )
    return IMSendResponse(**result)
