"""검수(QA)팀 도구 — 금지 표현 스캔, 마진 역전 점검, 고시정보 누락, 에셋 규격.

검수는 '느낌'이 아니라 규칙으로 합니다. 도구가 위반 항목과 근거(문구·수치)를 돌려주고,
`agent.py`가 이를 `QACheck`로 감싸 담당 팀에 되돌립니다. 규정 근거를 함께 남겨
나중에 왜 반려했는지 설명할 수 있게 합니다.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.shared.models import TeamName
from app.shared.tooling import tool

#: (코드, 정규식, 사유, 근거 규정)
CLAIM_RULES: list[tuple[str, str, str, str]] = [
    (
        "SUPERLATIVE",
        r"최고급|최고의|최상급|최저가|업계 ?1위|판매 ?1위|국내 ?1위",
        "입증 자료 없는 최상급·1위 표현",
        "표시광고법 제3조(거짓·과장 광고)",
    ),
    ("GUARANTEE", r"완벽|무조건|반드시 보장|100\s*%\s*보장", "단정·보장 표현은 소비자 오인 우려", "표시광고법 제3조"),
    (
        "MEDICAL",
        r"부작용|치료|효능|다이어트|감량|특효|피부질환",
        "의약·효능 표현은 의류 상품에 사용 불가",
        "의료법 제27조(무면허 의료행위 금지)",
    ),
    ("PERMANENT", r"영구|평생|절대 ?줄지|절대 ?변하지", "기간·결과를 단정하는 표현", "표시광고법 제3조"),
    ("SELLOUT", r"완판|품절 ?대란|오픈런|줄 ?서서", "판매량·희소성 과장 표현", "표시광고법 제3조"),
]
FUNCTIONAL_CLAIMS = r"방수|방풍|발열|보온 ?효과|흡한속건|항균|탈취|자외선 ?차단|UV ?차단|냄새 ?제거"

#: 소재 함량 표기는 100% 표현이 허용된다 (예: 면 100%).
ALLOWED_PERCENT = re.compile(
    r"(면|폴리에스터|폴리|코튼|울|모|나일론|레이온|아크릴|린넨|텐셀|스판|엘라스테인)\s*\d{1,3}\s*%"
)
CONTACT_PATTERN = re.compile(r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}")
URL_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)


# ═══════════════════════════════════════════════
# 1) 금지·과장 표현
# ═══════════════════════════════════════════════
class ClaimScanArgs(BaseModel):
    text: str = Field(description="검사할 카피 전체(제목·메타·본문·SNS)")
    evidence: list[str] = Field(
        default_factory=list, description="기능성 주장의 근거 자료(시험성적서 등). 없으면 미입증"
    )


class ClaimHit(BaseModel):
    code: str
    phrase: str
    reason: str
    law: str
    severity: str = "critical"


class ClaimScan(BaseModel):
    passed: bool
    hits: list[ClaimHit] = Field(default_factory=list)
    note: str = ""


@tool(
    name="qa_scan_claims",
    team=TeamName.QA,
    description=(
        "표시광고법·의료법 기준으로 금지·과장 표현을 찾는다: 최고급/1위, 완벽·보장, 효능·치료, 영구·평생, "
        "완판·품절대란, 근거 없는 기능성(방수·항균 등), 소재 외 '100%', 연락처·외부 링크 노출."
    ),
    args=ClaimScanArgs,
    returns="ClaimScan(통과 여부·위반 문구 목록·근거 규정)",
    tags=("compliance", "claim"),
)
def scan_claims(req: ClaimScanArgs) -> ClaimScan:
    text = ALLOWED_PERCENT.sub(" ", req.text or "")
    hits: list[ClaimHit] = []

    for code, pattern, reason, law in CLAIM_RULES:
        for match in re.finditer(pattern, text):
            hits.append(ClaimHit(code=code, phrase=match.group(0), reason=reason, law=law))

    if re.search(r"100\s*%", text):
        hits.append(
            ClaimHit(
                code="PERCENT_CLAIM",
                phrase="100%",
                reason="소재 함량 외 '100%' 표현은 입증 없이 사용할 수 없음",
                law="표시광고법 제3조",
            )
        )

    functional = re.search(FUNCTIONAL_CLAIMS, text)
    if functional and not req.evidence:
        hits.append(
            ClaimHit(
                code="FUNCTIONAL_NO_EVIDENCE",
                phrase=functional.group(0),
                reason="기능성 표현은 시험성적서 등 근거 자료가 있을 때만 사용 가능",
                law="표시광고법 제3조·제4조(중요사항 고지)",
                severity="major",
            )
        )

    contact = CONTACT_PATTERN.search(text)
    if contact:
        hits.append(
            ClaimHit(
                code="CONTACT_EXPOSED",
                phrase=contact.group(0),
                reason="상세페이지 내 개인 연락처 노출 금지",
                law="플랫폼 정책",
            )
        )
    url = URL_PATTERN.search(text)
    if url:
        hits.append(
            ClaimHit(
                code="EXTERNAL_LINK",
                phrase=url.group(0),
                reason="외부 링크 유도는 플랫폼 정책 위반",
                law="플랫폼 정책",
            )
        )

    note = "금지 표현 없음" if not hits else f"{len(hits)}건 발견 — 담당 팀 수정 필요"
    return ClaimScan(passed=not hits, hits=hits, note=note)


# ═══════════════════════════════════════════════
# 2) 마진·가격 점검
# ═══════════════════════════════════════════════
class MarginGuardArgs(BaseModel):
    cost_price: int = Field(ge=0)
    selling_price: int = Field(ge=0)
    net_profit: int
    margin_rate: float
    vat_amount: int = 0
    minimum_margin_rate: float = 0.25
    vat_rate: float = 0.1
    return_reserve: int = Field(default=0, description="반품·불량 충당금")
    payment_fee: int = Field(default=0, description="PG 결제 수수료")


class MarginIssue(BaseModel):
    code: str
    severity: str = Field(description="critical | major | minor")
    message: str
    evidence: str = ""


class MarginGuard(BaseModel):
    issues: list[MarginIssue] = Field(default_factory=list)
    blocked: bool = False
    vat_expected: int = 0
    total_cost: int = 0


@tool(
    name="qa_margin_guard",
    team=TeamName.QA,
    description=(
        "판매가·원가·마진·부가세 정합성을 점검한다. 역마진, 최소 마진 미달, "
        "부가세 불일치, 반품충당금·PG 수수료 미반영을 잡는다."
    ),
    args=MarginGuardArgs,
    returns="MarginGuard(문제 목록·차단 여부·기대 부가세·총원가)",
    tags=("price", "margin"),
)
def margin_guard(req: MarginGuardArgs) -> MarginGuard:
    issues: list[MarginIssue] = []
    vat_expected = round(req.selling_price * req.vat_rate / (1 + req.vat_rate))
    total_cost = req.cost_price + max(req.return_reserve, 0) + max(req.payment_fee, 0)

    if req.selling_price <= 0:
        issues.append(
            MarginIssue(
                code="PRICE_POSITIVE",
                severity="critical",
                message="판매가가 0원 이하입니다",
                evidence=f"selling_price={req.selling_price}",
            )
        )
    if req.selling_price < req.cost_price:
        issues.append(
            MarginIssue(
                code="PRICE_NOT_BELOW_COST",
                severity="critical",
                message=f"판매가({req.selling_price:,}원)가 공급가({req.cost_price:,}원)보다 낮습니다 (역마진)",
                evidence=f"selling={req.selling_price} / cost={req.cost_price}",
            )
        )
    if req.net_profit <= 0:
        issues.append(
            MarginIssue(
                code="PRICE_LOSS",
                severity="critical",
                message=f"수수료·배송·충당금 반영 후 순이익이 {req.net_profit:,}원입니다",
                evidence=f"net_profit={req.net_profit} / total_cost={total_cost}",
            )
        )
    if req.margin_rate < req.minimum_margin_rate:
        issues.append(
            MarginIssue(
                code="PRICE_MARGIN",
                severity="major",
                message=(
                    f"순이익률 {req.margin_rate:.1%} — 최소 기준 "
                    f"{req.minimum_margin_rate:.0%} 미달, 가격 재산정 필요"
                ),
                evidence=f"margin_rate={req.margin_rate:.4f}",
            )
        )
    if abs(req.vat_amount - vat_expected) > 2:
        issues.append(
            MarginIssue(
                code="PRICE_VAT_CONSISTENT",
                severity="major",
                message=f"부가세 불일치 (계산 {req.vat_amount:,} / 기대 {vat_expected:,})",
                evidence=f"vat={req.vat_amount}",
            )
        )
    if req.return_reserve <= 0:
        issues.append(
            MarginIssue(
                code="PRICE_RETURN_RESERVE",
                severity="minor",
                message="반품·불량 충당금이 반영되지 않았습니다 (반품률 5~10% 가정 누락)",
                evidence="return_reserve=0",
            )
        )
    if req.payment_fee <= 0:
        issues.append(
            MarginIssue(
                code="PRICE_PAYMENT_FEE",
                severity="minor",
                message="PG 결제 수수료가 반영되지 않았습니다",
                evidence="payment_fee=0",
            )
        )

    blocked = any(i.severity in ("critical", "major") for i in issues)
    return MarginGuard(issues=issues, blocked=blocked, vat_expected=vat_expected, total_cost=total_cost)


# ═══════════════════════════════════════════════
# 3) 고시정보
# ═══════════════════════════════════════════════
class DisclosureGuardArgs(BaseModel):
    material_composition: str = ""
    country_of_origin: str = ""
    care_instruction: str = ""
    manufacturer: str = ""
    quality_guarantee: str = ""
    as_contact: str = ""
    source_material: str = Field(default="", description="도매처 원본 소재 표기")
    source_origin: str = Field(default="", description="도매처 원본 제조국")


class DisclosureGuard(BaseModel):
    missing: list[str] = Field(description="고시 필수 항목 누락(차단)")
    confirm_needed: list[str] = Field(description="원본 데이터가 없어 '확인 필요'로 남긴 항목(비차단 경고)")
    passed: bool


@tool(
    name="qa_disclosure_guard",
    team=TeamName.QA,
    description=(
        "전자상거래법 고시 필수 항목(혼용률·제조국·세탁법·제조자·품질보증·AS) 누락을 검사하고, "
        "원본 데이터가 없어 확인이 필요한 항목을 구분한다."
    ),
    args=DisclosureGuardArgs,
    returns="DisclosureGuard(누락·확인필요·통과 여부)",
    tags=("compliance", "disclosure"),
)
def disclosure_guard(req: DisclosureGuardArgs) -> DisclosureGuard:
    required = {
        "혼용률": req.material_composition,
        "제조국": req.country_of_origin,
        "세탁법": req.care_instruction,
        "제조자": req.manufacturer,
        "품질보증": req.quality_guarantee,
        "AS 연락처": req.as_contact,
    }
    missing = [name for name, value in required.items() if not (value or "").strip()]
    confirm_needed = [name for name, value in required.items() if "확인 필요" in (value or "")]
    if not req.source_material.strip() and "혼용률" not in confirm_needed:
        confirm_needed.append("혼용률(원본 미기재)")
    if not req.source_origin.strip() and "제조국" not in confirm_needed:
        confirm_needed.append("제조국(원본 미기재)")
    return DisclosureGuard(missing=missing, confirm_needed=confirm_needed, passed=not missing)


# ═══════════════════════════════════════════════
# 4) 에셋 규격
# ═══════════════════════════════════════════════
class AssetItem(BaseModel):
    kind: str
    width: int
    height: int
    status: str = "spec_ready"
    file_url: str | None = None


class AssetGuardArgs(BaseModel):
    assets: list[AssetItem] = Field(default_factory=list)
    section_count: int = 0
    has_image_prompt: bool = True


class AssetGuard(BaseModel):
    missing: list[str] = Field(default_factory=list)
    size_issues: list[str] = Field(default_factory=list)
    broken: list[str] = Field(default_factory=list)
    layout_issues: list[str] = Field(default_factory=list)
    passed: bool = False


REQUIRED_ASSETS: dict[str, tuple[int, int | None]] = {
    "detail_page": (860, None),
    "thumbnail": (1000, 1000),
    "banner": (1920, 600),
    "lookbook": (1200, 1600),
}


@tool(
    name="qa_asset_guard",
    team=TeamName.QA,
    description=(
        "필수 에셋 4종(상세페이지·썸네일·배너·룩북)의 존재, 픽셀 규격, 링크 깨짐, "
        "상세페이지 섹션 5개 이상 여부를 검사한다."
    ),
    args=AssetGuardArgs,
    returns="AssetGuard(누락·규격 오류·깨진 링크·레이아웃 문제·통과 여부)",
    tags=("asset", "spec"),
)
def asset_guard(req: AssetGuardArgs) -> AssetGuard:
    by_kind = {a.kind: a for a in req.assets}
    missing = [k for k in REQUIRED_ASSETS if k not in by_kind]
    size_issues: list[str] = []
    for kind, (width, height) in REQUIRED_ASSETS.items():
        asset = by_kind.get(kind)
        if not asset:
            continue
        if asset.width != width or (height and asset.height != height):
            size_issues.append(f"{kind}: {asset.width}×{asset.height} (기준 {width}×{height or '가변'})")
    broken = [a.kind for a in req.assets if a.status == "generated" and not a.file_url]
    layout: list[str] = []
    if req.section_count < 5:
        layout.append(f"상세페이지 섹션이 {req.section_count}개 — 최소 5개 필요")
    if not req.has_image_prompt:
        layout.append("룩북 이미지 프롬프트가 비어 있음")
    passed = not (missing or size_issues or broken or layout)
    return AssetGuard(missing=missing, size_issues=size_issues, broken=broken, layout_issues=layout, passed=passed)


#: 검수팀이 LLM에 바인딩하는 도구 목록.
TOOLS = [scan_claims, margin_guard, disclosure_guard, asset_guard]
