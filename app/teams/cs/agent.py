"""CS·운영팀 — 사이즈/배송 문의 초안, 교환·반품 처리, 불량 접수, 에스컬레이션.

주문이 들어온 뒤 계속 도는 팀이라 메인 배포 워크플로에는 넣지 않고,
같은 상품 상태를 입력으로 단독 실행할 수 있게 만들었습니다.
(향후 주문 웹훅 → CS팀 자동 초안 → 승인 후 발송 구조로 확장)

원칙: 환불·보상·법적 분쟁 가능 건은 자동 발송하지 않고 대표님 승인으로 올립니다.
"""

from __future__ import annotations

from typing import Any

from app.orchestrator.state import MallWorkflowState
from app.shared.models import CSPlaybook, InquiryTemplate, MDPlan, ProductItem, TeamName
from app.shared.prompting import PromptBundle, register_prompt
from app.shared.tooling import tool_manifest
from app.teams.cs.tools import (
    TOOLS,
    defect_intake,
    escalation_decision,
    exchange_guide,
    return_quote,
    shipping_delay_notice,
    size_chart,
)

TEAM = "cs"
TEAM_NAME = TeamName.CS
__all__ = ["TEAM", "SYSTEM_PROMPT", "USER_TEMPLATE", "PROMPT", "TOOLS", "build_prompt", "build_messages", "run"]

SYSTEM_PROMPT = f"""당신은 한국 남성 보세몰의 CS·운영 담당입니다.
보세몰 CS 문의의 대부분은 '사이즈가 안 맞는다', '언제 오나', '품절인데 언제 들어오나', '색이 다르다'입니다.
고객은 이미 돈을 냈고 기다리고 있다는 전제로, 짧고 정확하게, 다음 행동을 알려주는 답변을 씁니다.

[톤]
1. 호칭은 '고객님', 존댓말. 첫 문장은 공감 한 줄("불편을 드려 죄송합니다"), 두 번째는 사실, 세 번째는 다음 행동.
2. 이모지·감탄사·과장된 사과 반복은 쓰지 않습니다. 3~6문장으로 끝냅니다.
3. '아마', '될 것 같아요' 같은 추측 표현 대신 확인된 사실과 기한을 씁니다.
4. 답변 끝에는 고객이 할 일(주문번호 회신, 사진 전송, 옵션 선택)을 한 가지로 정리합니다.

[정책 — 숫자는 바꾸지 않습니다]
1. 교환·반품은 수령 후 7일 이내, 택 미부착·미착용 상태.
2. 단순 변심 왕복 배송비 6,000원(고객 부담), 하자·오배송은 판매자 부담.
3. 카드 환불 3~5영업일, 무통장 1~2영업일. 쿠폰 재발급은 대표 확인.
4. 품절·리오더는 입고 예정일을 확인한 뒤 안내하고, 취소·옵션 변경 선택지를 함께 줍니다.

[에스컬레이션 — 자동 발송 금지]
- 3만원 이상 환불·보상 요구
- 상품 하자·오배송으로 판매자 귀책이 명확한 건
- 소비자원·법적 분쟁·언론·커뮤니티 제보 언급
- 욕설·협박, 동일 고객 3회 이상 반복 항의
위 경우는 초안만 만들고 '대표 승인 필요'로 표시합니다.

[금지]
- 법적 책임을 인정하는 표현("저희 잘못입니다", "배상하겠습니다")을 임의로 쓰지 않습니다. 사실 확인 후 처리합니다.
- 보상(쿠폰·배송비 환급·적립금)을 승인 없이 약속하지 않습니다.
- 고객 개인정보(주민번호·카드번호)를 요구하거나 남기지 않습니다.
- 재고·입고일을 확인하지 않고 날짜를 단정하지 않습니다.

[도구]
{tool_manifest(TEAM_NAME)}

[출력]
CSPlaybook JSON만 출력합니다.
{{
  "templates": [{{"intent": "size|shipping|exchange|return|stock|etc", "question": "고객 문의 예시",
                 "draft": "답변 초안", "escalation": "승인 필요 조건"}}],
  "exchange_policy": ["..."],
  "escalation_rules": ["..."]
}}"""

USER_TEMPLATE = """[상품]
$name / $category / 판매가: $price원 / 사이즈: $sizes / 색상: $colors

[실측 사이즈표]
$size_table

[정책 계산 결과]
- 교환(사이즈): $exchange_line
- 반품(단순변심): $return_line
- 배송 지연 예시: $delay_line
- 불량 접수: $defect_line

[MD 참고]
$md_note

[요청]
1) 사이즈·배송·교환·반품·품절 5종 문의에 대한 답변 초안
2) 교환·반품 정책 요약
3) 에스컬레이션 기준(금액·표현·반복)
CSPlaybook JSON으로만 답하세요."""

PROMPT = register_prompt(
    PromptBundle(
        team=TEAM_NAME,
        role="CS·운영",
        system=SYSTEM_PROMPT,
        user_template=USER_TEMPLATE,
        output_contract="CSPlaybook JSON (templates[], exchange_policy[], escalation_rules[])",
    )
)


def _cs_inputs(product: ProductItem, md: MDPlan | None) -> dict[str, Any]:
    price = md.pricing.selling_price if md else (product.selling_price or 0)
    chart = size_chart(sizes=product.size_options or ["M", "L", "XL"], fit=product.fit)
    exchange = exchange_guide(
        reason="size",
        days_since_delivery=2,
        tag_attached=True,
        price=price,
        colors=product.color_options,
        sizes=product.size_options,
    )
    ret = return_quote(reason="change_of_mind", price=price)
    delay = shipping_delay_notice(delay_days=3, cause="restock", product_name=product.name, price=price)
    defect = defect_intake(product_name=product.name, defect_type="봉제", same_sku_reports=1, price=price)
    return {"price": price, "chart": chart, "exchange": exchange, "return": ret, "delay": delay, "defect": defect}


def build_prompt(product: ProductItem, plan: MDPlan | None = None) -> str:
    ctx = _cs_inputs(product, plan)
    return PROMPT.render(
        name=product.name,
        category=product.category,
        price=f"{ctx['price']:,}" if ctx["price"] else "미정",
        sizes="/".join(product.size_options or []),
        colors=", ".join(product.color_options) or "미기재",
        size_table=ctx["chart"].table_text,
        exchange_line=(
            f"가능 {ctx['exchange'].eligible} / 배송비 {ctx['exchange'].fee:,}원"
            f"({ctx['exchange'].payer} 부담)"
        ),
        return_line=f"환불 {ctx['return'].refund_amount:,}원 (배송비 {ctx['return'].fee:,}원 차감)",
        delay_line=ctx["delay"].text[:120],
        defect_line=ctx["defect"].text[:100],
        md_note=(plan.risk_notes[0] if plan and plan.risk_notes else "특이 리스크 없음"),
    )


def build_messages(product: ProductItem, plan: MDPlan | None = None) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": PROMPT.system},
        {"role": "user", "content": build_prompt(product, plan)},
    ]


def run(state: MallWorkflowState) -> dict[str, Any]:
    product = ProductItem.model_validate(state["product"])
    md: MDPlan | None = state.get("md_plan")
    ctx = _cs_inputs(product, md)

    price = ctx["price"]
    chart = ctx["chart"]
    recommended = chart.rows[1].size if len(chart.rows) > 1 else chart.rows[0].size
    esc = escalation_decision(message="사이즈 교환 문의", refund_amount=0, repeat_count=1)
    esc_high = escalation_decision(message="소비자원 신고하겠다고 하십니다", refund_amount=50_000, repeat_count=3)

    templates = [
        InquiryTemplate(
            intent="size",
            question="키 175에 몸무게 70인데 무슨 사이즈 입어야 하나요?",
            draft=(
                "안녕하세요, 고객님. 사이즈 문의 주셔서 감사합니다.\n"
                f"175cm/70kg 기준으로는 {recommended} 사이즈를 가장 많이 선택하십니다. "
                "정핏을 원하시면 평소 사이즈, 여유 있는 핏을 원하시면 한 사이즈 업을 권장드립니다.\n"
                f"{chart.model_line}\n{chart.table_text}\n"
                f"{chart.note}\n더 궁금한 점 있으시면 편하게 말씀해 주세요."
            ),
            escalation="",
        ),
        InquiryTemplate(
            intent="shipping",
            question="오늘 주문하면 언제 받을 수 있나요?",
            draft=(
                "안녕하세요, 고객님. 배송 문의 감사합니다.\n"
                "평일 오후 2시 이전 결제 완료 건은 당일 출고됩니다. 출고 후 보통 1~2영업일 내 수령 가능하며, "
                "택배사 사정에 따라 달라질 수 있습니다. 출고 시 송장 번호를 문자로 안내드립니다."
            ),
            escalation="지연 7일 초과 시 대표 확인 후 보상 여부 결정",
        ),
        InquiryTemplate(
            intent="exchange",
            question="색상이 마음에 안 들어서 교환하고 싶어요.",
            draft=ctx["exchange"].text,
            escalation="하자·오배송으로 판매자 부담이 되면 대표 승인 후 처리",
        ),
        InquiryTemplate(
            intent="return",
            question="사이즈가 안 맞아서 반품하려고 합니다.",
            draft=ctx["return"].text,
            escalation="3만원 이상 환불 또는 판매자 귀책이면 대표 승인 후 처리",
        ),
        InquiryTemplate(
            intent="stock",
            question="품절인 사이즈 언제 들어오나요?",
            draft=(
                "안녕하세요, 고객님. 문의 감사합니다.\n"
                "해당 사이즈는 현재 품절이며, 사입처에 리오더를 요청한 상태입니다. 입고 예정일은 확인 후 "
                "2~3일 내 다시 안내드리겠습니다. 원하시면 입고 알림을 신청해 주시면 바로 연락드리겠습니다."
            ),
            escalation="입고일 확인 전 날짜를 단정하지 않습니다",
        ),
        InquiryTemplate(
            intent="etc",
            question="봉제가 뜯어져서 왔어요.",
            draft=ctx["defect"].text,
            escalation="하자 접수 — 사진 확인 후 교환/환불, 3건 이상 시 생산·검수팀 리포트",
        ),
    ]

    playbook = CSPlaybook(
        templates=templates,
        exchange_policy=[
            "수령 후 7일 이내 교환·반품 가능 (택 미부착, 미착용)",
            "단순 변심 왕복 배송비 6,000원(고객 부담) / 하자·오배송 시 판매자 부담",
            "색상·사이즈 교환은 재고 범위 내 1회 접수 (배송비만 부담)",
            f"현재 판매가 {price:,}원 기준, 3만원 이상 환불은 대표 승인 필요",
            "카드 환불 3~5영업일 / 무통장 1~2영업일, 쿠폰 재발급은 대표 확인",
        ],
        escalation_rules=[
            f"일반 문의({esc.level}): 템플릿으로 자동 발송, {esc.sla_hours}시간 내 응답",
            f"고액·반복 문의({esc_high.level}): 대표 승인 후 발송, {esc_high.sla_hours}시간 내 1차 응답",
            *esc_high.reasons,
            "법적 분쟁·소비자원 신고·언론 제보 언급 → 즉시 대표님 에스컬레이션",
            "욕설·협박 → 1회 안내 후 대표님 이관",
            "상품 하자 3건 이상 동일 SKU 접수 → 검수팀·개발팀에 불량 리포트",
            "재고·입고일을 확인하지 않은 채 날짜 약속 금지",
        ],
    )

    return {
        "cs_playbook": playbook,
        "status": "running",
        "log": [
            f"[cs] 응대 템플릿 {len(templates)}종 / 에스컬레이션 규칙 {len(playbook.escalation_rules)}개 준비 "
            f"(추천 사이즈 {recommended}, 반품 환불 {ctx['return'].refund_amount:,}원)"
        ],
    }
