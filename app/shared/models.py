"""팀 간에 주고받는 공통 스키마.

각 팀은 이 모델들을 입출력으로 사용하고, 오케스트레이터는 모델 단위로
워크플로 상태를 갱신합니다. 필드 이름은 DB/API로 그대로 내보내도 되도록
영문 snake_case를 사용하고, 설명은 한국어로 답니다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


# ═══════════════════════════════════════════════
# 열거형
# ═══════════════════════════════════════════════
class TeamName(StrEnum):
    ORCHESTRATOR = "orchestrator"
    MD = "md"
    DESIGN = "design"
    CONTENT = "content"
    DEV = "dev"
    MARKETING = "marketing"
    CS = "cs"
    QA = "qa"


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    QA_BLOCKED = "qa_blocked"
    DEPLOY_FAILED = "deploy_failed"
    COMPLETED = "completed"


class ApprovalKind(StrEnum):
    """대표님 승인이 반드시 필요한 실행 종류."""

    DEPLOY = "deploy"                 # 실서버 상품 등록/배포
    PURCHASE_ORDER = "purchase_order"  # 발주·결제
    AD_SPEND = "ad_spend"             # 광고비 집행
    CUSTOMER_SEND = "customer_send"   # 고객 발송/대량 안내


class Severity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class CheckCategory(StrEnum):
    PRICE = "price"
    CLAIM = "claim"
    TYPO = "typo"
    ASSET = "asset"
    SEO = "seo"
    SPEC = "spec"


# ═══════════════════════════════════════════════
# 상품 / MD
# ═══════════════════════════════════════════════
class ProductItem(BaseModel):
    """등록 후보 상품 한 건. 보세 도매처에서 사입하는 단위."""

    model_config = ConfigDict(extra="forbid")

    sku: str = Field(..., description="자체 관리 SKU (예: MN-OUT-2411-001)")
    name: str = Field(..., description="상품명(작업용). 판매용 명칭은 콘텐츠팀이 다듬습니다.")
    category: str = Field(..., description="예: 남성 아우터 > 바람막이")
    fit: str = Field(default="regular", description="regular | slim | oversized | loose")
    material: str = Field(default="", description="소재 (예: 폴리에스터 100%)")
    color_options: list[str] = Field(default_factory=list)
    size_options: list[str] = Field(default_factory=lambda: ["M", "L", "XL", "2XL"])
    cost_price: int = Field(..., ge=0, description="도매/공급가(원). VAT 별도 기준")
    selling_price: int | None = Field(default=None, ge=0, description="미지정 시 MD팀이 역산")
    stock: int = Field(default=0, ge=0)
    supplier: str = Field(default="", description="도매처/사입처 이름")
    source_url: str | None = Field(default=None, description="도매처 상품 링크")
    image_urls: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    description: str = Field(default="", description="도매처 원문 설명")
    target_margin_rate: float | None = Field(default=None, ge=0, lt=1)
    country_of_origin: str = Field(
        default="", description="제조국 (예: 중국, 베트남, 대한민국). 고시정보에 그대로 표기"
    )

    @property
    def display_name(self) -> str:
        return self.name.strip() or self.sku


class SourcingCandidate(BaseModel):
    supplier: str
    item_name: str
    cost_price: int = Field(ge=0)
    moq: int = Field(default=1, ge=1, description="최소 주문 수량")
    lead_time_days: int = Field(default=3, ge=0)
    url: str | None = None
    note: str = ""


class PricingPlan(BaseModel):
    """마진 계산 결과. 금액 단위는 원."""

    cost_price: int
    selling_price: int
    vat_amount: int = Field(description="판매가에 포함된 부가세")
    platform_fee: int = Field(description="몰 수수료")
    shipping_fee: int
    net_profit: int = Field(description="수수료·부가세·배송 원가·충당금 반영 순이익")
    margin_rate: float = Field(description="판매가 대비 순이익률")
    break_even_units: int = Field(default=1, description="고정비 회수 손익분기 수량")
    payment_fee: int = Field(default=0, description="PG 결제 수수료")
    return_reserve: int = Field(default=0, description="반품·불량 충당금")
    note: str = ""


class MDPlan(BaseModel):
    """MD(상품기획)팀 산출물."""

    trend_summary: str
    trend_keywords: list[str] = Field(default_factory=list)
    target_customer: str = ""
    season: str = ""
    sourcing_list: list[SourcingCandidate] = Field(default_factory=list)
    pricing: PricingPlan
    inventory_notes: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════
# 디자인
# ═══════════════════════════════════════════════
AssetKind = Literal["detail_page", "thumbnail", "banner", "lookbook"]


class LayoutSection(BaseModel):
    order: int
    section: str
    headline: str
    visual: str
    copy_points: list[str] = Field(default_factory=list)


class DesignAsset(BaseModel):
    kind: AssetKind
    name: str
    width: int
    height: int
    format: Literal["jpg", "png", "webp", "psd", "mp4"] = "jpg"
    spec: dict[str, Any] = Field(default_factory=dict)
    status: Literal["spec_ready", "generated"] = "spec_ready"
    file_url: str | None = None


class DesignPlan(BaseModel):
    """디자인팀 산출물: 상세페이지 레이아웃 + 이미지 규격."""

    concept: str
    mood_keywords: list[str] = Field(default_factory=list)
    palette: list[str] = Field(default_factory=list, description="HEX 색상 코드")
    layout_sections: list[LayoutSection] = Field(default_factory=list)
    assets: list[DesignAsset] = Field(default_factory=list)
    image_prompt: str = Field(default="", description="AI 이미지 생성용 영문 프롬프트")
    notes: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════
# 콘텐츠
# ═══════════════════════════════════════════════
class ProductDisclosure(BaseModel):
    """전자상거래법 시행령상 의류 상품정보 고시 항목.

    상세페이지 하단에 고정 노출해야 하며, 비어 있는 항목은 검수팀이 반려합니다.
    """

    material_composition: str = Field(default="", description="혼용률 (예: 폴리에스터 100%)")
    country_of_origin: str = Field(default="", description="제조국")
    care_instruction: str = Field(default="", description="세탁 방법")
    manufacturer: str = Field(default="", description="제조자/수입자")
    quality_guarantee: str = Field(default="", description="품질보증 기준 (예: 소비자분쟁해결기준)")
    as_contact: str = Field(default="", description="AS 책임자 및 연락처")

    #: 누락 시 고시 위반이 되는 필수 항목.
    REQUIRED_FIELDS: ClassVar[tuple[str, ...]] = (
        "material_composition",
        "country_of_origin",
        "care_instruction",
    )

    def missing_required(self) -> list[str]:
        return [name for name in self.REQUIRED_FIELDS if not str(getattr(self, name, "") or "").strip()]


class ContentCopy(BaseModel):
    """콘텐츠팀 산출물: SEO 제목, 핏/소재/코디 카피, SNS 원고."""

    seo_title: str = Field(description="검색 노출용 제목 (공백 포함 50자 이내 권장)")
    meta_description: str = Field(description="메타 설명 (80자 이내 권장)")
    hook: str = Field(default="", description="상단 후킹 문장")
    fit_copy: str = ""
    material_copy: str = ""
    coordi_copy: str = ""
    size_guide_copy: str = ""
    care_copy: str = ""
    sns_script: str = Field(default="", description="릴스/숏폼 15~30초 원고")
    hashtags: list[str] = Field(default_factory=list)
    disclosure: ProductDisclosure | None = Field(
        default=None, description="상품정보 고시(혼용률·제조국·세탁법 등). 미작성 시 QA 반려"
    )


# ═══════════════════════════════════════════════
# QA
# ═══════════════════════════════════════════════
class QACheck(BaseModel):
    code: str = Field(description="검사 코드 (예: PRICE_MARGIN)")
    category: CheckCategory
    passed: bool
    severity: Severity = Severity.MAJOR
    message: str
    target_team: TeamName = TeamName.QA
    evidence: str = ""


class QAReport(BaseModel):
    passed: bool
    score: int = Field(ge=0, le=100)
    checks: list[QACheck] = Field(default_factory=list)
    feedback: list[str] = Field(default_factory=list, description="팀별 재작업 지시문")
    checked_at: datetime = Field(default_factory=_now)

    @property
    def failed(self) -> list[QACheck]:
        return [c for c in self.checks if not c.passed]


# ═══════════════════════════════════════════════
# 승인 / 개발 / 마케팅 / CS
# ═══════════════════════════════════════════════
class ApprovalRequest(BaseModel):
    """대표님 승인 요청. 워크플로가 interrupt되어 이 내용이 사람에게 전달됩니다."""

    id: str = Field(default_factory=lambda: _new_id("apr"))
    workflow_id: str
    kind: ApprovalKind = ApprovalKind.DEPLOY
    title: str
    summary: str
    requested_by: TeamName = TeamName.ORCHESTRATOR
    payload: dict[str, Any] = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: datetime = Field(default_factory=_now)
    decided_at: datetime | None = None
    decided_by: str | None = None
    note: str = ""


class DevDeployment(BaseModel):
    deployed: bool
    simulated: bool = Field(default=False, description="로컬 시뮬레이션 여부 (실서버 미반영)")
    platform: str
    mall_product_id: str | None = None
    product_url: str | None = None
    inventory_synced: bool = False
    errors: list[str] = Field(default_factory=list)
    deployed_at: datetime | None = None


class CampaignChannel(BaseModel):
    channel: Literal["meta", "naver", "google", "kakao", "instagram_organic"]
    objective: str
    budget: int = Field(ge=0, description="일 예산(원)")
    target_audience: str
    creative_notes: str
    expected_roas: float = Field(default=2.0, ge=0)


class MarketingPlan(BaseModel):
    budget_total: int = Field(ge=0)
    channels: list[CampaignChannel] = Field(default_factory=list)
    schedule: list[str] = Field(default_factory=list)
    kpi: dict[str, float] = Field(default_factory=dict, description="목표 CTR/CVR/ROAS 등")
    tracking_notes: list[str] = Field(default_factory=list)


class InquiryTemplate(BaseModel):
    intent: Literal["size", "shipping", "exchange", "return", "stock", "etc"]
    question: str
    draft: str
    escalation: str = ""


class CSPlaybook(BaseModel):
    templates: list[InquiryTemplate] = Field(default_factory=list)
    exchange_policy: list[str] = Field(default_factory=list)
    escalation_rules: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════
# 팀 실행 결과 / API 입출력
# ═══════════════════════════════════════════════
class TeamResult(BaseModel):
    """팀 하나의 실행 결과 봉투."""

    team: TeamName
    ok: bool
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None


class WorkflowLaunchRequest(BaseModel):
    product: ProductItem
    workflow_id: str | None = Field(default=None, description="미지정 시 자동 생성")
    note: str = ""


class ApprovalDecision(BaseModel):
    approved: bool
    decided_by: str = "대표"
    note: str = ""


class WorkflowLaunchResponse(BaseModel):
    workflow_id: str
    status: WorkflowStatus
    awaiting_approval: bool = False
    approval: ApprovalRequest | None = None
    qa_report: QAReport | None = None
    result: dict[str, Any] = Field(default_factory=dict)
