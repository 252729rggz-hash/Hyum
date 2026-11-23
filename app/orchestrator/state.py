"""LangGraph 워크플로 상태 정의.

상태는 팀 간 계약(contract)입니다. 각 팀 노드는 자기가 책임지는 키만 갱신하고,
나머지 키는 건드리지 않습니다. `log`만 reducer(operator.add)로 누적됩니다.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from app.shared.models import (
    ApprovalRequest,
    ContentCopy,
    CSPlaybook,
    DesignPlan,
    DevDeployment,
    MarketingPlan,
    MDPlan,
    ProductItem,
    QAReport,
    WorkflowStatus,
)


class MallWorkflowState(TypedDict, total=False):
    """상품 1건이 기획 → 제작 → 검수 → 승인 → 배포 → 마케팅으로 흐르는 상태."""

    # 실행 식별
    workflow_id: str
    status: WorkflowStatus
    note: str

    # 입력
    product: ProductItem

    # 팀 산출물
    md_plan: MDPlan
    design_assets: DesignPlan
    content_copy: ContentCopy

    # 검수
    qa_passed: bool
    qa_feedback: list[str]
    qa_report: QAReport
    qa_revision: int

    # 사람 승인 (human-in-the-loop)
    human_approved: bool
    approval_request: ApprovalRequest
    approval_note: str

    # 배포 / 마케팅
    dev_deployed: DevDeployment
    marketing_plan: MarketingPlan

    # CS·운영 (배포 후 상시 실행)
    cs_playbook: CSPlaybook

    # 진행 로그 (누적)
    log: Annotated[list[str], operator.add]


#: 워크플로를 시작할 때 넣는 기본값.
def initial_state(product: ProductItem, workflow_id: str, note: str = "") -> MallWorkflowState:
    return {
        "workflow_id": workflow_id,
        "status": WorkflowStatus.PENDING,
        "note": note,
        "product": product,
        "qa_passed": False,
        "qa_feedback": [],
        "qa_revision": 0,
        "human_approved": False,
        "log": [f"[orchestrator] 워크플로 시작: {workflow_id} / SKU {product.sku}"],
    }
