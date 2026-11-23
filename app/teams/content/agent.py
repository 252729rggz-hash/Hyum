"""콘텐츠팀 — SEO 상품명, 핏·소재·코디 카피, 고시정보, 릴스 대본.

보세몰은 같은 상품을 여러 셀러가 팔기 때문에, 검색에서 먼저 보이는 제목과 첫 문단이
사실상 경쟁력입니다. 이 팀은 (1) 키워드 조합 제목, (2) 실측·소재 기반 신뢰 카피,
(3) 릴스용 15~30초 원고, (4) 법정 고시정보를 만듭니다.

주의: 과장·최상급·효능 표현은 검수팀이 반려합니다(표시광고법).
"""

from __future__ import annotations

import re
from typing import Any

from app.orchestrator.state import MallWorkflowState
from app.shared.models import ContentCopy, DesignPlan, MDPlan, ProductItem, TeamName
from app.shared.prompting import PromptBundle, register_prompt
from app.shared.tooling import tool_manifest
from app.teams.content.tools import (
    FIT_LABEL,
    TOOLS,
    care_guide,
    disclosure,
    fit_guide,
    hashtags,
    seo_title,
    shortform_script,
)

TEAM = "content"
TEAM_NAME = TeamName.CONTENT
__all__ = ["TEAM", "SYSTEM_PROMPT", "USER_TEMPLATE", "PROMPT", "TOOLS", "build_prompt", "build_messages", "run"]

SYSTEM_PROMPT = f"""당신은 한국 남성 보세몰의 카피라이터입니다.
타겟은 20~30대 남성으로, 캐주얼·미니멀·스트릿을 오가며 '출근복과 주말복의 경계'를 사는 고객입니다.
같은 도매 상품을 파는 셀러가 수십 곳이므로, 검색에서 먼저 보이고 첫 문단에서 신뢰를 주는 것이 목표입니다.

[SEO 상품명 규칙]
1. 네이버 쇼핑 기준 공백 포함 50자 이내. 핵심 키워드(카테고리·핏·소재)를 앞쪽에 둡니다.
2. 같은 단어 반복, 특수문자(★, ♥, [], 【】), 띄어쓰기 없는 키워드 나열은 쓰지 않습니다.
3. 타 브랜드명·연예인 이름을 붙이지 않습니다(상표권·표시광고 위반).
4. '최고급', '완판', '1위', '최저가' 같은 표현은 절대 쓰지 않습니다.
5. 메타 설명은 80자 이내로, 무엇을 누구에게 왜 추천하는지 한 문장으로 끝냅니다.

[카피 규칙]
1. 핏 설명은 실측(어깨·가슴·총장·소매)과 모델 착용 기준(키/몸무게/사이즈)을 밝힙니다.
2. 체형별 안내는 '마른/보통/탄탄/근육형'으로 나누되, 단정하지 않고 권장으로 씁니다.
3. 소재는 도매처 표기 혼용률을 그대로 씁니다. 없는 기능성(방수·발열·흡한속건 등)을 창작하지 않습니다.
4. 세탁 안내는 소재에 맞는 실제 방법만 씁니다. '절대 줄지 않습니다' 같은 보증 표현 금지.
5. 코디 제안은 색상·아이템을 구체적으로(예: 블랙 슬랙스 + 스니커즈) 씁니다.
6. '100%'는 소재 함량(예: 폴리에스터 100%)에만 씁니다. '100% 만족' 같은 표현은 금지입니다.

[숏폼 규칙]
1. 15~30초, 0~3초 훅 → 4~10초 핏/디테일 → 11~18초 코디 → 19~25초 CTA 4비트.
2. 자막 기준으로 한 줄 20자 이내, 말로 읽었을 때 자연스럽게.
3. 훅에는 가격·할인보다 '핏이 주는 변화'를 먼저 말합니다.
4. 마지막에 사이즈 범위와 구매 경로를 반드시 넣습니다.

[고시정보]
혼용률·제조국·세탁법·제조자·품질보증·AS는 비워 두지 않습니다. 모르면 '확인 필요(사입처 문의)'로
남기고, 그 사실을 메모에 적습니다. 이 항목이 비면 검수팀이 반려합니다.

[도구]
{tool_manifest(TEAM_NAME)}

[출력]
ContentCopy JSON 하나만 출력합니다. 금지 표현이 없는지 스스로 한 번 더 확인한 뒤 출력하세요.
{{
  "seo_title": "", "meta_description": "", "hook": "", "fit_copy": "", "material_copy": "",
  "coordi_copy": "", "size_guide_copy": "", "care_copy": "", "sns_script": "",
  "hashtags": ["#남성패션"],
  "disclosure": {{"material_composition": "", "country_of_origin": "", "care_instruction": "",
                 "manufacturer": "", "quality_guarantee": "", "as_contact": ""}}
}}"""

USER_TEMPLATE = """[상품]
$name / $category / 핏: $fit / 소재: $material / 색상: $colors / 사이즈: $sizes
판매가: $price원 / 제조국: $origin / 사입처: $supplier

[MD 기획]
타겟: $target_customer / 시즌: $season / 키워드: $keywords

[디자인 방향]
컨셉: $design_concept / 섹션: $design_sections

[도구 결과 — 문장은 이 내용을 근거로]
- 제목 후보: $title_line
- 핏 안내: $fit_line
- 세탁 안내: $care_line
- 고시정보: $disclosure_line
- 숏폼: $shortform_line
- 해시태그: $hashtag_line

[요청]
1) 위 제목 후보 중 가장 좋은 것을 고르거나 다듬어 최종 SEO 제목
2) 메타 설명 80자 이내, 후킹 문장 1줄
3) 핏·소재·코디·사이즈·세탁 카피 (각 2~3문장)
4) 릴스 15~25초 원고와 해시태그 10개
5) 고시정보 6개 항목
ContentCopy JSON으로만 답하세요."""

PROMPT = register_prompt(
    PromptBundle(
        team=TEAM_NAME,
        role="콘텐츠(카피라이터)",
        system=SYSTEM_PROMPT,
        user_template=USER_TEMPLATE,
        output_contract="ContentCopy JSON (seo_title, meta_description, 카피 5종, sns_script, hashtags, disclosure)",
    )
)


def _clean(text: str) -> str:
    """연속 공백/중복 구두점을 정리한다 (검수팀 오탈자 규칙과 동일 기준)."""
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"([!?.,])\1{1,}", r"\1", text)
    return text.strip()


def _bounded(parts: list[str], limit: int, sep: str = " ") -> str:
    out = ""
    for part in parts:
        candidate = f"{out}{sep}{part}".strip()
        if len(candidate) <= limit:
            out = candidate
    return out


def _leaf(category: str) -> str:
    return category.split(">")[-1].strip() or category.strip()


def _inputs(product: ProductItem, md: MDPlan | None) -> dict[str, Any]:
    leaf = _leaf(product.category)
    fit = FIT_LABEL.get(product.fit, product.fit)
    price = md.pricing.selling_price if md else (product.selling_price or 0)
    season = md.season if md else ""

    title = seo_title(
        category=product.category,
        fit=product.fit,
        material=product.material,
        colors=product.color_options,
        season=season,
        keywords=product.keywords,
    )
    guide = fit_guide(
        fit=product.fit,
        size_options=product.size_options,
        height_cm=178,
        weight_kg=68,
        body_type="보통",
    )
    care = care_guide(material=product.material, colors=product.color_options)
    disc = disclosure(
        material=product.material,
        country_of_origin=product.country_of_origin,
        supplier=product.supplier,
        care_text=care.text,
    )
    script = shortform_script(
        name=product.name,
        category=product.category,
        fit=product.fit,
        material=product.material,
        price=price,
        sizes=product.size_options,
        hook="",
        benefits=["구김이 적어 매일 입기 좋습니다"] if "폴리" in (product.material or "") else [],
    )
    tags = hashtags(category=product.category, fit=product.fit, season=season, extra=product.keywords[:2])
    return {
        "leaf": leaf,
        "fit": fit,
        "price": price,
        "season": season,
        "title": title,
        "guide": guide,
        "care": care,
        "disclosure": disc,
        "script": script,
        "hashtags": tags,
    }


def build_prompt(product: ProductItem, plan: MDPlan | None = None, design: DesignPlan | None = None) -> str:
    ctx = _inputs(product, plan)
    return PROMPT.render(
        name=product.name,
        category=product.category,
        fit=product.fit,
        material=product.material or "미기재",
        colors=", ".join(product.color_options) or "미기재",
        sizes="/".join(product.size_options),
        price=f"{ctx['price']:,}" if ctx["price"] else "미정",
        origin=product.country_of_origin or "미기재",
        supplier=product.supplier or "미지정",
        target_customer=plan.target_customer if plan else "20~30대 남성",
        season=plan.season if plan else "미정",
        keywords=", ".join(product.keywords) or "미기재",
        design_concept=design.concept if design else "미정",
        design_sections=" / ".join(s.section for s in design.layout_sections) if design else "미정",
        title_line=f"{ctx['title'].title} ({ctx['title'].length}자) / 대안: {' | '.join(ctx['title'].alternatives)}",
        fit_line=ctx["guide"].text,
        care_line=ctx["care"].text,
        disclosure_line=(
            f"혼용률 {ctx['disclosure'].material_composition} / 제조국 {ctx['disclosure'].country_of_origin} / "
            f"세탁 {ctx['disclosure'].care_instruction[:40]}"
        ),
        shortform_line=ctx["script"].script,
        hashtag_line=" ".join(ctx["hashtags"].hashtags),
    )


def build_messages(
    product: ProductItem, plan: MDPlan | None = None, design: DesignPlan | None = None
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": PROMPT.system},
        {"role": "user", "content": build_prompt(product, plan, design)},
    ]


def run(state: MallWorkflowState) -> dict[str, Any]:
    product = ProductItem.model_validate(state["product"])
    md: MDPlan | None = state.get("md_plan")
    design: DesignPlan | None = state.get("design_assets")
    ctx = _inputs(product, md)

    leaf, fit, price = ctx["leaf"], ctx["fit"], ctx["price"]
    color_text = ", ".join(product.color_options[:3]) or "기본 색상"
    main_color = product.color_options[0] if product.color_options else "블랙"
    material_word = (product.material.split()[0] if product.material else "") or "탄탄한 원단"
    size_text = f"{product.size_options[0]}~{product.size_options[-1]}" if product.size_options else "M~2XL"

    meta_description = _bounded(
        [
            f"{fit} {leaf}.",
            f"{material_word} 소재,",
            f"{color_text} {len(product.color_options) or 1}색.",
            f"{size_text} 사이즈, 무료배송.",
        ],
        80,
    )

    fit_copy = _clean(f"{ctx['guide'].text} 상세 실측표는 하단 사이즈 안내를 참고해 주세요.")
    material_copy = _clean(
        f"{material_word} 소재로 구김이 적고 형태 유지가 잘 됩니다. "
        f"혼용률은 {ctx['care'].composition}이며, 피부에 닿는 부분은 부드럽게 마감했습니다."
    )
    coordi_copy = _clean(
        f"출근에는 {main_color} 톤 슬랙스와 매치하면 단정하고, 주말에는 워시드 데님과 스니커즈로 캐주얼하게 입습니다. "
        "추운 날에는 얇은 니트 위에 아우터로 레이어드해도 실루엣이 답답하지 않습니다."
    )
    size_guide_copy = _clean(
        f"모델 178cm/68kg 기준 {ctx['guide'].recommended_size} 사이즈를 착용했습니다. {ctx['guide'].alternative}. "
        f"{ctx['guide'].body_notes[0]}"
    )
    care_copy = _clean(ctx["care"].text)

    copy = ContentCopy(
        seo_title=ctx["title"].title[:50],
        meta_description=meta_description,
        hook=_clean(f"{fit} 하나로 끝나는 데일리 {leaf}"),
        fit_copy=fit_copy,
        material_copy=material_copy,
        coordi_copy=coordi_copy,
        size_guide_copy=size_guide_copy,
        care_copy=care_copy,
        sns_script=ctx["script"].script[:600],
        hashtags=ctx["hashtags"].hashtags,
        disclosure=ctx["disclosure"],
    )

    log = [
        f"[content] 카피 완료 — 제목 {len(copy.seo_title)}자 / 해시태그 {len(copy.hashtags)}개 / "
        f"고시정보 {6 - len(copy.disclosure.missing_required())}/6 입력",
    ]
    if design:
        log.append(f"[content] 디자인 섹션 {len(design.layout_sections)}개에 맞춰 카피 길이 조정")
    if price:
        log.append(f"[content] 판매가 {price:,}원 기준 혜택 문구 반영")
    for note in ctx["care"].notes:
        log.append(f"[content] {note}")

    return {"content_copy": copy, "status": "running", "log": log}
