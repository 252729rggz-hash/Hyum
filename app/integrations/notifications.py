"""승인 요청/운영 알림 스텁.

대표님 승인이 필요한 순간(배포, 발주, 광고비, 고객 발송)에 호출됩니다.
`APPROVAL_WEBHOOK_URL`이 있으면 슬랙/카카오/자체 알림 서버로 POST하고,
없으면 로그에만 남깁니다. 실제 발송 채널을 붙일 때 이 파일만 고치면 됩니다.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.shared.config import get_settings
from app.shared.models import ApprovalRequest

logger = logging.getLogger("mall.notifications")


def _format_approval(request: ApprovalRequest) -> str:
    lines = [
        f"🔔 [{request.kind}] 승인 요청 — {request.title}",
        request.summary,
    ]
    if request.payload:
        price = request.payload.get("selling_price")
        if price:
            lines.append(f"· 판매가: {price:,}원")
        margin = request.payload.get("margin_rate")
        if margin is not None:
            lines.append(f"· 순이익률: {margin:.1%}")
    if request.risks:
        lines.append("· 확인 필요: " + " / ".join(request.risks[:3]))
    return "\n".join(lines)


def notify_approval(request: ApprovalRequest) -> dict[str, Any]:
    """승인 요청을 사람에게 전달한다. 반환값은 전달 결과(로그/웹훅)."""
    text = _format_approval(request)
    logger.info("approval requested: %s\n%s", request.id, text)

    url = get_settings().approval_webhook_url
    if not url:
        return {"delivered": False, "channel": "log", "approval_id": request.id, "text": text}

    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.post(url, json={"text": text, "approval": request.model_dump(mode="json")})
            res.raise_for_status()
        return {"delivered": True, "channel": "webhook", "approval_id": request.id, "status": res.status_code}
    except httpx.HTTPError as exc:
        logger.warning("approval webhook failed: %s", exc)
        return {"delivered": False, "channel": "webhook", "approval_id": request.id, "error": str(exc)}


def notify_event(event: str, message: str, **fields: Any) -> None:
    """운영 로그/알림용 단순 이벤트. 필요 시 웹훅으로 확장."""
    logger.info("[%s] %s %s", event, message, fields or "")
