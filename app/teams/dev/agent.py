"""개발팀 — 쇼핑몰 상품 등록, 옵션 조합, 재고 동기화·임계 알림.

승인(interrupt) 이후에만 호출됩니다. 실제 배포는 `MallAdapter` 구현체가 담당하고,
이 팀은 (1) 승인된 가격/카피/에셋으로 플랫폼별 payload를 만들고 (2) 컬러×사이즈 옵션과
재고를 정리하고 (3) 등록 결과와 재고 동기화 상태를 남깁니다.

로컬 개발(.env에 MALL_API_KEY 없음, APP_ENV!=prod)에서는 실제 호출 대신
시뮬레이션 등록으로 전체 흐름을 끝까지 돌려볼 수 있습니다.
`DevDeployment.simulated=True`로 표시되므로 실제 배포와 구분됩니다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.integrations.mall_adapter import MallCredentialsMissing, MallIntegrationError, get_adapter
from app.orchestrator.state import MallWorkflowState
from app.shared.config import get_settings
from app.shared.models import (
    ContentCopy,
    DesignPlan,
    DevDeployment,
    MDPlan,
    ProductItem,
    TeamName,
    WorkflowStatus,
)
from app.shared.prompting import PromptBundle, register_prompt
from app.shared.tooling import tool_manifest
from app.teams.dev.tools import TOOLS, option_matrix, product_payload, stock_alert

TEAM = "dev"
TEAM_NAME = TeamName.DEV
__all__ = ["TEAM", "SYSTEM_PROMPT", "USER_TEMPLATE", "PROMPT", "TOOLS", "build_prompt", "build_messages", "run"]

SYSTEM_PROMPT = f"""당신은 한국 남성 보세몰의 개발(운영 자동화) 담당입니다.
대표님이 승인한 상품만 몰에 등록하고, 옵션·재고·가격이 승인 내용과 1원도 다르지 않게 유지합니다.
등록은 되돌리기 어려운 작업이므로 '확인 → 변환 → 검증 → 실행 → 기록' 순서를 지킵니다.

[등록 payload 규칙]
1. 판매가는 승인된 값(정수, 원)만 씁니다. 임의 할인·반올림·수수료 가산 금지.
2. 옵션 코드는 SKU-순번 형식으로 유일하게 만들고, 컬러·사이즈 조합이 중복되지 않게 합니다.
3. 재고 0 조합은 '품절'로 표시하거나 옵션에서 숨깁니다. 0장을 판매 가능으로 두지 않습니다.
4. 이미지 순서는 썸네일 → 상세 → 룩북. file_url이 없는 에셋은 payload에 넣지 않습니다.
5. 상품명은 콘텐츠팀 SEO 제목을 그대로 쓰고, 메타 설명·해시태그를 함께 넘깁니다.
6. 플랫폼별 키 이름 차이는 도구가 흡수합니다(cafe24/imweb/custom). 필수값 누락이 있으면 등록하지 않습니다.

[재고 규칙]
1. 재고 동기화는 등록 직후 1회, 이후 주문 웹훅마다 갱신합니다.
2. 임계치(기본 5장) 이하 또는 소진일수가 리드타임 이하이면 critical 알림을 대표님께 보냅니다.
3. 재고 0장은 품절 처리 후 긴급 사입 요청. 자동으로 수량을 늘리지 않습니다.

[금지]
- 승인되지 않은 가격·옵션·이미지 변경. 승인 후 수정이 필요하면 워크플로를 다시 돌립니다.
- API 키·토큰을 로그·응답·payload에 남기는 행위.
- 실패를 숨기고 성공으로 보고하는 행위. 실패는 errors에 그대로 남깁니다.
- 운영(APP_ENV=prod)에서 자격증명 없이 시뮬레이션으로 넘어가는 행위.

[도구]
{tool_manifest(TEAM_NAME)}

[출력]
등록 결과 요약 JSON만 출력합니다.
{{
  "platform": "custom",
  "mall_product_id": "",
  "product_url": null,
  "options": {{"active": 0, "disabled": 0, "total_stock": 0}},
  "inventory_synced": true,
  "stock_alert": {{"level": "ok", "action": ""}},
  "errors": []
}}"""

USER_TEMPLATE = """[승인된 상품]
SKU: $sku / 상품명: $name / 카테고리: $category
판매가: $price원 / 공급가: $cost원 / 재고: $stock장
색상: $colors / 사이즈: $sizes
플랫폼: $platform / 환경: $env

[콘텐츠]
제목: $seo_title
메타: $meta_description
해시태그: $hashtags

[디자인]
에셋: $assets
이미지 URL 있음: $images

[도구 결과]
$option_line
$payload_line
$alert_line

[요청]
1) 위 payload로 몰 등록 (승인 범위 밖 변경 금지)
2) 등록 결과 ID·URL, 재고 동기화 여부
3) 재고 임계 알림 단계와 조치
4) 실패 시 원인과 재시도 가능 여부
출력 스키마 JSON으로만 답하세요."""

PROMPT = register_prompt(
    PromptBundle(
        team=TEAM_NAME,
        role="개발(몰 등록·재고)",
        system=SYSTEM_PROMPT,
        user_template=USER_TEMPLATE,
        output_contract=(
            "등록 결과 JSON (platform, mall_product_id, product_url, options, "
            "inventory_synced, stock_alert, errors)"
        ),
    )
)


def _registers(product: ProductItem, copy: ContentCopy | None, design: DesignPlan | None, price: int) -> dict[str, Any]:
    """payload·옵션·재고 알림을 한 번에 계산한다(프롬프트와 실행이 같은 값을 사용)."""
    settings = get_settings()
    options = option_matrix(
        sku=product.sku,
        colors=product.color_options or ["단일색"],
        sizes=product.size_options or ["M", "L", "XL"],
        stock=product.stock,
        extra_price={"2XL": 2000} if "2XL" in (product.size_options or []) else {},
    )
    images = [a.file_url for a in design.assets if a.file_url] if design else []
    payload = product_payload(
        platform=settings.mall_platform,
        sku=product.sku,
        name=(copy.seo_title if copy else product.name),
        price=price,
        stock=product.stock,
        category=product.category,
        description="\n\n".join(
            filter(
                None,
                [
                    copy.hook if copy else "",
                    copy.fit_copy if copy else "",
                    copy.material_copy if copy else "",
                    copy.coordi_copy if copy else "",
                    copy.size_guide_copy if copy else "",
                    copy.care_copy if copy else "",
                ],
            )
        ),
        meta_description=copy.meta_description if copy else "",
        hashtags=copy.hashtags if copy else [],
        images=images,
        options=options.options,
        tags=product.keywords,
    )
    alert = stock_alert(sku=product.sku, stock=product.stock, threshold=5, daily_sales=0, lead_time_days=3)
    return {"options": options, "payload": payload, "alert": alert, "settings": settings}


def _lines(ctx: dict[str, Any]) -> dict[str, str]:
    options, payload, alert = ctx["options"], ctx["payload"], ctx["alert"]
    return {
        "option_line": (
            f"- 옵션: 활성 {options.active_count}개 / 비활성 {options.disabled_count}개 / "
            f"총 재고 {options.total_stock}장"
            + (f" · 주의: {'; '.join(options.notes)}" if options.notes else "")
        ),
        "payload_line": (
            f"- payload({payload.platform}): 필수값 누락 "
            f"{payload.missing_required or '없음'} / 메모 {payload.notes or '없음'}"
        ),
        "alert_line": f"- 재고 알림: {alert.level} / {alert.message} / 조치 {alert.action}",
    }


def build_prompt(
    product: ProductItem,
    price: int,
    copy: ContentCopy | None = None,
    design: DesignPlan | None = None,
) -> str:
    ctx = _registers(product, copy, design, price)
    settings = ctx["settings"]
    return PROMPT.render(
        sku=product.sku,
        name=product.name,
        category=product.category,
        price=f"{price:,}",
        cost=f"{product.cost_price:,}",
        stock=product.stock,
        colors=", ".join(product.color_options),
        sizes="/".join(product.size_options),
        platform=settings.mall_platform,
        env=settings.app_env,
        seo_title=copy.seo_title if copy else product.name,
        meta_description=copy.meta_description if copy else "",
        hashtags=" ".join(copy.hashtags) if copy else "",
        assets=", ".join(f"{a.kind}({a.width}×{a.height})" for a in design.assets) if design else "없음",
        images=bool([a for a in design.assets if a.file_url]) if design else False,
        **_lines(ctx),
    )


def build_messages(
    product: ProductItem,
    price: int,
    copy: ContentCopy | None = None,
    design: DesignPlan | None = None,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": PROMPT.system},
        {"role": "user", "content": build_prompt(product, price, copy, design)},
    ]


def _simulate(product: ProductItem, reason: str) -> DevDeployment:
    """API 키가 없을 때의 로컬 시뮬레이션. 실서버에는 아무 것도 만들지 않는다."""
    return DevDeployment(
        deployed=False,
        simulated=True,
        platform=get_settings().mall_platform,
        mall_product_id=None,
        product_url=None,
        inventory_synced=False,
        errors=[reason],
        deployed_at=datetime.now(UTC),
    )


async def run(state: MallWorkflowState) -> dict[str, Any]:
    product = ProductItem.model_validate(state["product"])
    md: MDPlan | None = state.get("md_plan")
    copy: ContentCopy | None = state.get("content_copy")
    design: DesignPlan | None = state.get("design_assets")
    settings = get_settings()

    if md is None or copy is None or design is None:
        return {
            "dev_deployed": DevDeployment(
                deployed=False,
                platform=settings.mall_platform,
                errors=["MD/콘텐츠/디자인 산출물이 없어 배포할 수 없습니다"],
            ),
            "status": WorkflowStatus.DEPLOY_FAILED,
            "log": ["[dev] 배포 중단 — 선행 산출물 누락"],
        }

    price = md.pricing.selling_price
    ctx = _registers(product, copy, design, price)
    payload = ctx["payload"]
    alert = ctx["alert"]
    options = ctx["options"]
    log_prefix = [
        (
            f"[dev] 옵션 {options.active_count}개 활성 / 비활성 {options.disabled_count}개 / "
            f"payload 필수값 누락 {len(payload.missing_required)}건"
        ),
        f"[dev] 재고 알림 {alert.level} — {alert.action}",
    ]
    if payload.missing_required:
        return {
            "dev_deployed": DevDeployment(
                deployed=False,
                platform=settings.mall_platform,
                errors=[f"필수값 누락으로 등록 중단: {', '.join(payload.missing_required)}"],
            ),
            "status": WorkflowStatus.DEPLOY_FAILED,
            "log": [*log_prefix, "[dev] 배포 실패 — payload 필수값 누락"],
        }

    adapter = get_adapter(settings)
    try:
        ref = await adapter.register_product(product, copy, design, price)
        inventory_synced = True
        try:
            await adapter.update_inventory(product.sku, product.stock)
        except (MallIntegrationError, MallCredentialsMissing) as exc:
            inventory_synced = False
            errors = [f"재고 동기화 실패: {exc}"]
        else:
            errors = []
        return {
            "dev_deployed": DevDeployment(
                deployed=True,
                platform=ref.platform,
                mall_product_id=ref.mall_product_id,
                product_url=ref.product_url,
                inventory_synced=inventory_synced,
                errors=errors,
                deployed_at=datetime.now(UTC),
            ),
            "status": WorkflowStatus.COMPLETED,
            "log": [
                *log_prefix,
                f"[dev] 상품 등록 완료 — {ref.platform} / ID {ref.mall_product_id} / 재고 동기화 {inventory_synced}",
            ],
        }

    except MallCredentialsMissing as exc:
        if settings.is_production:
            return {
                "dev_deployed": DevDeployment(
                    deployed=False,
                    platform=settings.mall_platform,
                    errors=[f"운영 환경인데 몰 API 키가 없습니다: {exc}"],
                ),
                "status": WorkflowStatus.DEPLOY_FAILED,
                "log": [*log_prefix, "[dev] 배포 실패 — 운영 환경 자격증명 누락"],
            }
        dep = _simulate(product, f"로컬 시뮬레이션 ({exc})")
        return {
            "dev_deployed": dep,
            "status": WorkflowStatus.COMPLETED,
            "log": [
                *log_prefix,
                f"[dev] 시뮬레이션 등록 완료 — SKU {product.sku} / 판매가 {price:,}원 (실서버 반영 없음)",
            ],
        }

    except MallIntegrationError as exc:
        return {
            "dev_deployed": DevDeployment(
                deployed=False,
                platform=settings.mall_platform,
                errors=[str(exc)],
            ),
            "status": WorkflowStatus.DEPLOY_FAILED,
            "log": [*log_prefix, f"[dev] 배포 실패 — {exc}"],
        }
