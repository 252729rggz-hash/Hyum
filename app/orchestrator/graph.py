"""LangGraph 워크플로 조립.

    START → MD → 디자인 → 콘텐츠 → 검수(QA) ─┬─ 통과 → 승인(interrupt) → 개발 → 마케팅 → END
                    ↑              │          ├─ 반려 → 담당 팀으로 재작업 (최대 N회)
                    └──────────────┘          └─ 재작업 초과 → 차단(대표님 보고) → END

승인 단계는 LangGraph `interrupt()`로 워크플로를 멈춥니다. 상태는 체크포인터에
저장되므로 프로세스가 재시작돼도 `Command(resume={"approved": ...})`로 이어갈 수 있습니다.
승인 알림 발송은 그래프 밖(API 계층)에서 interrupt payload를 보고 수행합니다 —
노드는 재개 시 처음부터 다시 실행되므로 노드 안에서 알림을 보내면 중복 발송됩니다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import Enum
from functools import lru_cache
from typing import Any, Literal

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel

from app.integrations.notifications import notify_event
from app.orchestrator.state import MallWorkflowState
from app.shared import models as shared_models
from app.shared.config import get_settings
from app.shared.models import (
    ApprovalKind,
    ApprovalRequest,
    DesignPlan,
    DevDeployment,
    MDPlan,
    ProductItem,
    QAReport,
    TeamName,
    WorkflowStatus,
)
from app.teams import run_content, run_design, run_dev, run_marketing, run_md, run_qa

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════
# 노드
# ═══════════════════════════════════════════════
def md_node(state: MallWorkflowState) -> dict:
    return run_md(state)


def design_node(state: MallWorkflowState) -> dict:
    return run_design(state)


def content_node(state: MallWorkflowState) -> dict:
    return run_content(state)


def qa_node(state: MallWorkflowState) -> dict:
    return run_qa(state)


async def dev_node(state: MallWorkflowState) -> dict:
    return await run_dev(state)


def marketing_node(state: MallWorkflowState) -> dict:
    return run_marketing(state)


def _build_approval_request(state: MallWorkflowState) -> ApprovalRequest:
    product = ProductItem.model_validate(state["product"])
    md: MDPlan | None = state.get("md_plan")
    design: DesignPlan | None = state.get("design_assets")
    qa: QAReport | None = state.get("qa_report")
    settings = get_settings()

    price = md.pricing.selling_price if md else (product.selling_price or 0)
    margin = md.pricing.margin_rate if md else 0.0
    score = qa.score if qa else 0
    platform = settings.mall_platform

    risks = ["실서버에 상품이 공개되면 즉시 고객 주문이 들어올 수 있습니다."]
    if settings.mall_api_key is None and not settings.is_production:
        risks.append("MALL_API_KEY 미설정 — 이 환경에서는 시뮬레이션 등록으로 처리됩니다.")
    if qa and qa.failed:
        risks.extend(f"[{c.severity}] {c.message}" for c in qa.failed[:3])
    if md:
        risks.extend(md.risk_notes[:2])

    return ApprovalRequest(
        workflow_id=state.get("workflow_id", ""),
        kind=ApprovalKind.DEPLOY,
        title=f"'{product.name}' 상품 등록 승인 요청",
        summary=(
            f"SKU {product.sku} / 판매가 {price:,}원 / 순이익률 {margin:.1%} / 검수 {score}점. "
            f"{platform} 몰에 상품을 등록하고 재고를 동기화합니다."
        ),
        requested_by=TeamName.ORCHESTRATOR,
        payload={
            "sku": product.sku,
            "name": product.name,
            "selling_price": price,
            "cost_price": product.cost_price,
            "margin_rate": margin,
            "stock": product.stock,
            "platform": platform,
            "qa_score": score,
            "qa_feedback": list(state.get("qa_feedback") or []),
            "assets": [a.kind for a in design.assets] if design else [],
            "seo_title": state["content_copy"].seo_title if state.get("content_copy") else None,
        },
        risks=risks,
    )


def approval_node(state: MallWorkflowState) -> dict:
    """대표님 승인 대기 지점. 재개 시 interrupt()가 사람의 결정을 돌려준다."""
    request = _build_approval_request(state)
    decision = interrupt(request.model_dump(mode="json"))

    if isinstance(decision, dict):
        approved = bool(decision.get("approved"))
        note = str(decision.get("note") or "")
        decided_by = str(decision.get("decided_by") or "대표")
    else:
        approved, note, decided_by = bool(decision), "", "대표"

    decided = request.model_copy(
        update={
            "status": "approved" if approved else "rejected",
            "decided_at": datetime.now(UTC),
            "decided_by": decided_by,
            "note": note,
        }
    )
    verb = "승인" if approved else "반려"
    return {
        "human_approved": approved,
        "approval_request": decided,
        "approval_note": note,
        "status": WorkflowStatus.APPROVED if approved else WorkflowStatus.REJECTED,
        "log": [f"[approval] 대표님 {verb} — {request.title}" + (f" / 메모: {note}" if note else "")],
    }


def qa_blocked_node(state: MallWorkflowState) -> dict:
    feedback = list(state.get("qa_feedback") or [])
    notify_event(
        "qa_blocked",
        f"SKU {state.get('product') and ProductItem.model_validate(state['product']).sku} 검수 반려 한도 초과",
        feedback=feedback,
    )
    return {
        "status": WorkflowStatus.QA_BLOCKED,
        "log": [
            f"[orchestrator] 재작업 한도({get_settings().qa_max_revisions}회) 초과 — 대표님 확인 필요: "
            + " | ".join(feedback[:3])
        ],
    }


# ═══════════════════════════════════════════════
# 라우팅
# ═══════════════════════════════════════════════
RouteAfterQA = Literal["approval", "md", "design", "content", "blocked"]


def route_after_qa(state: MallWorkflowState) -> RouteAfterQA:
    if state.get("qa_passed"):
        return "approval"

    revision = int(state.get("qa_revision", 0))
    if revision > get_settings().qa_max_revisions:
        return "blocked"

    targets = {
        chunk.split("]", 1)[0].lstrip("[")
        for chunk in (state.get("qa_feedback") or [])
        if chunk.startswith("[")
    }
    # 가격/재고 문제는 MD부터, 디자인 문제는 디자인부터 다시 돈다.
    if "md" in targets:
        return "md"
    if "design" in targets:
        return "design"
    if "content" in targets:
        return "content"
    return "design"


def route_after_approval(state: MallWorkflowState) -> Literal["dev", "end"]:
    return "dev" if state.get("human_approved") else "end"


def route_after_dev(state: MallWorkflowState) -> Literal["marketing", "end"]:
    raw = state.get("dev_deployed")
    if not raw:
        return "end"
    dep = DevDeployment.model_validate(raw)
    if dep.deployed or dep.simulated:
        return "marketing"
    return "end"


# ═══════════════════════════════════════════════
# 그래프 조립
# ═══════════════════════════════════════════════
def build_graph(checkpointer: Any | None = None):
    """워크플로 그래프를 컴파일한다. interrupt를 쓰려면 checkpointer가 필요하다."""
    graph = StateGraph(MallWorkflowState)

    graph.add_node("md", md_node)
    graph.add_node("design", design_node)
    graph.add_node("content", content_node)
    graph.add_node("qa", qa_node)
    graph.add_node("approval", approval_node)
    graph.add_node("qa_blocked", qa_blocked_node)
    graph.add_node("dev", dev_node)
    graph.add_node("marketing", marketing_node)

    graph.add_edge(START, "md")
    graph.add_edge("md", "design")
    graph.add_edge("design", "content")
    graph.add_edge("content", "qa")
    graph.add_conditional_edges(
        "qa",
        route_after_qa,
        {
            "approval": "approval",
            "md": "md",
            "design": "design",
            "content": "content",
            "blocked": "qa_blocked",
        },
    )
    graph.add_conditional_edges("approval", route_after_approval, {"dev": "dev", "end": END})
    graph.add_conditional_edges("dev", route_after_dev, {"marketing": "marketing", "end": END})
    graph.add_edge("qa_blocked", END)
    graph.add_edge("marketing", END)

    return graph.compile(checkpointer=checkpointer)


@lru_cache
def get_graph():
    """프로세스 공용 그래프 (인메모리 체크포인터).

    운영에서는 `SqliteSaver`/`PostgresSaver`로 바꿔 넣으면 승인 대기 상태가
    서버 재시작 후에도 유지됩니다.
    """
    # 상태에 담기는 우리 모델/enum 을 체크포인터 직렬화 허용 목록에 등록한다.
    allowed = [
        obj
        for obj in vars(shared_models).values()
        if isinstance(obj, type) and issubclass(obj, (BaseModel, Enum))
    ]
    serde = JsonPlusSerializer(allowed_msgpack_modules=allowed)
    return build_graph(checkpointer=InMemorySaver(serde=serde))
