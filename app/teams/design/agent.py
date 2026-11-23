"""디자인팀 — 모바일 우선 상세페이지 구조, 에셋 규격, 룩북 이미지 프롬프트.

산출물은 파일이 아니라 '규격서(spec)'입니다. 상세페이지 섹션 순서와 각 컷의 촬영 지시,
썸네일·배너·룩북의 픽셀 규격, 이미지 생성용 영문 프롬프트까지를 한 번에 남겨
외주 디자이너나 이미지 생성 API가 그대로 집어갈 수 있게 합니다.

표준 규격(카페24/아임웹 공통):
- 상세페이지 본문 860px (모바일 720px 대응)
- 썸네일 1000×1000 (1:1)
- 메인 배너 1920×600
- 룩북 1200×1600 (3:4)
"""

from __future__ import annotations

from typing import Any

from app.orchestrator.state import MallWorkflowState
from app.shared.models import (
    DesignAsset,
    DesignPlan,
    LayoutSection,
    MDPlan,
    ProductItem,
    TeamName,
    WorkflowStatus,
)
from app.shared.prompting import PromptBundle, register_prompt
from app.shared.tooling import tool_manifest
from app.teams.design.tools import TOOLS, asset_spec, detail_blueprint, image_prompt, palette

TEAM = "design"
TEAM_NAME = TeamName.DESIGN
__all__ = ["TEAM", "SYSTEM_PROMPT", "USER_TEMPLATE", "PROMPT", "TOOLS", "build_prompt", "build_messages", "run"]

SYSTEM_PROMPT = f"""당신은 한국 남성 보세몰의 아트디렉터입니다.
MD가 확정한 상품과 가격을 받아, 모바일에서 3초 만에 핏이 보이고 스크롤이 끊기지 않는
상세페이지 구조와 이미지 규격을 설계합니다. 결과물은 외주 디자이너·이미지 생성 API가
그대로 실행할 수 있는 수준의 지시서여야 합니다.

[상세페이지 순서 — 반드시 지킵니다]
1) 후킹 인트로: 전신 착장 + 핏 한 줄. 첫 화면에서 어깨선이 보이지 않으면 실패입니다.
2) 룩북/히어로: 컬러별 전신컷. 시즌 무드 전달.
3) 핏 포인트: 어깨 드롭·암홀·총장을 가이드선으로 설명.
4) 디테일 컷: 봉제·포켓·지퍼·밑단 접사. '가격이 납득되는' 구간입니다.
5) 소재/촉감: 원단 매크로 + 늘어남·구김 테스트.
6) 스펙/사이즈표: 실측 표(어깨·가슴·총장·소매)와 모델 착용 기준.
7) 코디 제안: 슬랙스·데님·트레이닝 3종.
8) 배송/교환/고시정보: 혼용률·제조국·세탁법은 이미지가 아니라 텍스트로.

[규격 원칙]
- 상세페이지는 860px 폭, 모바일 720px에서 잘리지 않게 텍스트 최소 14px.
- 썸네일 1000×1000, 배너 1920×600, 룩북 1200×1600. 규격을 임의로 바꾸지 않습니다.
- 이미지 1장당 300KB~1MB, 상세페이지는 10장 이하로 분할합니다.
- 텍스트는 이미지에 굽지 않습니다. 검색·번역·수정이 안 됩니다.

[이미지 프롬프트 원칙]
- 실사 같은 한국 남성 모델(20대 중후반), 자연스러운 피부 질감, 과한 보정 금지.
- 배경은 콘크리트 스튜디오/단색, 조명은 창 자연광. 네온·과채도 금지.
- 로고·워터마크·텍스트가 생성되지 않도록 네거티브 프롬프트를 반드시 함께 넣습니다.
- 얼굴이 과도하게 클로즈업된 컷은 의류 확인에 도움이 안 되므로 쓰지 않습니다.

[금지]
- 실제와 다른 색·소재로 보이게 하는 보정(색상 왜곡) 금지.
- '최고급', '완판', '1위' 같은 문구를 이미지에 넣지 않습니다(검수팀 반려 대상).
- 저작권 있는 타사 화보·연예인 이미지 모방 금지. 스타일 키워드만 참고합니다.
- 접근성 무시: 배경 대비 4.5:1 미만 텍스트 배치 금지.

[도구]
{tool_manifest(TEAM_NAME)}

[출력]
DesignPlan JSON 하나만 출력합니다.
{{
  "concept": "한 줄 컨셉",
  "mood_keywords": ["clean", "minimal", "editorial"],
  "palette": ["#111111", "#2B2B2B", "#E8E4DC", "#B08D57"],
  "layout_sections": [{{"order": 1, "section": "", "headline": "", "visual": "", "copy_points": []}}],
  "assets": [{{"kind": "detail_page|thumbnail|banner|lookbook", "name": "", "width": 0,
              "height": 0, "format": "jpg", "spec": {{}}}}],
  "image_prompt": "영문 이미지 생성 프롬프트",
  "notes": ["제작·검수 시 유의사항"]
}}"""

USER_TEMPLATE = """[상품]
$name / $category / 핏: $fit / 소재: $material / 색상: $colors / 판매가: $price원

[MD 기획 요약]
$trend_summary
타겟: $target_customer

[도구 계산 결과]
$palette_line
$section_line
$asset_line
$prompt_line

[요청]
1) 이 상품의 상세페이지 컨셉과 무드 키워드
2) 위 8개 섹션을 그대로 쓰되, 헤드라인과 촬영 지시를 이 상품에 맞게 다듬기
3) 4종 에셋 규격과 룩북/썸네일 이미지 프롬프트
4) 제작·검수 시 유의사항(모바일 가독성, 색상 왜곡 금지 등)
DesignPlan JSON으로만 답하세요."""

PROMPT = register_prompt(
    PromptBundle(
        team=TEAM_NAME,
        role="디자인(아트디렉터)",
        system=SYSTEM_PROMPT,
        user_template=USER_TEMPLATE,
        output_contract=(
            "DesignPlan JSON (concept, mood_keywords, palette, layout_sections, assets, image_prompt, notes)"
        ),
    )
)


def _render_sections(product: ProductItem, md: MDPlan | None) -> tuple[Any, list[LayoutSection], dict[str, str]]:
    price = md.pricing.selling_price if md else (product.selling_price or 0)
    blueprint = detail_blueprint(
        name=product.name,
        category=product.category,
        fit=product.fit,
        material=product.material,
        colors=product.color_options,
        price=price,
        selling_points=list(product.keywords[:3]),
    )
    sections = [
        LayoutSection(
            order=spec.order,
            section=spec.section,
            headline=spec.headline,
            visual=f"{spec.visual} (모바일 {spec.height_px}px · {spec.mobile_note})",
            copy_points=spec.copy_points,
        )
        for spec in blueprint.sections
    ]
    lines = {
        "section_line": " / ".join(f"{s.section}({s.height_px}px)" for s in blueprint.sections),
        "total_height": f"{blueprint.total_height_px:,}",
    }
    return blueprint, sections, lines


def _build_prompt_values(product: ProductItem, md: MDPlan | None) -> dict[str, str]:
    blueprint, _, lines = _render_sections(product, md)
    pal = palette(name=product.name, category=product.category, colors=product.color_options)
    look = image_prompt(
        kind="lookbook",
        category=product.category,
        fit=product.fit,
        material=product.material,
        colors=product.color_options,
        palette=pal.colors,
        mood=pal.mood,
    )
    thumb = image_prompt(
        kind="thumbnail",
        category=product.category,
        fit=product.fit,
        material=product.material,
        colors=product.color_options,
        palette=pal.colors,
        mood=pal.mood,
    )
    specs = " / ".join(
        f"{k} {asset_spec(kind=k).width}×{asset_spec(kind=k).height}"
        for k in ("detail_page", "thumbnail", "banner", "lookbook")
    )
    price = md.pricing.selling_price if md else (product.selling_price or 0)
    return {
        "name": product.name,
        "category": product.category,
        "fit": product.fit,
        "material": product.material or "미기재",
        "colors": ", ".join(product.color_options) or "미기재",
        "price": f"{price:,}" if price else "미정",
        "trend_summary": md.trend_summary if md else "MD 기획안 없음",
        "target_customer": md.target_customer if md else "20~30대 남성",
        "palette_line": (
            f"- 팔레트 {', '.join(pal.colors)} (배경 {pal.background}, "
            f"텍스트 {pal.text_on_background}, 대비 {pal.contrast_ratio}:1)"
        ),
        "section_line": (
            f"- 섹션 {len(blueprint.sections)}개: {lines['section_line']} "
            f"(모바일 총 {lines['total_height']}px)"
        ),
        "asset_line": f"- 규격: {specs}",
        "prompt_line": (
            f"- 룩북 프롬프트: {look.prompt} / 네거티브: {look.negative_prompt} / "
            f"썸네일: {thumb.usage_note}"
        ),
    }


def build_prompt(product: ProductItem, plan: MDPlan | None = None) -> str:
    return PROMPT.render(**_build_prompt_values(product, plan))


def build_messages(product: ProductItem, plan: MDPlan | None = None) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": PROMPT.system},
        {"role": "user", "content": build_prompt(product, plan)},
    ]


def run(state: MallWorkflowState) -> dict[str, Any]:
    product = ProductItem.model_validate(state["product"])
    md: MDPlan | None = state.get("md_plan")

    blueprint, sections, _ = _render_sections(product, md)
    pal = palette(name=product.name, category=product.category, colors=product.color_options)

    look = image_prompt(
        kind="lookbook", category=product.category, fit=product.fit, material=product.material,
        colors=product.color_options, palette=pal.colors, mood=pal.mood,
    )
    thumb = image_prompt(
        kind="thumbnail", category=product.category, fit=product.fit, material=product.material,
        colors=product.color_options, palette=pal.colors, mood=pal.mood,
    )
    detail = image_prompt(
        kind="detail_cut", category=product.category, fit=product.fit, material=product.material,
        colors=product.color_options, palette=pal.colors, mood=pal.mood,
    )
    detail_spec = asset_spec(kind="detail_page")
    thumb_spec = asset_spec(kind="thumbnail")
    banner_spec = asset_spec(kind="banner")
    look_spec = asset_spec(kind="lookbook")

    assets = [
        DesignAsset(
            kind="detail_page",
            name=f"{product.sku}_detail",
            width=detail_spec.width,
            height=max(detail_spec.height, blueprint.total_height_px),
            format="jpg",
            spec={
                "sections": [s.section for s in sections],
                "mobile_width": blueprint.mobile_width_px,
                "desktop_width": blueprint.desktop_width_px,
                "max_file_mb": round(detail_spec.max_kb / 1000, 1),
                "scroll_hooks": blueprint.scroll_hooks,
                "text_rendering": "HTML 텍스트 (이미지 굽기 금지)",
            },
        ),
        DesignAsset(
            kind="thumbnail",
            name=f"{product.sku}_thumb",
            width=thumb_spec.width,
            height=thumb_spec.height,
            format="jpg",
            spec={
                "background": pal.background,
                "headline_area": thumb_spec.safe_area,
                "contrast_ratio": pal.contrast_ratio,
                "badge": ["신상", "무료배송"],
                "prompt": thumb.prompt,
                "negative_prompt": thumb.negative_prompt,
            },
        ),
        DesignAsset(
            kind="banner",
            name=f"{product.sku}_banner",
            width=banner_spec.width,
            height=banner_spec.height,
            format="jpg",
            spec={
                "text_safe_area": banner_spec.safe_area,
                "cta": "신상 특가 보기",
                "mobile_crop": "750×400 중앙 크롭",
            },
        ),
        DesignAsset(
            kind="lookbook",
            name=f"{product.sku}_lookbook",
            width=look_spec.width,
            height=look_spec.height,
            format="jpg",
            spec={
                "count": 3,
                "ratio": look_spec.ratio,
                "max_kb": look_spec.max_kb,
                "prompt": look.prompt,
                "negative_prompt": look.negative_prompt,
                "detail_prompt": detail.prompt,
            },
        ),
    ]

    notes = [
        "상세페이지 최상단 3초 안에 핏 실루엣이 보이도록 룩북컷 배치",
        f"모바일 폭 {blueprint.mobile_width_px}px 기준 텍스트 14px 이상, 총 길이 {blueprint.total_height_px:,}px",
        f"배경 대비 {pal.contrast_ratio}:1 — "
        f"{'접근성 기준 충족' if pal.accessible else '4.5:1 미달, 텍스트색 조정 필요'}",
        "텍스트는 이미지에 굽지 말고 HTML 텍스트로 올려 SEO·번역 대응",
        "이미지 1장당 1MB 이하로 분할, 상세페이지 10장 이하",
        "상품 컬러와 다른 색감 보정 금지 — 반품·클레임 사유가 됩니다",
    ]
    if md:
        notes.append(md.trend_summary[:80])

    plan = DesignPlan(
        concept=f"{pal.mood} · {product.fit} 실루엣 강조 · {pal.background} 배경",
        mood_keywords=["clean", "minimal", "editorial", "muted", product.fit],
        palette=pal.colors,
        layout_sections=sections,
        assets=assets,
        image_prompt=look.prompt,
        notes=notes,
    )

    return {
        "design_assets": plan,
        "status": WorkflowStatus.RUNNING,
        "log": [
            f"[design] 레이아웃 {len(sections)}개 섹션 / 에셋 {len(assets)}종 규격 확정 "
            f"(모바일 {blueprint.mobile_width_px}px, 대비 {pal.contrast_ratio}:1)"
        ],
    }
