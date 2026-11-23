"""MD(상품기획)팀 — 동대문 사입 마진, 초도 발주 배분, 리오더 기준.

이 팀은 남성 보세몰의 현금흐름을 지키는 곳입니다. 시즌 트렌드보다 먼저 보는 것은
(1) 사입가에 수수료·배송·부가세·반품충당금을 다 얹고도 남는가,
(2) 초도 몇 장을 어떤 컬러·사이즈로 나눠야 품절과 재고를 동시에 피하는가,
(3) 언제 다시 발주해야 하는가입니다.

계산은 `app/teams/md/tools.py`의 도구가 담당하고, 이 모듈은 LLM에 넘길 프롬프트와
워크플로 산출물(`MDPlan`) 조립을 맡습니다. `LLM_PROVIDER=mock`에서도 도구는 그대로
실행되므로 숫자는 항상 같은 규칙으로 나옵니다.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from app.orchestrator.state import MallWorkflowState
from app.shared.config import get_settings
from app.shared.models import (
    MDPlan,
    PricingPlan,
    ProductItem,
    SourcingCandidate,
    TeamName,
    WorkflowStatus,
)
from app.shared.prompting import PromptBundle, register_prompt
from app.shared.tooling import tool_manifest
from app.teams.md.tools import (
    TOOLS,
    PriceQuote,
    allocate_initial_order,
    price_quote,
    reorder_signal,
    size_curve,
    sourcing_plan,
)

TEAM = "md"
TEAM_NAME = TeamName.MD
__all__ = ["TEAM", "SYSTEM_PROMPT", "USER_TEMPLATE", "PROMPT", "TOOLS", "build_prompt", "build_messages", "run"]

SYSTEM_PROMPT = f"""당신은 한국 남성 보세(사입) 쇼핑몰의 MD(상품기획) 담당입니다.
대표님을 대신해 '이 상품을 얼마에 사입해 얼마에 팔고, 몇 장을 어떻게 나눠 발주할지'를 결정합니다.
대상 고객은 20~30대 남성이며, 몰은 동대문 도매처에서 소량·다품종으로 사입해 2~4주 회전을 노립니다.

[판매가·마진 규칙]
1. 판매가는 부가세 포함가, 도매 공급가는 부가세 별도가 기본입니다.
2. 순이익 = 판매가 − 부가세 − 몰 수수료 − PG 결제 수수료 − 무료배송 원가 − 공급가 − 반품·불량 충당금.
3. 반품충당금(기본 판매가의 5%)과 PG 수수료(기본 1.8%)를 반드시 반영합니다. 이 둘을 빼면
   실제 마진보다 7~8%p 높게 착각하게 됩니다.
4. 순이익률 25% 미만이거나 판매가가 공급가의 2.0배 미만이면 그대로 제안하지 말고, 목표 마진을
   낮추거나 공급가를 재협상해야 한다고 명시합니다.
5. 판매가는 9,900 / 39,900처럼 끝자리를 마감해 제안합니다.

[초도 발주 규칙]
1. 사이즈 커브는 L·XL 중심(약 65%)이 기본이고, 오버핏·루즈핏은 XL·2XL로, 슬림핏은 M·L로 무게를 옮깁니다.
2. 컬러는 주력 1색에 60%를 몰고 나머지를 균등 배분합니다. 그래야 사진·재고·반품이 단순해집니다.
3. 도매처 MOQ보다 적은 컬러 조합은 만들지 않습니다. 0장이 나온 조합은 '옵션 비활성'으로 표시합니다.
4. 초도 수량은 예상 2~3주 판매량의 1.6배를 넘기지 않습니다. 첫 사입은 '팔려서 아쉬운' 쪽보다
   '남아서 아픈' 쪽을 피합니다.

[리오더 규칙]
1. 소진 일수 = 현재 재고 ÷ 일평균 판매량입니다.
2. 소진 일수가 리드타임 이하면 critical(즉시 발주), 리드타임+안전재고(7일) 이하면 reorder입니다.
3. 리오더 수량은 (리드타임+안전재고) 소진분에서 현재 재고를 빼고 MOQ 단위로 올림합니다.
4. 판매 데이터가 없는 신상품은 가정값으로 계산하되, '가정'이라고 명시하고 2주 실판매로 재계산하도록 남깁니다.

[금지]
- 근거 없는 매출·판매량·업계 1위·완판 표현을 쓰지 않습니다(표시광고법).
- 실재고 0장 상품을 판매 가능 상태로 넘기지 않습니다.
- 사입처 실재고·단가 확인 없이 '확정 발주'로 단정하지 않습니다. 확인 전에는 '확인 필요'로 남깁니다.
- 데이터가 없는데 숫자를 만들어 채우지 않습니다. 가정이면 가정이라고 씁니다.

[도구]
아래 도구로 계산합니다. 숫자는 반드시 도구 결과를 쓰고 암산하지 않습니다.
{tool_manifest(TEAM_NAME)}

[출력]
아래 JSON 하나만 출력합니다. 설명 문장·마크다운 없이 JSON만.
{{
  "trend_summary": "시즌·카테고리 수요 요약 2~3문장",
  "trend_keywords": ["검색 키워드 5~6개"],
  "target_customer": "타겟 고객 한 줄",
  "season": "시즌",
  "sourcing_list": [{{"supplier": "", "item_name": "", "cost_price": 0, "moq": 0,
                    "lead_time_days": 0, "url": null, "note": ""}}],
  "pricing": {{"cost_price": 0, "selling_price": 0, "vat_amount": 0, "platform_fee": 0,
              "payment_fee": 0, "return_reserve": 0, "shipping_fee": 0, "net_profit": 0,
              "margin_rate": 0.0, "break_even_units": 1, "note": ""}},
  "inventory_notes": ["초도 배분·리오더 기준"],
  "risk_notes": ["확인 필요 사항"]
}}"""

USER_TEMPLATE = """[상품]
SKU: $sku
상품명: $name
카테고리: $category
핏: $fit / 소재: $material / 색상: $colors / 사이즈: $sizes
공급가: $cost원 (VAT 별도) / 현재 재고: $stock장
사입처: $supplier / 제조국: $origin

[몰 조건]
시즌: $season / 목표 순이익률: $target_margin / 몰 수수료: $platform_fee / PG 수수료: $payment_fee
반품충당금: $return_reserve / 무료배송 원가: $shipping원 / 최소 마진: $minimum_margin

[도구 계산 결과 — 이 숫자를 그대로 사용]
$quote_line
$curve_line
$order_line
$reorder_line
$sourcing_line

[요청]
1) 이 상품을 지금 팔아야 하는 이유(시즌·카테고리 수요)와 검색 키워드 5~6개
2) 위 판매가·마진을 그대로 쓴 가격 계획과, 마진이 부족하면 어떤 조건을 바꿔야 하는지
3) 컬러×사이즈 초도 발주 배분과 리오더 기준
4) 배포 전에 대표님이 확인해야 할 리스크(도매처 재고, 비침·오염, MOQ 등)
위 출력 스키마의 JSON으로만 답하세요."""

PROMPT = register_prompt(
    PromptBundle(
        team=TEAM_NAME,
        role="MD(상품기획)",
        system=SYSTEM_PROMPT,
        user_template=USER_TEMPLATE,
        output_contract=(
            "MDPlan JSON (trend_summary, trend_keywords, sourcing_list, pricing, "
            "inventory_notes, risk_notes)"
        ),
    )
)


def _season(now: datetime) -> str:
    month = now.month
    if month in (3, 4, 5):
        return "봄 (SS)"
    if month in (6, 7, 8):
        return "여름 (SS)"
    if month in (9, 10, 11):
        return "가을 (FW)"
    return "겨울 (FW)"


def _initial_qty(product: ProductItem) -> int:
    settings = get_settings()
    base = max(product.stock, 10) * settings.initial_order_multiplier
    return int(max(20, min(200, math.ceil(base / 5) * 5)))


def _quote(product: ProductItem) -> PriceQuote:
    s = get_settings()
    return price_quote(
        cost_price=product.cost_price,
        selling_price=product.selling_price,
        target_margin_rate=product.target_margin_rate or s.default_target_margin_rate,
        shipping_cost=s.default_shipping_fee,
        platform_fee_rate=s.platform_fee_rate,
        payment_fee_rate=s.payment_fee_rate,
        return_reserve_rate=s.return_reserve_rate,
        vat_rate=s.vat_rate,
        fixed_monthly_cost=s.monthly_fixed_cost,
    )


def _context(product: ProductItem) -> dict[str, Any]:
    """프롬프트와 실행이 같은 숫자를 쓰도록 한 번만 계산한다."""
    s = get_settings()
    season = _season(datetime.now(UTC))
    quote = _quote(product)
    curve = size_curve(sizes=product.size_options or ["M", "L", "XL"], fit=product.fit, category=product.category)
    colors = product.color_options or ["단일색"]
    qty = _initial_qty(product)
    order = allocate_initial_order(
        total_qty=qty,
        colors=colors,
        sizes=product.size_options or ["M", "L", "XL"],
        size_weights=curve.weights,
        moq_per_color=10,
    )
    # 판매 이력이 없는 신상품: 가정값임을 명시하고 리오더 신호를 계산한다.
    assumed_weekly = 20.0
    reorder = reorder_signal(
        current_stock=product.stock,
        weekly_sales=assumed_weekly,
        lead_time_days=3,
        safety_days=7,
        moq=10,
    )
    sourcing = sourcing_plan(
        item_name=product.name,
        supplier=product.supplier,
        cost_price=product.cost_price,
        lead_time_days=3,
        moq=10,
        initial_qty=order.total,
        source_url=product.source_url,
    )
    return {
        "season": season,
        "quote": quote,
        "curve": curve,
        "colors": colors,
        "sizes": product.size_options or ["M", "L", "XL"],
        "order": order,
        "assumed_weekly": assumed_weekly,
        "reorder": reorder,
        "sourcing": sourcing,
        "settings": s,
    }


def _lines(ctx: dict[str, Any]) -> dict[str, str]:
    quote = ctx["quote"]
    curve = ctx["curve"]
    order = ctx["order"]
    reorder = ctx["reorder"]
    sourcing = ctx["sourcing"]
    return {
        "quote_line": (
            f"- 판매가 {quote.selling_price:,}원: 부가세 {quote.vat_amount:,} / 몰 수수료 {quote.platform_fee:,} / "
            f"PG {quote.payment_fee:,} / 반품충당금 {quote.return_reserve:,} / 배송원가 {quote.shipping_cost:,} → "
            f"순이익 {quote.net_profit:,}원 (마진율 {quote.margin_rate:.1%}, 배수 {quote.markup_multiple:.1f}배, "
            f"{quote.price_basis})"
        ),
        "curve_line": f"- 사이즈 커브: {curve.weights} / 주력 {'/'.join(curve.main_sizes)} — {curve.rationale}",
        "order_line": (
            f"- 초도 {order.total}장 배분: "
            + " · ".join(f"{c} {'/'.join(f'{s} {n}' for s, n in row.items())}" for c, row in order.matrix.items())
            + (f" / 경고: {'; '.join(order.warnings)}" if order.warnings else "")
        ),
        "reorder_line": (
            f"- 리오더 신호: {reorder.level} / 소진 {reorder.days_of_cover}일 / "
            f"제안 {reorder.reorder_qty}장 — {reorder.reason} "
            f"(판매 이력 없음: 주 {ctx['assumed_weekly']:.0f}장 가정)"
        ),
        "sourcing_line": "- 사입 후보: " + " | ".join(
            f"{o.supplier} {o.cost_price:,}원·MOQ {o.moq}·{o.lead_time_days}일" for o in sourcing
        ),
    }


def build_prompt(product: ProductItem) -> str:
    """LLM 사용자 메시지 1개(문자열). LLM을 붙일 때 그대로 보냅니다."""
    ctx = _context(product)
    s = ctx["settings"]
    values = {
        "sku": product.sku,
        "name": product.name,
        "category": product.category,
        "fit": product.fit,
        "material": product.material or "미기재",
        "colors": ", ".join(ctx["colors"]),
        "sizes": "/".join(ctx["sizes"]),
        "cost": f"{product.cost_price:,}",
        "stock": product.stock,
        "supplier": product.supplier or "미지정",
        "origin": product.country_of_origin or "미기재",
        "season": ctx["season"],
        "target_margin": f"{product.target_margin_rate or s.default_target_margin_rate:.0%}",
        "platform_fee": f"{s.platform_fee_rate:.1%}",
        "payment_fee": f"{s.payment_fee_rate:.1%}",
        "return_reserve": f"{s.return_reserve_rate:.0%}",
        "shipping": f"{s.default_shipping_fee:,}",
        "minimum_margin": f"{s.minimum_margin_rate:.0%}",
        **_lines(ctx),
    }
    return PROMPT.render(**values)


def build_messages(product: ProductItem) -> list[dict[str, str]]:
    """OpenAI/Anthropic 공통 messages. 시스템 프롬프트 + 사용자 메시지."""
    return [
        {"role": "system", "content": PROMPT.system},
        {"role": "user", "content": build_prompt(product)},
    ]


def run(state: MallWorkflowState) -> dict[str, Any]:
    """상품 1건을 받아 기획안(md_plan)을 만든다."""
    product = ProductItem.model_validate(state["product"])
    ctx = _context(product)
    quote, curve, order, reorder, sourcing = (
        ctx["quote"],
        ctx["curve"],
        ctx["order"],
        ctx["reorder"],
        ctx["sourcing"],
    )

    pricing = PricingPlan(
        cost_price=quote.cost_price,
        selling_price=quote.selling_price,
        vat_amount=quote.vat_amount,
        platform_fee=quote.platform_fee,
        payment_fee=quote.payment_fee,
        return_reserve=quote.return_reserve,
        shipping_fee=quote.shipping_cost,
        net_profit=quote.net_profit,
        margin_rate=quote.margin_rate,
        break_even_units=quote.break_even_units,
        note=(
            f"{quote.price_basis} / 몰 수수료 {ctx['settings'].platform_fee_rate:.1%} · "
            f"PG {ctx['settings'].payment_fee_rate:.1%} · "
            f"반품충당금 {ctx['settings'].return_reserve_rate:.0%} · "
            f"무료배송 원가 {quote.shipping_cost:,}원 반영"
        ),
    )

    keywords = [k.strip() for k in dict.fromkeys([*product.keywords, *product.category.split(">")]) if k.strip()][:6]
    leaf = product.category.split(">")[-1].strip() or product.category
    silhouette = "오버핏·와이드 실루엣" if product.fit != "slim" else "슬림·클래식 핏"
    trend_summary = (
        f"{ctx['season']} 남성 {leaf} 수요는 {silhouette} 키워드가 강합니다. "
        "보세 도매 회전이 빠른 품목으로, 초도 소량 사입 후 반응 좋은 사이즈만 리오더하는 전략을 권장합니다."
    )
    if product.material:
        trend_summary += f" 소재는 {product.material} 기준으로 촉감·구김 관련 상세 설명을 강조하세요."

    inventory_notes = [
        f"초도 사입 {order.total}장 — "
        + ", ".join(f"{c} {q}장" for c, q in order.per_color.items())
        + f" / 사이즈 {' · '.join(f'{s} {order.per_size[s]}장' for s in ctx['sizes'])}",
        (
            f"주력 사이즈 {'/'.join(curve.main_sizes)} "
            f"비중 {sum(curve.weights[s] for s in curve.main_sizes):.0%} — {curve.rationale}"
        ),
        f"리오더 기준: 소진 {reorder.days_of_cover}일일 때 {reorder.reorder_qty}장 발주 ({reorder.reason}). "
        f"판매 이력이 없어 주 {ctx['assumed_weekly']:.0f}장 가정 — 2주 실판매로 재계산",
        "소진율 70% 도달 시 자동 리오더 알림 (개발팀 재고 동기화 연동)",
    ]
    inventory_notes.extend(f"발주 주의: {w}" for w in order.warnings)
    if order.disabled_options:
        inventory_notes.append(
            f"0장 조합 {len(order.disabled_options)}개는 등록 시 옵션 비활성: "
            f"{', '.join(order.disabled_options[:6])}"
        )

    risk_notes = [
        "도매처 재고는 수시로 변동 — 발주 전 실재고 확인 필요",
        "흰색·아이보리는 오염/비침 클레임 빈도가 높아 검수 시 봉제·비침 확인",
        *quote.warnings,
        "대체 사입처 단가는 가정값 — 샘플 봉제·원단 확인 전 확정 발주 금지",
    ]

    plan = MDPlan(
        trend_summary=trend_summary,
        trend_keywords=keywords or ["남성 데일리", product.category],
        target_customer="20~30대 남성, 데일리·출근 겸용 캐주얼",
        season=ctx["season"],
        sourcing_list=[
            SourcingCandidate(
                supplier=o.supplier,
                item_name=o.item_name,
                cost_price=o.cost_price,
                moq=o.moq,
                lead_time_days=o.lead_time_days,
                url=o.url,
                note=o.note,
            )
            for o in sourcing
        ],
        pricing=pricing,
        inventory_notes=inventory_notes,
        risk_notes=list(dict.fromkeys(risk_notes)),
    )

    return {
        "md_plan": plan,
        "status": WorkflowStatus.RUNNING,
        "log": [
            f"[md] 기획 완료 — 판매가 {pricing.selling_price:,}원 / 순이익 {pricing.net_profit:,}원 "
            f"(마진율 {pricing.margin_rate:.1%}) / 초도 {order.total}장"
        ],
    }
