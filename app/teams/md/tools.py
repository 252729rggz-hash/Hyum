"""MD(상품기획)팀 도구 — 동대문 사입 마진, 초도 발주 배분, 리오더 판단.

모든 도구는 `입력 모델 → 결과 모델` 순수 함수입니다. 워크플로 실행 중에는 그대로 호출하고,
LLM을 붙일 때는 같은 스키마를 function calling으로 넘깁니다(`openai_tools(TeamName.MD)`).
금액 단위는 모두 원(KRW), 비율은 0~1 소수입니다.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from app.shared.models import TeamName
from app.shared.tooling import tool

#: 이 아래로 떨어지면 보세몰 회전 구조에서 광고비를 못 버팁니다.
MIN_MARGIN_RATE = 0.25

#: 남성 보세몰 표준 사이즈 커브 (L·XL 중심 65%).
DEFAULT_SIZE_CURVE: dict[str, float] = {"S": 0.05, "M": 0.20, "L": 0.35, "XL": 0.30, "2XL": 0.10}

OVERSIZE_CURVE: dict[str, float] = {"S": 0.03, "M": 0.15, "L": 0.30, "XL": 0.35, "2XL": 0.17}

SLIM_CURVE: dict[str, float] = {"S": 0.10, "M": 0.30, "L": 0.40, "XL": 0.15, "2XL": 0.05}


# ═══════════════════════════════════════════════
# 1) 판매가·마진
# ═══════════════════════════════════════════════
class PriceQuoteArgs(BaseModel):
    """판매가·마진 산출 입력. 실제 사입 조건을 그대로 넣습니다."""

    cost_price: int = Field(ge=0, description="도매 공급가(원, VAT 별도)")
    selling_price: int | None = Field(default=None, ge=0, description="지정 판매가. 없으면 목표 마진으로 역산")
    target_margin_rate: float = Field(default=0.55, gt=0, lt=1, description="목표 순이익률(판매가 대비)")
    shipping_cost: int = Field(default=3000, ge=0, description="무료배송 원가(건당 택배비)")
    platform_fee_rate: float = Field(default=0.035, ge=0, lt=1, description="몰 수수료율(부가세 제외 매출 기준)")
    payment_fee_rate: float = Field(default=0.018, ge=0, lt=1, description="PG 결제 수수료율(결제액 기준)")
    return_reserve_rate: float = Field(default=0.05, ge=0, lt=1, description="반품·불량 충당금 비율(판매가 기준)")
    vat_rate: float = Field(default=0.1, ge=0, lt=1, description="부가세율")
    fixed_monthly_cost: int = Field(default=0, ge=0, description="월 고정비(광고·툴). 손익분기 수량 계산용")


class PriceQuote(BaseModel):
    selling_price: int
    cost_price: int
    vat_amount: int
    platform_fee: int
    payment_fee: int
    return_reserve: int
    shipping_cost: int
    net_profit: int
    margin_rate: float
    markup_multiple: float = Field(description="판매가 ÷ 공급가 (보세몰 통상 2.2~3.0배)")
    break_even_units: int
    price_basis: str
    warnings: list[str] = Field(default_factory=list)


def _round_psychological(value: float) -> int:
    """판매가를 9,900 / 39,900 형태로 올림 마감한다."""
    if value <= 0:
        return 0
    step = 10_000 if value >= 100_000 else 1_000
    rounded = math.ceil(value / step) * step
    return max(rounded - 100, 100)


@tool(
    name="md_price_quote",
    team=TeamName.MD,
    description=(
        "공급가·몰 수수료·PG 수수료·무료배송 원가·부가세·반품충당금을 모두 반영해 판매가와 순이익을 계산한다. "
        "지정 판매가가 있으면 그 가격을 검증만 하고, 없으면 목표 순이익률로 역산한다."
    ),
    args=PriceQuoteArgs,
    returns="PriceQuote(판매가·부가세·수수료·충당금·순이익·마진율·배수·손익분기)",
    tags=("pricing", "margin"),
)
def price_quote(req: PriceQuoteArgs) -> PriceQuote:
    # 판매가 1원이 순이익에 기여하는 비율 (부가세·몰 수수료·PG 수수료·반품충당금 차감 후)
    net_ratio = 1 / (1 + req.vat_rate) * (1 - req.platform_fee_rate) - req.payment_fee_rate - req.return_reserve_rate
    variable_cost = req.cost_price + req.shipping_cost
    warnings: list[str] = []

    if req.selling_price:
        selling = req.selling_price
        basis = "입력 판매가 기준 검증"
    elif net_ratio - req.target_margin_rate > 0.05:
        selling = _round_psychological(variable_cost / (net_ratio - req.target_margin_rate))
        basis = f"목표 순이익률 {req.target_margin_rate:.0%} 역산"
    else:
        selling = _round_psychological(req.cost_price * 2.2)
        basis = "목표 마진 구조 불가 → 공급가 2.2배 보수 책정"
        warnings.append(
            f"수수료·충당금 합계가 목표 마진({req.target_margin_rate:.0%})를 잠식합니다. "
            "마진 목표 하향 또는 공급가 재협상 필요"
        )

    vat_amount = round(selling * req.vat_rate / (1 + req.vat_rate))
    net_revenue = selling - vat_amount
    platform_fee = round(net_revenue * req.platform_fee_rate)
    payment_fee = round(selling * req.payment_fee_rate)
    return_reserve = round(selling * req.return_reserve_rate)
    net_profit = net_revenue - platform_fee - payment_fee - return_reserve - req.cost_price - req.shipping_cost
    margin_rate = round(net_profit / selling, 4) if selling else 0.0
    markup = round(selling / req.cost_price, 2) if req.cost_price else 0.0
    break_even = math.ceil(req.fixed_monthly_cost / net_profit) if net_profit > 0 else 0

    if net_profit <= 0:
        warnings.append("역마진: 판매가에서 원가·수수료·충당금을 빼면 손실입니다")
    elif margin_rate < MIN_MARGIN_RATE:
        warnings.append(f"순이익률 {margin_rate:.1%} — 최소 기준 {MIN_MARGIN_RATE:.0%} 미달")
    if req.cost_price and markup < 2.0:
        warnings.append(f"판매 배수 {markup:.1f}배 — 보세몰 통상 2.2배 이상 필요")
    if req.cost_price and markup >= 4.0:
        warnings.append(f"판매 배수 {markup:.1f}배 — 통상 2.2~3.0배보다 높음. 경쟁 상품 시장가 확인 필요")

    return PriceQuote(
        selling_price=selling,
        cost_price=req.cost_price,
        vat_amount=vat_amount,
        platform_fee=platform_fee,
        payment_fee=payment_fee,
        return_reserve=return_reserve,
        shipping_cost=req.shipping_cost,
        net_profit=net_profit,
        margin_rate=margin_rate,
        markup_multiple=markup,
        break_even_units=max(break_even, 1),
        price_basis=basis,
        warnings=warnings,
    )


# ═══════════════════════════════════════════════
# 2) 사이즈 커브
# ═══════════════════════════════════════════════
class SizeCurveArgs(BaseModel):
    sizes: list[str] = Field(default_factory=lambda: ["M", "L", "XL", "2XL"], min_length=1, description="판매 사이즈")
    fit: str = Field(default="regular", description="regular | slim | oversized | loose")
    category: str = Field(default="", description="예: 남성 아우터 > 바람막이")


class SizeCurve(BaseModel):
    weights: dict[str, float] = Field(description="사이즈별 초도 사입 비중(합계 약 1.0)")
    main_sizes: list[str] = Field(description="비중 상위 2개 사이즈")
    rationale: str


def _normalize(weights: dict[str, float], sizes: list[str]) -> dict[str, float]:
    picked = {s: max(weights.get(s, 0.0), 0.0) for s in sizes}
    total = sum(picked.values())
    if total <= 0:
        even = round(1 / len(sizes), 4)
        return {s: even for s in sizes}
    return {s: round(w / total, 4) for s, w in picked.items()}


@tool(
    name="md_size_curve",
    team=TeamName.MD,
    description=(
        "핏과 카테고리에 맞는 남성 사이즈 커브(초도 사입 비중)를 제안한다. "
        "오버핏은 XL·2XL로, 슬림은 M·L로 무게가 이동한다."
    ),
    args=SizeCurveArgs,
    returns="SizeCurve(사이즈별 비중·주력 사이즈·근거)",
    tags=("inventory", "size"),
)
def size_curve(req: SizeCurveArgs) -> SizeCurve:
    if req.fit in ("oversized", "loose"):
        base, note = OVERSIZE_CURVE, "오버핏·루즈핏은 한 사이즈 크게 입는 수요가 많아 XL·2XL 비중을 올립니다"
    elif req.fit == "slim":
        base, note = SLIM_CURVE, "슬림핏은 정사이즈 착용이 많아 M·L 중심으로 잡습니다"
    else:
        base, note = DEFAULT_SIZE_CURVE, "레귤러핏은 L·XL 중심 표준 커브를 씁니다"

    weights = _normalize(base, req.sizes)
    main = sorted(weights, key=lambda s: weights[s], reverse=True)[:2]
    return SizeCurve(
        weights=weights,
        main_sizes=main,
        rationale=f"{note}. 주력 {'/'.join(main)} 합계 {sum(weights[s] for s in main):.0%}. {req.category}".strip(),
    )


# ═══════════════════════════════════════════════
# 3) 초도 발주 배분
# ═══════════════════════════════════════════════
class InitialOrderArgs(BaseModel):
    total_qty: int = Field(ge=1, description="초도 사입 총 수량(장)")
    colors: list[str] = Field(min_length=1, description="컬러 옵션")
    sizes: list[str] = Field(min_length=1, description="사이즈 옵션")
    size_weights: dict[str, float] | None = Field(default=None, description="사이즈 비중(미지정 시 균등)")
    color_weights: dict[str, float] | None = Field(default=None, description="컬러 비중(미지정 시 주력 1색 60%)")
    moq_per_color: int = Field(default=10, ge=1, description="컬러별 최소 사입 수량(MOQ)")


class InitialOrder(BaseModel):
    matrix: dict[str, dict[str, int]] = Field(description="컬러 → 사이즈 → 수량")
    per_color: dict[str, int]
    per_size: dict[str, int]
    total: int
    disabled_options: list[str] = Field(default_factory=list, description="0장이 나온 컬러/사이즈 조합")
    warnings: list[str] = Field(default_factory=list)


def _split(total: int, weights: dict[str, float]) -> dict[str, int]:
    """최대잔여법으로 정수 배분해 합계를 정확히 total에 맞춘다."""
    raw = {k: total * max(w, 0.0) for k, w in weights.items()}
    base = {k: math.floor(v) for k, v in raw.items()}
    remainder = total - sum(base.values())
    order = sorted(raw, key=lambda k: raw[k] - base[k], reverse=True)
    for key in order[:remainder]:
        base[key] += 1
    return base


def _default_color_weights(colors: list[str]) -> dict[str, float]:
    if len(colors) == 1:
        return {colors[0]: 1.0}
    head = 0.6
    rest = (1 - head) / (len(colors) - 1)
    return {c: head if i == 0 else rest for i, c in enumerate(colors)}


@tool(
    name="md_allocate_initial_order",
    team=TeamName.MD,
    description=(
        "초도 사입 수량을 컬러×사이즈 조합으로 배분한다. 주력 컬러 60%, "
        "사이즈 커브를 반영하고 MOQ 미달 컬러를 경고한다."
    ),
    args=InitialOrderArgs,
    returns="InitialOrder(컬러×사이즈 배분표·합계·비활성 옵션·경고)",
    tags=("inventory", "sourcing"),
)
def allocate_initial_order(req: InitialOrderArgs) -> InitialOrder:
    color_weights = req.color_weights or _default_color_weights(req.colors)
    weights = req.size_weights or {s: 1 / len(req.sizes) for s in req.sizes}
    # 요청 사이즈만 남기고 정규화
    weights = _normalize({s: weights.get(s, 0.0) for s in req.sizes}, req.sizes)

    per_color = _split(req.total_qty, {c: color_weights.get(c, 0.0) for c in req.colors})
    matrix: dict[str, dict[str, int]] = {}
    disabled: list[str] = []
    for color, qty in per_color.items():
        row = _split(qty, weights) if qty >= len(req.sizes) else {s: 0 for s in req.sizes}
        matrix[color] = row
        disabled.extend(f"{color}/{size}" for size, n in row.items() if n == 0)

    per_size = {s: sum(matrix[c][s] for c in req.colors) for s in req.sizes}
    warnings: list[str] = []
    short = [f"{c}({q}장)" for c, q in per_color.items() if q < req.moq_per_color]
    if short:
        warnings.append(f"MOQ {req.moq_per_color}장 미달 컬러: {', '.join(short)} — 도매처 협의 또는 컬러 수 축소")
    if disabled:
        warnings.append(f"0장 배분 조합 {len(disabled)}개는 등록 시 옵션 비활성 처리")

    return InitialOrder(
        matrix=matrix,
        per_color=per_color,
        per_size=per_size,
        total=sum(per_color.values()),
        disabled_options=disabled,
        warnings=warnings,
    )


# ═══════════════════════════════════════════════
# 4) 리오더 신호
# ═══════════════════════════════════════════════
class ReorderArgs(BaseModel):
    current_stock: int = Field(ge=0, description="현재 창고 재고(장)")
    weekly_sales: float = Field(ge=0, description="최근 7일 판매량(장)")
    lead_time_days: int = Field(default=3, ge=0, description="사입 리드타임(일)")
    safety_days: int = Field(default=7, ge=0, description="목표 안전재고 일수")
    moq: int = Field(default=10, ge=1, description="최소 사입 수량")


class ReorderSignal(BaseModel):
    level: str = Field(description="soldout | critical | reorder | ok")
    days_of_cover: float = Field(description="현재 재고로 버티는 일수")
    reorder_qty: int
    reason: str


@tool(
    name="md_reorder_signal",
    team=TeamName.MD,
    description="일 판매 속도·리드타임·안전재고로 품절 위험을 판정하고 리오더 수량을 MOQ 단위로 계산한다.",
    args=ReorderArgs,
    returns="ReorderSignal(위험도·재고 소진 일수·리오더 수량·사유)",
    tags=("inventory", "reorder"),
)
def reorder_signal(req: ReorderArgs) -> ReorderSignal:
    daily = req.weekly_sales / 7
    if daily <= 0:
        return ReorderSignal(level="ok", days_of_cover=999.0, reorder_qty=0, reason="최근 판매 없음 — 리오더 보류")
    cover = round(req.current_stock / daily, 1)
    target = math.ceil(daily * (req.lead_time_days + req.safety_days))
    need = max(0, target - req.current_stock)

    if req.current_stock == 0:
        level = "soldout"
        reason = "재고 0 — 판매 중단 상태, 긴급 사입 필요"
    elif cover <= req.lead_time_days:
        level = "critical"
        reason = f"재고 소진 {cover}일 ≤ 리드타임 {req.lead_time_days}일 — 품절 전 사입 필요"
    elif cover <= req.lead_time_days + req.safety_days:
        level = "reorder"
        reason = f"재고 소진 {cover}일 — 안전재고 구간 진입, 리오더 발주"
    else:
        level = "ok"
        reason = f"재고 소진 {cover}일 — 리오더 불필요"

    qty = math.ceil(need / req.moq) * req.moq if need > 0 else 0
    return ReorderSignal(level=level, days_of_cover=cover, reorder_qty=qty, reason=reason)


# ═══════════════════════════════════════════════
# 5) 사입처 후보
# ═══════════════════════════════════════════════
class SourcingArgs(BaseModel):
    item_name: str = Field(description="상품명(작업용)")
    supplier: str = Field(default="", description="현재 사입처")
    cost_price: int = Field(ge=0, description="현재 공급가")
    lead_time_days: int = Field(default=3, ge=0)
    moq: int = Field(default=10, ge=1)
    initial_qty: int = Field(default=30, ge=1, description="이번 초도 사입 수량")
    source_url: str | None = None


class SourcingOption(BaseModel):
    supplier: str
    item_name: str
    cost_price: int
    moq: int
    lead_time_days: int
    url: str | None = None
    note: str = ""


@tool(
    name="md_sourcing_plan",
    team=TeamName.MD,
    description=(
        "현재 사입처 기준 사입안과 단가·리드타임을 맞바꾼 대체처 검토안을 만든다. "
        "대체처 단가는 가정값이므로 샘플 확인 전 확정 금지."
    ),
    args=SourcingArgs,
    returns="list[SourcingOption](사입처·단가·MOQ·리드타임·메모)",
    tags=("sourcing",),
)
def sourcing_plan(req: SourcingArgs) -> list[SourcingOption]:
    base = req.supplier or "동대문 도매처(미지정)"
    return [
        SourcingOption(
            supplier=base,
            item_name=req.item_name,
            cost_price=req.cost_price,
            moq=req.moq,
            lead_time_days=req.lead_time_days,
            url=req.source_url,
            note=f"초도 {req.initial_qty}장 — 기존 거래처, 샘플·반품 처리 조건 유지",
        ),
        SourcingOption(
            supplier=f"{base} 대체처(검토)",
            item_name=f"{req.item_name} 동일 원단 대체",
            cost_price=max(int(req.cost_price * 0.93), 1000),
            moq=max(req.moq, 30),
            lead_time_days=req.lead_time_days + 2,
            url=None,
            note="단가 7% 절감 가정 — MOQ 30장·리드타임 +2일. 실물 샘플 봉제·원단 확인 전 발주 금지",
        ),
    ]


#: MD팀이 LLM에 바인딩하는 도구 목록.
TOOLS = [price_quote, size_curve, allocate_initial_order, reorder_signal, sourcing_plan]
