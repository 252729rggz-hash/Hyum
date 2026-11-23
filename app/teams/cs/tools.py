"""CS·운영팀 도구 — 사이즈 안내, 교환·반품비 계산, 배송 지연/리오더 안내, 불량 접수, 에스컬레이션 판정.

보세몰 CS는 '재고가 없어서 못 보낸다', '사이즈가 안 맞는다'가 문의의 대부분입니다.
그래서 (1) 실측 기반 사이즈 안내, (2) 단순변심/하자에 따른 반품비 구분, (3) 지연·리오더를
미리 알리는 문구, (4) 자동 발송하면 안 되는 위험 건 판정을 도구로 고정합니다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.shared.models import TeamName
from app.shared.tooling import tool


# ═══════════════════════════════════════════════
# 1) 실측 사이즈표
# ═══════════════════════════════════════════════
class SizeChartArgs(BaseModel):
    sizes: list[str] = Field(default_factory=lambda: ["M", "L", "XL", "2XL"], min_length=1)
    fit: str = Field(default="regular", description="regular | slim | oversized | loose")


class SizeRow(BaseModel):
    size: str
    shoulder_cm: float
    chest_cm: float
    length_cm: float
    sleeve_cm: float


class SizeChart(BaseModel):
    rows: list[SizeRow]
    model_line: str
    table_text: str
    note: str


_SIZE_BASE = {
    "S": (43.0, 100.0, 64.0, 58.0),
    "M": (45.0, 106.0, 66.0, 60.0),
    "L": (47.0, 112.0, 68.0, 62.0),
    "XL": (49.0, 118.0, 70.0, 64.0),
    "2XL": (51.0, 124.0, 72.0, 66.0),
    "3XL": (53.0, 130.0, 74.0, 68.0),
}


@tool(
    name="cs_size_chart",
    team=TeamName.CS,
    description=(
        "사이즈 옵션별 실측표(어깨·가슴·총장·소매)를 만들고 모델 착용 기준 문장을 붙인다. "
        "오버핏은 여유분을 더한다."
    ),
    args=SizeChartArgs,
    returns="SizeChart(실측 행·모델 기준·표 텍스트·주의)",
    tags=("size", "cs"),
)
def size_chart(req: SizeChartArgs) -> SizeChart:
    extra = 4.0 if req.fit in ("oversized", "loose") else 0.0
    rows: list[SizeRow] = []
    for idx, size in enumerate(req.sizes):
        base = _SIZE_BASE.get(size.upper())
        if base is None:
            shoulder = 45.0 + idx * 2
            chest = 106.0 + idx * 6
            length = 66.0 + idx * 2
            sleeve = 60.0 + idx * 2
        else:
            shoulder, chest, length, sleeve = base
        rows.append(
            SizeRow(
                size=size,
                shoulder_cm=round(shoulder + extra, 1),
                chest_cm=round(chest + extra * 2, 1),
                length_cm=round(length + extra * 0.5, 1),
                sleeve_cm=round(sleeve, 1),
            )
        )
    table = "사이즈 | 어깨 | 가슴(단면) | 총장 | 소매\n" + "\n".join(
        f"{r.size} | {r.shoulder_cm}cm | {r.chest_cm / 2:.1f}cm | {r.length_cm}cm | {r.sleeve_cm}cm" for r in rows
    )
    return SizeChart(
        rows=rows,
        model_line="모델 178cm/68kg 기준 L 사이즈 착용",
        table_text=table,
        note="실측은 측정 방법에 따라 ±1~2cm 오차가 있습니다. 가슴은 단면 기준입니다.",
    )


# ═══════════════════════════════════════════════
# 2) 교환 안내
# ═══════════════════════════════════════════════
class ExchangeArgs(BaseModel):
    reason: Literal["size", "color", "defect", "wrong_item"] = Field(description="교환 사유")
    days_since_delivery: int = Field(default=2, ge=0, description="수령 후 경과일")
    tag_attached: bool = Field(default=True, description="택 부착·미착용 여부")
    price: int = Field(default=0, ge=0)
    colors: list[str] = Field(default_factory=list)
    sizes: list[str] = Field(default_factory=list)


class ExchangeGuide(BaseModel):
    eligible: bool
    fee: int
    payer: str
    steps: list[str]
    text: str
    needs_approval: bool = False


@tool(
    name="cs_exchange_guide",
    team=TeamName.CS,
    description="사이즈·컬러 교환 가능 여부와 배송비 부담 주체를 판정하고, 고객에게 보낼 교환 절차 안내를 만든다.",
    args=ExchangeArgs,
    returns="ExchangeGuide(가능 여부·배송비·부담 주체·절차·안내문)",
    tags=("exchange", "cs"),
)
def exchange_guide(req: ExchangeArgs) -> ExchangeGuide:
    within = req.days_since_delivery <= 7
    eligible = within and (req.tag_attached or req.reason in ("defect", "wrong_item"))
    seller_fault = req.reason in ("defect", "wrong_item")
    fee = 0 if seller_fault else 6000
    payer = "판매자" if seller_fault else "고객"

    if not eligible:
        reason = "수령 후 7일이 지났습니다" if not within else "택 제거·착용 흔적이 확인됩니다"
        return ExchangeGuide(
            eligible=False,
            fee=fee,
            payer=payer,
            steps=["주문번호·상품 사진 확인", "교환 불가 사유 안내", "필요 시 대표님 확인"],
            text=(
                f"문의 감사합니다. 확인 결과 {reason}로 교환 처리가 어렵습니다. "
                "다만 사이즈 안내나 수선 가능 여부는 도와드릴 수 있으니 편하게 말씀해 주세요."
            ),
            needs_approval=True,
        )

    color_text = ", ".join(req.colors) if req.colors else "보유 컬러"
    size_text = "/".join(req.sizes) if req.sizes else "보유 사이즈"
    steps = [
        "주문번호와 교환하실 컬러·사이즈 회신",
        "재고 확인 후 수거 접수(방문 수거 또는 편의점 택배)",
        "상품 상태 확인 후 새 상품 발송",
    ]
    if seller_fault:
        text = (
            "불편을 드려 죄송합니다. 하자/오배송으로 확인되어 왕복 배송비는 저희가 부담합니다. "
            f"가능한 옵션은 {color_text} / {size_text}이며, 주문번호와 함께 상품 전체·부분 사진을 보내 주시면 "
            "바로 수거 접수해 드리겠습니다."
        )
    else:
        text = (
            f"교환은 수령 후 7일 이내, 택 미부착·미착용 상태에서 가능합니다. "
            f"가능한 옵션은 {color_text} / {size_text}이고, "
            f"단순 변심 교환 배송비는 왕복 {fee:,}원입니다. "
            "주문번호와 원하시는 옵션을 회신해 주시면 접수해 드리겠습니다."
        )
    return ExchangeGuide(eligible=True, fee=fee, payer=payer, steps=steps, text=text, needs_approval=False)


# ═══════════════════════════════════════════════
# 3) 반품비 계산
# ═══════════════════════════════════════════════
class ReturnQuoteArgs(BaseModel):
    reason: Literal["change_of_mind", "size", "defect", "wrong_item", "late_delivery"] = "change_of_mind"
    price: int = Field(default=0, ge=0, description="결제 금액")
    shipping_round: int = Field(default=6000, ge=0, description="왕복 배송비")
    used_coupon: bool = Field(default=False)


class ReturnQuote(BaseModel):
    fee: int
    payer: str
    refund_amount: int
    text: str
    notes: list[str] = Field(default_factory=list)
    needs_approval: bool = False


@tool(
    name="cs_return_quote",
    team=TeamName.CS,
    description=(
        "반품 사유별로 반품 배송비 부담과 환불 예정 금액을 계산한다. "
        "단순변심은 고객 부담, 하자·오배송은 판매자 부담."
    ),
    args=ReturnQuoteArgs,
    returns="ReturnQuote(배송비·부담 주체·환불액·안내문·승인 필요 여부)",
    tags=("return", "refund"),
)
def return_quote(req: ReturnQuoteArgs) -> ReturnQuote:
    seller_fault = req.reason in ("defect", "wrong_item", "late_delivery")
    fee = 0 if seller_fault else req.shipping_round
    payer = "판매자" if seller_fault else "고객"
    refund = max(req.price - fee, 0)
    notes: list[str] = []
    if req.used_coupon:
        notes.append("쿠폰 사용 주문 — 쿠폰 재발급 여부는 대표 확인 필요")
    if refund >= 30_000 or seller_fault:
        notes.append("3만원 이상 환불 또는 판매자 귀책 — 대표 승인 후 처리")

    if seller_fault:
        text = (
            "불편을 드려 죄송합니다. 확인 결과 상품 하자/오배송으로 확인되어 반품 배송비는 저희가 부담합니다. "
            f"환불 예정 금액은 {refund:,}원이며, 상품 회수 확인 후 3~5영업일 내 결제 수단으로 환불됩니다."
        )
    else:
        text = (
            f"반품 접수 도와드리겠습니다. 단순 변심 반품은 왕복 배송비 {fee:,}원이 차감되어 "
            f"{refund:,}원이 환불됩니다. 수령 후 7일 이내, 택 미부착·미착용 상태에서 신청 가능합니다. "
            "카드 결제는 취소 후 3~5영업일, 무통장 입금은 계좌 확인 후 1~2영업일 내 환불됩니다."
        )
    return ReturnQuote(
        fee=fee,
        payer=payer,
        refund_amount=refund,
        text=text,
        notes=notes,
        needs_approval=refund >= 30_000 or seller_fault,
    )


# ═══════════════════════════════════════════════
# 4) 배송 지연 / 리오더 안내
# ═══════════════════════════════════════════════
class DelayArgs(BaseModel):
    delay_days: int = Field(ge=1, description="예상 지연 일수")
    cause: Literal["soldout", "restock", "courier", "weather", "customs"] = "restock"
    product_name: str = ""
    expected_date: str = Field(default="", description="입고/발송 예정일 (예: 11월 28일)")
    price: int = Field(default=0, ge=0)


class DelayNotice(BaseModel):
    text: str
    compensation: str
    needs_approval: bool
    notes: list[str] = Field(default_factory=list)


@tool(
    name="cs_shipping_delay_notice",
    team=TeamName.CS,
    description=(
        "품절·리오더·택배 지연 상황의 고객 안내 문구를 만든다. "
        "취소/교환 선택지를 주고, 보상은 대표 승인 없이는 약속하지 않는다."
    ),
    args=DelayArgs,
    returns="DelayNotice(안내문·보상 제안·승인 필요·메모)",
    tags=("shipping", "delay"),
)
def shipping_delay_notice(req: DelayArgs) -> DelayNotice:
    cause_text = {
        "soldout": "사입처 재고 소진",
        "restock": "리오더 입고 지연",
        "courier": "택배사 물량 증가",
        "weather": "기상 악화",
        "customs": "통관 지연",
    }[req.cause]
    when = f"{req.expected_date} " if req.expected_date else ""
    compensation = "없음 (대표 승인 시 쿠폰·배송비 환급 가능)"
    text = (
        f"주문하신 {req.product_name or '상품'}의 출고가 {cause_text}로 {req.delay_days}일가량 지연될 예정입니다. "
        f"{when}발송을 목표로 확인 중이며, 더 빨라지거나 늦어지면 바로 연락드리겠습니다. "
        "기다리기 어려우시면 취소·다른 옵션 교환도 도와드리겠습니다. 불편을 드려 죄송합니다."
    )
    return DelayNotice(
        text=text,
        compensation=compensation,
        needs_approval=False,
        notes=["지연 7일 초과 시 대표님 확인 후 보상 여부 결정", "취소 요청은 즉시 처리(위약금 없음)"],
    )


# ═══════════════════════════════════════════════
# 5) 불량 접수
# ═══════════════════════════════════════════════
class DefectArgs(BaseModel):
    product_name: str = ""
    defect_type: Literal["봉제", "오염", "사이즈오차", "이염", "부자재", "기타"] = "봉제"
    same_sku_reports: int = Field(default=1, ge=1, description="같은 SKU 불량 접수 건수")
    price: int = Field(default=0, ge=0)


class DefectIntake(BaseModel):
    text: str
    steps: list[str]
    needs_approval: bool
    production_note: str = ""


@tool(
    name="cs_defect_intake",
    team=TeamName.CS,
    description=(
        "불량 접수 응대 문구와 처리 절차를 만든다. 사진 요청 → 확인 → 교환/환불, "
        "동일 SKU 3건 이상이면 생산·검수팀 리포트."
    ),
    args=DefectArgs,
    returns="DefectIntake(안내문·절차·승인 필요·생산 리포트)",
    tags=("defect", "cs"),
)
def defect_intake(req: DefectArgs) -> DefectIntake:
    steps = [
        "상품 전체컷 + 불량 부위 접사 사진 요청",
        "주문번호·수령일 확인",
        "불량 확인 시 왕복 배송비 판매자 부담으로 교환/환불",
        "회수 상품 검수 후 사입처 클레임 진행",
    ]
    text = (
        f"{req.product_name or '상품'}의 {req.defect_type} 관련 불량으로 접수해 주셔서 감사합니다. "
        "상품 전체 사진과 불량 부위 접사 1~2장을 보내 주시면 바로 확인하겠습니다. "
        "확인 후에는 왕복 배송비 저희 부담으로 교환 또는 환불 처리해 드리겠습니다. "
        "불편을 드려 죄송합니다."
    )
    note = ""
    if req.same_sku_reports >= 3:
        note = f"동일 SKU 불량 {req.same_sku_reports}건 — 사입처 클레임·검수 기준 강화 필요"
    return DefectIntake(text=text, steps=steps, needs_approval=req.price >= 30_000, production_note=note)


# ═══════════════════════════════════════════════
# 6) 에스컬레이션 판정
# ═══════════════════════════════════════════════
class EscalationArgs(BaseModel):
    message: str = Field(description="고객 문의 원문")
    refund_amount: int = Field(default=0, ge=0, description="요구·예정 환불 금액")
    repeat_count: int = Field(default=1, ge=1, description="동일 고객 문의 횟수")
    order_value: int = Field(default=0, ge=0)


class Escalation(BaseModel):
    level: str = Field(description="low | mid | high")
    needs_approval: bool
    reasons: list[str] = Field(default_factory=list)
    sla_hours: int
    action: str


_HIGH_RISK = ("소비자원", "분쟁", "고소", "법적", "언론", "기자", "커뮤니티", "제보", "환불 안 해", "사기")
_ABUSE = ("욕설", "씨발", "병신", "꺼져", "개새")


@tool(
    name="cs_escalation_decision",
    team=TeamName.CS,
    description=(
        "문의 원문·환불액·반복 횟수로 자동 발송 가능 여부를 판정한다. "
        "법적 분쟁·언론·고액 환불·반복 항의는 대표 승인으로 올린다."
    ),
    args=EscalationArgs,
    returns="Escalation(단계·승인 필요·사유·응답 기한·조치)",
    tags=("escalation", "risk"),
)
def escalation_decision(req: EscalationArgs) -> Escalation:
    reasons: list[str] = []
    high = False
    if any(word in req.message for word in _HIGH_RISK):
        reasons.append("법적 분쟁·언론·소비자원 언급")
        high = True
    if req.refund_amount >= 30_000:
        reasons.append(f"환불 요구 {req.refund_amount:,}원 (3만원 이상)")
    if req.repeat_count >= 3:
        reasons.append(f"동일 고객 {req.repeat_count}회 반복 문의")
    if any(word in req.message for word in _ABUSE):
        reasons.append("욕설·모욕 표현")
        high = True

    if high:
        return Escalation(
            level="high",
            needs_approval=True,
            reasons=reasons,
            sla_hours=2,
            action="자동 발송 금지 — 대표님 확인 후 대응, 답변은 사실 관계만 간결하게",
        )
    if reasons:
        return Escalation(
            level="mid",
            needs_approval=True,
            reasons=reasons,
            sla_hours=12,
            action="초안 작성 후 대표 승인 받아 발송",
        )
    return Escalation(
        level="low",
        needs_approval=False,
        reasons=["일반 문의"],
        sla_hours=24,
        action="템플릿으로 자동 발송 가능",
    )


#: CS팀이 LLM에 바인딩하는 도구 목록.
TOOLS = [size_chart, exchange_guide, return_quote, shipping_delay_notice, defect_intake, escalation_decision]
