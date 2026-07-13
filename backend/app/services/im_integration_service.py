"""IM（即时通讯）集成服务（P2 占位实现）。

当前实现提供统一的适配器基类与企业微信/飞书/钉钉占位适配器，
所有方法返回模拟响应，便于后续接入真实 IM OpenAPI。
后续替换点：
- 实现各平台真实 access_token 获取、消息发送、回调验签逻辑。
- 增加消息模板、卡片消息、群聊 @ 等能力。
- 引入异步任务队列（Celery）处理消息发送，避免阻塞接口。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseIMAdapter(ABC):
    """IM 适配器基类。"""

    @property
    @abstractmethod
    def platform(self) -> str:
        """返回平台标识，如 wecom、feishu、dingtalk。"""

    @abstractmethod
    async def send_message(self, user_id: str, message: str) -> Dict[str, Any]:
        """向指定用户发送消息。后续替换为真实 API 调用。"""

    @abstractmethod
    async def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理平台推送的 webhook 事件。后续替换为真实回调解析与响应。"""


class WecomAdapter(BaseIMAdapter):
    """企业微信适配器（占位）。"""

    @property
    def platform(self) -> str:
        return "wecom"

    async def send_message(self, user_id: str, message: str) -> Dict[str, Any]:
        """企业微信发送消息（占位实现）。"""
        return {
            "platform": self.platform,
            "user_id": user_id,
            "message": message,
            "status": "placeholder_sent",
            "msg_id": "wecom-msg-placeholder",
        }

    async def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """企业微信 webhook 处理（占位实现）。"""
        return {
            "platform": self.platform,
            "event": payload.get("Event", "unknown"),
            "handled": True,
            "status": "placeholder_handled",
        }


class FeishuAdapter(BaseIMAdapter):
    """飞书适配器（占位）。"""

    @property
    def platform(self) -> str:
        return "feishu"

    async def send_message(self, user_id: str, message: str) -> Dict[str, Any]:
        """飞书发送消息（占位实现）。"""
        return {
            "platform": self.platform,
            "user_id": user_id,
            "message": message,
            "status": "placeholder_sent",
            "msg_id": "feishu-msg-placeholder",
        }

    async def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """飞书 webhook 处理（占位实现）。"""
        return {
            "platform": self.platform,
            "event": payload.get("header", {}).get("event_type", "unknown"),
            "handled": True,
            "status": "placeholder_handled",
        }


class DingtalkAdapter(BaseIMAdapter):
    """钉钉适配器（占位）。"""

    @property
    def platform(self) -> str:
        return "dingtalk"

    async def send_message(self, user_id: str, message: str) -> Dict[str, Any]:
        """钉钉发送消息（占位实现）。"""
        return {
            "platform": self.platform,
            "user_id": user_id,
            "message": message,
            "status": "placeholder_sent",
            "msg_id": "dingtalk-msg-placeholder",
        }

    async def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """钉钉 webhook 处理（占位实现）。"""
        return {
            "platform": self.platform,
            "event": payload.get("msgtype", "unknown"),
            "handled": True,
            "status": "placeholder_handled",
        }


class IMIntegrationService:
    """IM 集成统一入口（占位）。"""

    _adapters: Dict[str, BaseIMAdapter] = {
        "wecom": WecomAdapter(),
        "feishu": FeishuAdapter(),
        "dingtalk": DingtalkAdapter(),
    }

    async def send_message(self, platform: str, user_id: str, message: str) -> Dict[str, Any]:
        """调用指定平台适配器发送消息（占位实现）。

        后续替换点：
        - 校验平台配置是否启用。
        - 记录消息发送审计日志。
        - 失败时进入重试队列。

        Args:
            platform: 平台标识（wecom/feishu/dingtalk）。
            user_id: 接收用户 ID。
            message: 消息内容。

        Returns:
            适配器返回的发送结果。
        """
        adapter = self._adapters.get(platform)
        if not adapter:
            return {
                "platform": platform,
                "status": "error",
                "detail": f"Unsupported platform: {platform}",
            }
        return await adapter.send_message(user_id, message)

    async def handle_webhook(self, platform: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """分发平台 webhook 到对应适配器（占位实现）。

        后续替换点：
        - 对 payload 做签名/解密校验。
        - 识别用户意图并调用 RAG 服务生成回复。
        - 异步回复 IM 消息。

        Args:
            platform: 平台标识。
            payload: 平台推送的原始数据。

        Returns:
            适配器返回的处理结果。
        """
        adapter = self._adapters.get(platform)
        if not adapter:
            return {
                "platform": platform,
                "status": "error",
                "detail": f"Unsupported platform: {platform}",
            }
        return await adapter.handle_webhook(payload)


im_integration_service = IMIntegrationService()
