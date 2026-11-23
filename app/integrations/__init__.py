"""외부 시스템 연동 (쇼핑몰 API, 알림)."""

from app.integrations.mall_adapter import (
    Cafe24Adapter,
    CustomAdapter,
    ImwebAdapter,
    MallAdapter,
    MallCredentialsMissing,
    MallIntegrationError,
    MallProductRef,
    get_adapter,
)
from app.integrations.notifications import notify_approval, notify_event

__all__ = [
    "MallAdapter",
    "MallProductRef",
    "MallIntegrationError",
    "MallCredentialsMissing",
    "Cafe24Adapter",
    "ImwebAdapter",
    "CustomAdapter",
    "get_adapter",
    "notify_approval",
    "notify_event",
]
