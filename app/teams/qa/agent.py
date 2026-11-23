"""검수(QA)팀 — 가격 오기·오탈자·과장광고·규격·고시정보를 배포 전에 막는 게이트키퍼.

규칙 기반으로 실제 검사합니다. 통과하지 못하면 실패 항목의 담당 팀을 태그해
피드백을 돌려주고, 오케스트레이터가 해당 팀으로 되돌립니다.

검사 축
- price : 판매가/마진/부가세/반품충당금 정합성, 역마진
- claim : 표시광고법·의료법상 금지 표현, 근거 없는 기능성, 연락처·외부 링크
- typo  : 중복 공백, 중복 구두점, 반복 문자, 미완성 자모
- asset : 필수 에셋 종류·규격·링크
- seo   : 제목/메타 길이, 해시태그, 핵심 키워드
- spec  : 카피·사이즈·재고 누락, 상품정보 고시(혼용률·제조국·세탁법)
"""

from __future__ import annotations

import re
from typing import Any

from app.orchestrator.state import MallWorkflowState
from app.shared.config import get_settings
from app.shared.models import (
    CheckCategory,
    ContentCopy,
    DesignPlan,
    MDPlan,
    ProductItem,
    QACheck,
    QAReport,
    Severity,
    TeamName,
)
from app.shared.prompting import PromptBundle, register_prompt
from app.shared.tooling import tool_manifest
from app.teams.qa.tools import TOOLS, AssetItem, asset_guard, disclosure_guard, margin_guard, scan_claims

TEAM = "qa"
TEAM_NAME = TeamName.QA
__all__ = ["TEAM", "SYSTEM_PROMPT", "USER_TEMPLATE", "PROMPT", "TOOLS", "build_prompt", "build_messages", "run"]

SYSTEM_PROMPT = f"""당신은 한국 남성 보세몰의 최종 검수(QA) 담당입니다.
배포 버튼을 누르기 전 마지막 관문이며, 여기서 놓친 것은 그대로 고객 클레임·과태료가 됩니다.
칭찬은 하지 않고, 문제와 근거, 담당 팀, 고치는 방법만 짧게 남깁니다.

[검사 축과 기준]
1. 가격(price): 판매가가 원가 이하인가(역마진), 순이익률이 최소 기준(기본 25%) 이상인가,
   부가세가 판매가의 10/110으로 맞는가, 반품충당금·PG 수수료가 반영됐는가.
2. 광고 표현(claim): 표시광고법 제3조 — 근거 없는 '최고급·최상급·1위·최저가', '완벽·반드시 보장',
   '영구·평생', '완판·품절대란'. 의료법 제27조 — '치료·효능·다이어트·부작용'.
   '100%'는 소재 함량(폴리에스터 100%)에만 허용. 방수·항균 같은 기능성은 근거 자료가 없으면 반려.
3. 오탈자(typo): 중복 공백, 중복 구두점(!!, ??), 반복 문자(ㅋㅋㅋ), 미완성 자모.
4. 에셋(asset): 상세페이지·썸네일·배너·룩북 4종 존재, 규격(860/1000×1000/1920×600/1200×1600),
   섹션 5개 이상, 이미지 링크 깨짐.
5. SEO: 제목 10~50자, 메타 20~80자, 제목에 카테고리/핏 키워드 포함, 해시태그 5~12개·형식 준수.
6. 스펙(spec): 카피 필수 항목, 재고 0 여부, 사이즈 옵션, 상품정보 고시(혼용률·제조국·세탁법).
   고시 누락은 전자상거래법 제13조 위반이므로 반드시 잡습니다.

[판정 규칙]
- critical·major 실패가 하나라도 있으면 '반려'입니다. minor만 있으면 통과로 보되 리포트에 남깁니다.
- 반려 시 담당 팀을 정확히 지정합니다: 가격·재고·사이즈→md, 섹션·규격·이미지→design,
  카피·제목·고시문구→content, 등록 payload·재고 동기화→dev.
- 피드백은 '[팀] CODE: 무엇이 문제인지 (근거 수치)' 형식 한 줄로 씁니다. 감정·추측 금지.
- 근거 없이 통과시키지 않습니다. 반대로, 규정에 없는 취향 문제로 반려하지 않습니다.
- 고객 개인정보(연락처·주소)가 카피에 들어가면 즉시 critical입니다.

[도구]
{tool_manifest(TEAM_NAME)}

[출력]
아래 JSON만 출력합니다.
{{
  "passed": true,
  "score": 100,
  "checks": [{{"code": "", "category": "price|claim|typo|asset|seo|spec", "passed": true,
             "severity": "critical|major|minor", "message": "", "target_team": "md|design|content|dev",
             "evidence": ""}}],
  "feedback": ["[md] PRICE_MARGIN: 순이익률 21.0% — 최소 25% 미달 (margin_rate=0.21)"]
}}"""

USER_TEMPLATE = """[검수 대상 SKU] $sku / $name ($category)
판매가: $price원 / 공급가: $cost원 / 재고: $stock장

[가격] $price_line
[광고 표현] $claim_line
[에셋] $asset_line
[고시정보] $disclosure_line
[SEO] $seo_line
[오탈자] $typo_line

[요청]
위 결과를 종합해 passed/score/checks/feedback JSON을 만드세요.
critical·major 실패가 하나라도 있으면 passed=false, score는 100에서
critical 30점·major 8점·minor 2점을 감점한 값입니다.
feedback은 담당 팀이 바로 고칠 수 있게 '[팀] CODE: 문제 (근거)' 형식으로 쓰세요."""

PROMPT = register_prompt(
    PromptBundle(
        team=TEAM_NAME,
        role="검수(QA)",
        system=SYSTEM_PROMPT,
        user_template=USER_TEMPLATE,
        output_contract="QAReport JSON (passed, score, checks[], feedback[])",
    )
)


# ═══════════════════════════════════════════════
# 헬퍼
# ═══════════════════════════════════════════════
DOUBLE_SPACE = re.compile(r"[가-힣A-Za-z0-9]\s{2,}[가-힣A-Za-z0-9]")
REPEATED_PUNCT = re.compile(r"([!?;~])\1+")
REPEATED_CHAR = re.compile(r"([가-힣])\1{2,}")
JAMO_ONLY = re.compile(r"[ㄱ-ㅎㅏ-ㅣ]")

COPY_FIELDS = {
    "seo_title": "SEO 제목",
    "meta_description": "메타 설명",
    "fit_copy": "핏 카피",
    "material_copy": "소재 카피",
    "coordi_copy": "코디 카피",
    "size_guide_copy": "사이즈 안내",
    "sns_script": "SNS 원고",
}

PENALTIES = {Severity.CRITICAL: 30, Severity.MAJOR: 8, Severity.MINOR: 2}


def _check(
    code: str,
    category: CheckCategory,
    passed: bool,
    message: str,
    target: TeamName,
    severity: Severity = Severity.MAJOR,
    evidence: str = "",
) -> QACheck:
    return QACheck(
        code=code,
        category=category,
        passed=passed,
        severity=severity,
        message=message,
        target_team=target,
        evidence=evidence[:200],
    )


def _copy_text(copy: ContentCopy) -> str:
    parts = [
        copy.seo_title,
        copy.meta_description,
        copy.hook,
        copy.fit_copy,
        copy.material_copy,
        copy.coordi_copy,
        copy.size_guide_copy,
        copy.care_copy,
        copy.sns_script,
    ]
    if copy.disclosure:
        parts.extend([copy.disclosure.material_composition, copy.disclosure.care_instruction])
    return "\n".join(p for p in parts if p)


def _severity(raw: str) -> Severity:
    return {"critical": Severity.CRITICAL, "major": Severity.MAJOR}.get(raw, Severity.MINOR)


# ═══════════════════════════════════════════════
# 검사 항목
# ═══════════════════════════════════════════════
def _check_price(product: ProductItem, md: MDPlan) -> list[QACheck]:
    s = get_settings()
    p = md.pricing
    guard = margin_guard(
        cost_price=product.cost_price,
        selling_price=p.selling_price,
        net_profit=p.net_profit,
        margin_rate=p.margin_rate,
        vat_amount=p.vat_amount,
        minimum_margin_rate=s.minimum_margin_rate,
        vat_rate=s.vat_rate,
        return_reserve=p.return_reserve,
        payment_fee=p.payment_fee,
    )
    checks = [
        _check(
            issue.code,
            CheckCategory.PRICE,
            False,
            issue.message,
            TeamName.MD,
            _severity(issue.severity),
            issue.evidence,
        )
        for issue in guard.issues
    ]
    if not checks:
        checks.append(
            _check(
                "PRICE_GUARD",
                CheckCategory.PRICE,
                True,
                f"가격 정합성 통과 (순이익률 {p.margin_rate:.1%}, 부가세 {p.vat_amount:,}원)",
                TeamName.MD,
                Severity.MAJOR,
                f"vat_expected={guard.vat_expected} / total_cost={guard.total_cost:,}",
            )
        )
    return checks


def _check_claims(copy: ContentCopy) -> list[QACheck]:
    scan = scan_claims(text=_copy_text(copy))
    if scan.passed:
        return [
            _check(
                "CLAIM_PROHIBITED",
                CheckCategory.CLAIM,
                True,
                "금지 표현 없음",
                TeamName.CONTENT,
                Severity.CRITICAL,
            )
        ]
    return [
        _check(
            f"CLAIM_{hit.code}",
            CheckCategory.CLAIM,
            False,
            f"금지·위험 표현 '{hit.phrase}' — {hit.reason}",
            TeamName.CONTENT,
            _severity(hit.severity),
            f"{hit.law} / '{hit.phrase}'",
        )
        for hit in scan.hits
    ]


def _check_typos(copy: ContentCopy) -> list[QACheck]:
    text = _copy_text(copy)
    issues: list[str] = []
    for field, label in COPY_FIELDS.items():
        value = getattr(copy, field, "") or ""
        if DOUBLE_SPACE.search(value):
            issues.append(f"{label}: 중복 공백")
        if REPEATED_PUNCT.search(value):
            issues.append(f"{label}: 중복 구두점")
        if REPEATED_CHAR.search(value):
            issues.append(f"{label}: 반복 문자")

    return [
        _check(
            "TYPO_FORMAT",
            CheckCategory.TYPO,
            not issues,
            "오탈자/포맷 오류가 있습니다" if issues else "오탈자 없음",
            TeamName.CONTENT,
            Severity.MAJOR if issues else Severity.MINOR,
            " | ".join(issues),
        ),
        _check(
            "TYPO_JAMO_ONLY",
            CheckCategory.TYPO,
            not bool(JAMO_ONLY.search(text)),
            "완성되지 않은 자모(ㅋㅋ, ㅎㅎ 등)가 포함되어 있습니다" if JAMO_ONLY.search(text) else "자모 오타 없음",
            TeamName.CONTENT,
            Severity.MINOR,
            text[:80],
        ),
    ]


def _check_assets(design: DesignPlan) -> list[QACheck]:
    guard = asset_guard(
        assets=[
            AssetItem(kind=a.kind, width=a.width, height=a.height, status=a.status, file_url=a.file_url)
            for a in design.assets
        ],
        section_count=len(design.layout_sections),
        has_image_prompt=bool(design.image_prompt),
    )
    return [
        _check(
            "ASSET_REQUIRED",
            CheckCategory.ASSET,
            not guard.missing,
            f"필수 에셋 누락: {', '.join(guard.missing)}" if guard.missing else "필수 에셋 4종 확보",
            TeamName.DESIGN,
            Severity.CRITICAL,
            f"assets={[a.kind for a in design.assets]}",
        ),
        _check(
            "ASSET_SIZE",
            CheckCategory.ASSET,
            not guard.size_issues,
            "에셋 규격이 기준과 다릅니다" if guard.size_issues else "에셋 규격 기준 충족",
            TeamName.DESIGN,
            Severity.MAJOR,
            " | ".join(guard.size_issues),
        ),
        _check(
            "ASSET_LAYOUT",
            CheckCategory.ASSET,
            not guard.layout_issues,
            " / ".join(guard.layout_issues) or "레이아웃 기준 충족",
            TeamName.DESIGN,
            Severity.MAJOR,
            f"sections={len(design.layout_sections)}",
        ),
        _check(
            "ASSET_BROKEN_LINK",
            CheckCategory.ASSET,
            not guard.broken,
            f"이미지 깨짐/링크 누락: {', '.join(guard.broken)}" if guard.broken else "에셋 링크 정상",
            TeamName.DESIGN,
            Severity.MAJOR,
            " | ".join(guard.broken),
        ),
    ]


def _check_disclosure(product: ProductItem, copy: ContentCopy) -> list[QACheck]:
    disc = copy.disclosure
    guard = disclosure_guard(
        material_composition=disc.material_composition if disc else "",
        country_of_origin=disc.country_of_origin if disc else "",
        care_instruction=disc.care_instruction if disc else "",
        manufacturer=disc.manufacturer if disc else "",
        quality_guarantee=disc.quality_guarantee if disc else "",
        as_contact=disc.as_contact if disc else "",
        source_material=product.material,
        source_origin=product.country_of_origin,
    )
    return [
        _check(
            "SPEC_DISCLOSURE",
            CheckCategory.SPEC,
            guard.passed,
            "상품정보 고시 누락: " + ", ".join(guard.missing) if guard.missing else "고시 필수 항목 입력 완료",
            TeamName.CONTENT,
            Severity.MAJOR,
            " | ".join(guard.missing),
        ),
        _check(
            "SPEC_DISCLOSURE_CONFIRM",
            CheckCategory.SPEC,
            not guard.confirm_needed,
            "고시 확인 필요: " + ", ".join(guard.confirm_needed) + " — 등록 전 사입처 확인"
            if guard.confirm_needed
            else "고시 원본 데이터 확인 완료",
            TeamName.CONTENT,
            Severity.MINOR,
            " | ".join(guard.confirm_needed),
        ),
    ]


def _check_seo(copy: ContentCopy, product: ProductItem) -> list[QACheck]:
    title = copy.seo_title or ""
    meta = copy.meta_description or ""
    leaf = product.category.split(">")[-1].strip()

    bad_tags = [t for t in copy.hashtags if not t.startswith("#") or " " in t or len(t) < 3]
    return [
        _check(
            "SEO_TITLE_LENGTH",
            CheckCategory.SEO,
            10 <= len(title) <= 50,
            f"제목이 {len(title)}자입니다 (권장 10~50자)" if not (10 <= len(title) <= 50) else "제목 길이 적정",
            TeamName.CONTENT,
            Severity.MAJOR,
            title,
        ),
        _check(
            "SEO_META_LENGTH",
            CheckCategory.SEO,
            20 <= len(meta) <= 80,
            f"메타 설명이 {len(meta)}자입니다 (권장 20~80자)" if not (20 <= len(meta) <= 80) else "메타 설명 길이 적정",
            TeamName.CONTENT,
            Severity.MINOR,
            meta,
        ),
        _check(
            "SEO_KEYWORD",
            CheckCategory.SEO,
            any(k in title for k in filter(None, [leaf, product.fit])),
            "제목에 핵심 키워드(카테고리/핏)가 없습니다",
            TeamName.CONTENT,
            Severity.MAJOR,
            title,
        ),
        _check(
            "SEO_HASHTAG",
            CheckCategory.SEO,
            not bad_tags and 5 <= len(copy.hashtags) <= 12,
            f"해시태그 형식/개수 오류: {bad_tags or len(copy.hashtags)}개",
            TeamName.CONTENT,
            Severity.MINOR,
            ", ".join(copy.hashtags),
        ),
    ]


def _check_specs(product: ProductItem, copy: ContentCopy) -> list[QACheck]:
    missing = [label for field, label in COPY_FIELDS.items() if not (getattr(copy, field, "") or "").strip()]
    return [
        _check(
            "SPEC_COPY_COMPLETE",
            CheckCategory.SPEC,
            not missing,
            f"카피 누락: {', '.join(missing)}" if missing else "필수 카피 모두 작성",
            TeamName.CONTENT,
            Severity.MAJOR,
            " | ".join(missing),
        ),
        _check(
            "SPEC_STOCK",
            CheckCategory.SPEC,
            product.stock > 0,
            "재고가 0장입니다 — 배포 전 실재고 확인 필요" if product.stock <= 0 else f"재고 {product.stock}장",
            TeamName.MD,
            Severity.CRITICAL,
            f"stock={product.stock}",
        ),
        _check(
            "SPEC_SIZE",
            CheckCategory.SPEC,
            bool(product.size_options),
            "사이즈 옵션이 비어 있습니다",
            TeamName.MD,
            Severity.CRITICAL,
            ", ".join(product.size_options),
        ),
        _check(
            "SPEC_SNS_LENGTH",
            CheckCategory.SPEC,
            60 <= len(copy.sns_script) <= 600,
            f"SNS 원고가 {len(copy.sns_script)}자입니다 (권장 60~600자)",
            TeamName.CONTENT,
            Severity.MINOR,
            copy.sns_script[:80],
        ),
    ]


# ═══════════════════════════════════════════════
# 실행
# ═══════════════════════════════════════════════
def _collect_checks(state: MallWorkflowState) -> tuple[list[QACheck], ProductItem]:
    product = ProductItem.model_validate(state["product"])
    md: MDPlan | None = state.get("md_plan")
    design: DesignPlan | None = state.get("design_assets")
    copy: ContentCopy | None = state.get("content_copy")

    checks: list[QACheck] = []
    if md is None:
        checks.append(
            _check("SPEC_MD_PLAN", CheckCategory.SPEC, False, "MD 기획안이 없습니다", TeamName.MD, Severity.CRITICAL)
        )
    else:
        checks.extend(_check_price(product, md))
    if copy is None:
        checks.append(
            _check(
                "SPEC_CONTENT",
                CheckCategory.SPEC,
                False,
                "콘텐츠 카피가 없습니다",
                TeamName.CONTENT,
                Severity.CRITICAL,
            )
        )
    else:
        checks.extend(_check_claims(copy))
        checks.extend(_check_typos(copy))
        checks.extend(_check_seo(copy, product))
        checks.extend(_check_specs(product, copy))
        checks.extend(_check_disclosure(product, copy))
    if design is None:
        checks.append(
            _check(
                "SPEC_DESIGN", CheckCategory.SPEC, False, "디자인 산출물이 없습니다", TeamName.DESIGN, Severity.CRITICAL
            )
        )
    else:
        checks.extend(_check_assets(design))
    return checks, product


def build_prompt(state: MallWorkflowState) -> str:
    """LLM 2차 검수용 사용자 메시지. 규칙 검수 결과를 그대로 보여주고 판정만 맡깁니다."""
    checks, product = _collect_checks(state)
    md: MDPlan | None = state.get("md_plan")
    design: DesignPlan | None = state.get("design_assets")
    copy: ContentCopy | None = state.get("content_copy")

    def brief(predicate) -> str:
        hits = [c for c in checks if predicate(c) and not c.passed]
        return " / ".join(f"{c.code}: {c.message}" for c in hits) or "이상 없음"

    return PROMPT.render(
        sku=product.sku,
        name=product.name,
        category=product.category,
        price=f"{md.pricing.selling_price:,}" if md else "미정",
        cost=f"{product.cost_price:,}",
        stock=product.stock,
        price_line=brief(lambda c: c.category == CheckCategory.PRICE),
        claim_line=brief(lambda c: c.category == CheckCategory.CLAIM),
        asset_line=brief(lambda c: c.category == CheckCategory.ASSET),
        disclosure_line=brief(lambda c: c.category == CheckCategory.SPEC),
        seo_line=brief(lambda c: c.category == CheckCategory.SEO),
        typo_line=brief(lambda c: c.category == CheckCategory.TYPO),
    ) if design or copy else "선행 산출물이 없어 검수 프롬프트를 만들 수 없습니다."


def build_messages(state: MallWorkflowState) -> list[dict[str, str]]:
    return [{"role": "system", "content": PROMPT.system}, {"role": "user", "content": build_prompt(state)}]


def run(state: MallWorkflowState) -> dict[str, Any]:
    checks, _ = _collect_checks(state)
    revision = int(state.get("qa_revision", 0)) + 1

    score = max(0, 100 - sum(PENALTIES[c.severity] for c in checks if not c.passed))
    blocking = [c for c in checks if not c.passed and c.severity in (Severity.CRITICAL, Severity.MAJOR)]
    passed = not blocking

    feedback: list[str] = []
    for c in blocking:
        feedback.append(f"[{c.target_team}] {c.code}: {c.message}" + (f" ({c.evidence})" if c.evidence else ""))
    for c in checks:
        if not c.passed and c.severity == Severity.MINOR and c.code == "SPEC_DISCLOSURE_CONFIRM":
            feedback.append(f"[{c.target_team}] {c.code}: {c.message}")

    report = QAReport(passed=passed, score=score, checks=checks, feedback=feedback)

    return {
        "qa_passed": passed,
        "qa_feedback": feedback,
        "qa_report": report,
        "qa_revision": revision,
        "status": "running",
        "log": [
            f"[qa] {revision}차 검수 — {'통과' if passed else '반려'} (점수 {score}) "
            + ("" if passed else f"/ 재작업 {len(blocking)}건")
        ],
    }
