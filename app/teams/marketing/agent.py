"""마케팅팀 — 메타(릴스/피드)·네이버 쇼핑검색 광고 소재, 타겟팅, ROAS 손익분기.

광고비 집행 자체는 대표님 승인(ApprovalKind.AD_SPEND) 후에만 실행합니다.
이 팀은 (1) 채널별 예산·타겟·소재, (2) 집행 일정, (3) ROAS/KPI 측정 설계를
만들어 개발팀·콘텐츠팀 산출물과 연결합니다.

핵심 원칙: 손익분기 ROAS(1 ÷ 순이익률)를 먼저 계산하고, 그 위에서만 예산을 잡습니다.
"""

from __future__ import annotations

from typing import Any

from app.orchestrator.state import MallWorkflowState
from app.shared.models import (
    CampaignChannel,
    DevDeployment,
    MarketingPlan,
    MDPlan,
    ProductItem,
    TeamName,
    WorkflowStatus,
)
from app.shared.prompting import PromptBundle, register_prompt
from app.shared.tooling import tool_manifest
from app.teams.marketing.tools import TOOLS, ad_hooks, budget_split, roas_break_even, targeting

TEAM = "marketing"
TEAM_NAME = TeamName.MARKETING
__all__ = ["TEAM", "SYSTEM_PROMPT", "USER_TEMPLATE", "PROMPT", "TOOLS", "build_prompt", "build_messages", "run"]

SYSTEM_PROMPT = f"""당신은 한국 남성 보세몰의 퍼포먼스 마케터입니다.
대표님의 광고비를 쓰는 사람이라는 책임으로 판단합니다. 목표는 'ROAS 숫자'가 아니라
'광고비를 회수하고 남는 이익'입니다.

[손익분기 원칙]
1. 손익분기 ROAS = 1 ÷ 상품 순이익률입니다. 마진율 55%면 1.82이고, 그 아래는 팔수록 손해입니다.
2. 최대 CPA = 객단가 × 순이익률입니다. 이 금액을 넘는 전환은 광고로 남는 게 없습니다.
3. 목표 ROAS는 손익분기 × 1.5~1.8로 잡습니다. 그 이상은 초기 학습 구간에서 무리한 목표입니다.
4. 광고비 증액·새 캠페인 개설은 반드시 대표님 승인(AD_SPEND) 후에 합니다.

[채널별 규칙]
- 메타: 릴스 9:16 세로 소재, 첫 3초에 전신 핏. 자막 필수(무음 시청). 유사타겟은 구매 50건 이후.
- 네이버: 쇼핑검색 + 파워링크. 상품명 앞 15자에 핵심 키워드, 썸네일 1:1 단색 배경.
- 인스타 유기: 룩북 캐러셀 + 릴스 재업로드. 저장·공유를 지표로 봅니다.
- 채널 예산은 6:4(메타:네이버)에서 시작하고, 7일 후 ROAS 기준으로 재배분합니다.

[소재 규칙]
1. 금지 표현(최고급·완판·1위·완벽·보장)은 소재에도 쓰지 않습니다. 검수 기준과 동일합니다.
2. 가격을 쓸 때는 실제 판매가만 씁니다. '최저가' 같은 비교 표현 금지.
3. 핏·마감·코디라는 실제 상품 사실에 근거해 씁니다. 없는 기능성(방수·발열) 금지.
4. 타겟을 비하하거나 외모를 평가하는 표현(예: '돼지', '루저') 금지.

[측정]
- GA4 + 메타 픽셀 + 네이버 프리미엄 로그분석. UTM은 SKU 단위.
- 일 ROAS가 손익분기 아래로 3일 연속이면 소재 교체 또는 중단을 제안합니다.

[도구]
{tool_manifest(TEAM_NAME)}

[출력]
MarketingPlan JSON만 출력합니다.
{{
  "budget_total": 0,
  "channels": [{{"channel": "meta|naver|instagram_organic", "objective": "", "budget": 0,
                "target_audience": "", "creative_notes": "", "expected_roas": 0.0}}],
  "schedule": ["D-1: ...", "D+0: ..."],
  "kpi": {{"CTR": 1.2, "CVR": 2.5, "ROAS": 3.0, "CPA": 0}},
  "tracking_notes": ["..."]
}}"""

USER_TEMPLATE = """[상품]
$name / $category / 판매가: $price원 / 순이익률: $margin
타겟: $target_customer / 시즌: $season

[배포 상태]
$deploy_note

[콘텐츠]
제목: $seo_title

[도구 계산 결과]
$budget_line
$roas_line
$meta_line
$naver_line
$target_line

[요청]
1) 14일 예산과 채널 배분 (손익분기 ROAS 근거 포함)
2) 채널별 타겟·소재·목표 ROAS
3) D-1~D+14 집행 일정과 중단/증액 기준
4) KPI와 추적 설정
MarketingPlan JSON으로만 답하세요."""

PROMPT = register_prompt(
    PromptBundle(
        team=TEAM_NAME,
        role="마케팅(퍼포먼스)",
        system=SYSTEM_PROMPT,
        user_template=USER_TEMPLATE,
        output_contract="MarketingPlan JSON (budget_total, channels[], schedule[], kpi{}, tracking_notes[])",
    )
)


def _daily_budget(price: int) -> int:
    return max(30_000, min(150_000, int(price * 1.5 / 1000) * 1000))


def _plan_inputs(product: ProductItem, md: MDPlan | None) -> dict[str, Any]:
    price = md.pricing.selling_price if md else (product.selling_price or 0)
    margin = md.pricing.margin_rate if md else 0.0
    daily = _daily_budget(price)
    split = budget_split(daily_budget=daily, weights={"meta": 0.6, "naver": 0.4})
    roas = roas_break_even(margin_rate=margin or 0.3, aov=price or 50_000, daily_budget=daily)
    meta_hooks = ad_hooks(
        channel="meta",
        name=product.name,
        category=product.category,
        price=price,
        keywords=product.keywords,
        fit=product.fit,
    )
    naver_hooks = ad_hooks(
        channel="naver",
        name=product.name,
        category=product.category,
        price=price,
        keywords=product.keywords,
        fit=product.fit,
    )
    meta_target = targeting(channel="meta", category=product.category, price=price)
    naver_target = targeting(channel="naver", category=product.category, price=price)
    return {
        "price": price,
        "margin": margin,
        "daily": daily,
        "split": split,
        "roas": roas,
        "meta_hooks": meta_hooks,
        "naver_hooks": naver_hooks,
        "meta_target": meta_target,
        "naver_target": naver_target,
    }


def build_prompt(product: ProductItem, plan: MDPlan | None = None) -> str:
    md = plan or None
    ctx = _plan_inputs(product, md)
    roas = ctx["roas"]
    deploy_note = "배포 전 — 시뮬레이션/등록 대기"
    return PROMPT.render(
        name=product.name,
        category=product.category,
        price=f"{ctx['price']:,}" if ctx["price"] else "미정",
        margin=f"{ctx['margin']:.1%}" if ctx["margin"] else "미정",
        target_customer=md.target_customer if md else "20~30대 남성",
        season=md.season if md else "미정",
        deploy_note=deploy_note,
        hook=md.trend_summary[:80] if md else "",
        seo_title=product.name,
        budget_line=f"- 일 예산 {ctx['daily']:,}원 → {ctx['split'].allocations} (14일 {ctx['daily'] * 14:,}원)",
        roas_line=(
            f"- 손익분기 ROAS {roas.be_roas} / 목표 {roas.target_roas} / "
            f"최대 CPA {roas.max_cpa:,}원 / 일 손익분기 {roas.break_even_orders_per_day}건"
        ),
        meta_line="- 메타 훅: " + " | ".join(f"{h.angle}→{h.headline}" for h in ctx["meta_hooks"].hooks),
        naver_line="- 네이버 훅: " + " | ".join(f"{h.angle}→{h.headline}" for h in ctx["naver_hooks"].hooks),
        target_line="- 타겟: " + " / ".join(f"{s.name}({s.definition})" for s in ctx["meta_target"].segments[:3]),
    )


def build_messages(product: ProductItem, plan: MDPlan | None = None) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": PROMPT.system},
        {"role": "user", "content": build_prompt(product, plan)},
    ]


def run(state: MallWorkflowState) -> dict[str, Any]:
    product = ProductItem.model_validate(state["product"])
    md: MDPlan | None = state.get("md_plan")
    ctx = _plan_inputs(product, md)
    roas = ctx["roas"]
    deployed_raw = state.get("dev_deployed")
    deployed = DevDeployment.model_validate(deployed_raw) if deployed_raw else None

    daily, split = ctx["daily"], ctx["split"]
    meta_budget = split.allocations.get("meta", 0)
    naver_budget = split.allocations.get("naver", 0)
    leaf = product.category.split(">")[-1].strip()
    meta_target = ctx["meta_target"]
    naver_keywords = ", ".join(s.definition.split(": ")[-1] for s in ctx["naver_target"].segments[:2])
    meta_notes = " / ".join(f"{h.headline}: {h.primary_text}" for h in ctx["meta_hooks"].hooks[:2])
    naver_notes = " / ".join(f"{h.headline}" for h in ctx["naver_hooks"].hooks[:2])

    channels = [
        CampaignChannel(
            channel="meta",
            objective="전환(구매)",
            budget=meta_budget,
            target_audience=meta_target.segments[0].definition + f" · 유사타겟 {meta_target.segments[1].bid_hint}",
            creative_notes=f"릴스 9:16 세로 3종 — {meta_notes}. 첫 3초 전신 핏, 자막 필수",
            expected_roas=roas.target_roas,
        ),
        CampaignChannel(
            channel="naver",
            objective="파워링크 + 쇼핑검색",
            budget=naver_budget,
            target_audience=f"검색 키워드: 남자 {leaf}, {leaf} 코디, 남성 데일리룩 · {naver_keywords}",
            creative_notes=f"상품명 앞 15자에 핵심 키워드, 썸네일 1:1 클린 배경 — {naver_notes}",
            expected_roas=round(roas.target_roas * 1.15, 2),
        ),
        CampaignChannel(
            channel="instagram_organic",
            objective="도달·저장",
            budget=0,
            target_audience=ctx["meta_target"].segments[0].definition + " · 기존 팔로워",
            creative_notes="룩북 3컷 캐러셀 + 릴스 재업로드, 저장 유도 CTA",
            expected_roas=0.0,
        ),
    ]

    plan = MarketingPlan(
        budget_total=daily * 14,
        channels=channels,
        schedule=[
            "D-1: 픽셀/전환 스크립트 설치 확인, UTM 링크 생성(SKU 단위)",
            f"D+0: 메타·네이버 소재 업로드, 일 예산 {daily:,}원의 70%로 시작",
            f"D+3: CTR 1% 미만 소재 교체, ROAS {roas.be_roas} 미만 키워드 입찰가 하향",
            f"D+7: ROAS {roas.target_roas} 이상 소재에 예산 재배분",
            f"D+14: ROAS 리포트 → 리오더/중단 판단 (손익분기 {roas.be_roas} 기준)",
        ],
        kpi={
            "CTR": 1.2,
            "CVR": 2.5,
            "ROAS": roas.target_roas,
            "BE_ROAS": roas.be_roas,
            "CPA": float(roas.target_cpa),
        },
        tracking_notes=[
            "GA4 + 메타 픽셀 + 네이버 프리미엄 로그분석 연동",
            "UTM: utm_source / utm_medium / utm_campaign=sku 단위",
            f"일 ROAS가 {roas.be_roas} 아래로 3일 연속이면 소재 교체·중단 제안",
            "광고비 증액은 승인 필요 (ApprovalKind.AD_SPEND)",
            *split.notes,
        ],
    )

    if deployed and deployed.simulated:
        deploy_note = "시뮬레이션 등록 — 실서버 반영 전 소재만 준비"
    elif deployed and deployed.deployed:
        deploy_note = f"배포 URL 연결: {deployed.product_url or deployed.mall_product_id}"
    else:
        deploy_note = "배포 전 소재 준비"

    return {
        "marketing_plan": plan,
        "status": WorkflowStatus.COMPLETED,
        "log": [
            f"[marketing] 채널 {len(channels)}개 / 14일 예산 {plan.budget_total:,}원 "
            f"/ 손익분기 ROAS {roas.be_roas} · 목표 {roas.target_roas} (최대 CPA {roas.max_cpa:,}원) — {deploy_note}"
        ],
    }
