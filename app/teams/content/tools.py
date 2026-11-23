"""콘텐츠팀 도구 — SEO 상품명, 체형별 핏 가이드, 소재·세탁 안내, 고시정보, 숏폼 대본, 해시태그.

보세몰은 같은 상품을 여러 셀러가 팔기 때문에 검색 제목과 첫 문단이 곧 경쟁력입니다.
도구는 (1) 글자수·금지어를 지키는 제목, (2) 실측에 근거한 사이즈 안내, (3) 법정 고시정보를
빠짐없이 채우는 역할을 맡습니다.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.shared.models import ProductDisclosure, TeamName
from app.shared.tooling import tool

#: 소재별 세탁 규칙. 혼용률에서 가장 비중이 큰 소재를 기준으로 안내합니다.
FABRIC_CARE: dict[str, dict[str, str]] = {
    "면": {
        "wash": "찬물 30도 이하, 중성세제, 단독 세탁",
        "dry": "그늘 건조(건조기 수축 주의)",
        "iron": "중온 다림질",
        "bleach": "염소 표백 금지",
    },
    "코튼": {
        "wash": "찬물 30도 이하, 중성세제",
        "dry": "그늘 건조",
        "iron": "중온 다림질",
        "bleach": "염소 표백 금지",
    },
    "폴리에스터": {
        "wash": "찬물 30도 이하 약하게, 단독 세탁",
        "dry": "건조기 금지(열변형)",
        "iron": "저온 다림질(천 대고)",
        "bleach": "표백 금지",
    },
    "폴리": {"wash": "찬물 30도 이하 약하게", "dry": "건조기 금지", "iron": "저온 다림질", "bleach": "표백 금지"},
    "나일론": {"wash": "찬물 단독, 마찰 최소화", "dry": "그늘 건조", "iron": "저온 다림질", "bleach": "표백 금지"},
    "울": {
        "wash": "드라이클리닝 권장(손세탁 시 울 전용 세제)",
        "dry": "평평하게 눕혀 그늘 건조",
        "iron": "스팀 다림질",
        "bleach": "표백 금지",
    },
    "모": {"wash": "드라이클리닝 전용", "dry": "걸어서 그늘 건조", "iron": "스팀 다림질", "bleach": "표백 금지"},
    "린넨": {
        "wash": "찬물 손세탁, 세제 적게",
        "dry": "그늘 건조",
        "iron": "약간 젖은 상태에서 중온 다림질",
        "bleach": "산소 표백만 가능",
    },
    "레이온": {
        "wash": "드라이클리닝 권장(물세탁 시 수축)",
        "dry": "평평하게 건조",
        "iron": "저온 다림질",
        "bleach": "표백 금지",
    },
    "아크릴": {"wash": "찬물 약하게, 세탁망 사용", "dry": "건조기 금지", "iron": "저온 다림질", "bleach": "표백 금지"},
    "스판": {
        "wash": "찬물 단독, 세탁망 사용",
        "dry": "건조기 금지(신축성 손상)",
        "iron": "저온 다림질",
        "bleach": "표백 금지",
    },
    "텐셀": {"wash": "찬물 약하게", "dry": "그늘 건조", "iron": "저온 다림질", "bleach": "표백 금지"},
}
DEFAULT_CARE = {
    "wash": "라벨 표기 확인, 찬물 단독 세탁 권장",
    "dry": "그늘 건조, 건조기 사용 금지",
    "iron": "저온 다림질",
    "bleach": "염소 표백 금지",
}

_COMPOSITION_RE = re.compile(r"([가-힣A-Za-z]+)\s*(\d{1,3}(?:\.\d+)?)\s*%")

FIT_LABEL = {"regular": "레귤러핏", "slim": "슬림핏", "oversized": "오버핏", "loose": "루즈핏"}


def _leaf(category: str) -> str:
    return category.split(">")[-1].strip() or category.strip()


# ═══════════════════════════════════════════════
# 1) SEO 제목
# ═══════════════════════════════════════════════
class SeoTitleArgs(BaseModel):
    category: str = Field(description="예: 남성 아우터 > 바람막이")
    fit: str = Field(default="regular")
    material: str = Field(default="")
    colors: list[str] = Field(default_factory=list)
    season: str = Field(default="")
    keywords: list[str] = Field(default_factory=list, description="도매처/검색 키워드")
    gender_word: str = Field(default="남성", description="검색에서 쓰는 성별 단어(남성/남자)")
    max_length: int = Field(default=50, ge=10, le=80, description="네이버 쇼핑 노출 기준 권장 50자")


class SeoTitle(BaseModel):
    title: str
    length: int
    alternatives: list[str] = Field(default_factory=list)
    keywords_used: list[str] = Field(default_factory=list)
    note: str = ""


def _compose(parts: list[str], limit: int) -> str:
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        candidate = " ".join([*out, part])
        if len(candidate) <= limit:
            out.append(part)
    return " ".join(out) or parts[0][:limit]


@tool(
    name="cn_seo_title",
    team=TeamName.CONTENT,
    description=(
        "검색 노출용 상품명을 만든다. 카테고리·핏·소재·시즌·키워드를 우선순위대로 조합하고 "
        "글자수 상한을 지킨다."
    ),
    args=SeoTitleArgs,
    returns="SeoTitle(제목·글자수·대안 2개·사용된 키워드)",
    tags=("seo", "title"),
)
def seo_title(req: SeoTitleArgs) -> SeoTitle:
    leaf = _leaf(req.category)
    fit = FIT_LABEL.get(req.fit, req.fit)
    material = (req.material.split()[0].replace("100%", "").strip() if req.material else "")
    extra = [k.strip() for k in req.keywords if k.strip()][:2]
    season = req.season.replace(" (SS)", "").replace(" (FW)", "").strip()

    primary = [req.gender_word, leaf, fit, material, season or "데일리"]
    title = _compose(primary, req.max_length)
    alt1 = _compose([req.gender_word, fit, leaf, "데일리", *extra], req.max_length)
    alt2 = _compose([leaf, req.gender_word, material, "무료배송", *extra], req.max_length)
    alternatives = list(dict.fromkeys(a for a in (alt1, alt2) if a and a != title))[:2]
    used = [w for w in [req.gender_word, leaf, fit, material, season, *extra] if w and w in title]

    return SeoTitle(
        title=title,
        length=len(title),
        alternatives=alternatives,
        keywords_used=used,
        note="최상급·1위·완판 표현은 넣지 않았습니다" if len(title) >= 10 else "제목이 짧아 키워드를 추가하세요",
    )


# ═══════════════════════════════════════════════
# 2) 체형별 핏 가이드
# ═══════════════════════════════════════════════
class FitGuideArgs(BaseModel):
    fit: str = Field(default="regular")
    size_options: list[str] = Field(default_factory=lambda: ["M", "L", "XL", "2XL"])
    height_cm: int = Field(default=178, ge=150, le=210, description="기준 모델 키")
    weight_kg: int = Field(default=68, ge=40, le=150, description="기준 모델 몸무게")
    body_type: str = Field(default="보통", description="마른 | 보통 | 탄탄 | 근육형")


class FitGuide(BaseModel):
    text: str
    recommended_size: str
    alternative: str = Field(description="정핏/여유핏 대안 안내")
    body_notes: list[str] = Field(default_factory=list)


def _size_by_body(height_cm: int, weight_kg: int, sizes: list[str]) -> int:
    band = 0
    if weight_kg >= 88:
        band = 3
    elif weight_kg >= 78:
        band = 2
    elif weight_kg >= 68:
        band = 1
    if height_cm >= 182:
        band += 1
    return max(0, min(band, len(sizes) - 1))


@tool(
    name="cn_fit_guide",
    team=TeamName.CONTENT,
    description="키·몸무게·체형으로 추천 사이즈를 계산하고, 핏별 착용감 설명과 사이즈 업/다운 안내를 만든다.",
    args=FitGuideArgs,
    returns="FitGuide(안내 문장·추천 사이즈·대안·체형별 주의)",
    tags=("size", "copy"),
)
def fit_guide(req: FitGuideArgs) -> FitGuide:
    sizes = req.size_options or ["M", "L", "XL"]
    idx = _size_by_body(req.height_cm, req.weight_kg, sizes)
    fit = FIT_LABEL.get(req.fit, req.fit)
    recommended = sizes[idx]
    if req.fit in ("oversized", "loose"):
        alternative = f"정핏을 원하시면 {sizes[max(idx - 1, 0)]}, 여유핏은 {recommended}"
    elif req.fit == "slim":
        alternative = f"정핏은 {recommended}, 어깨가 넓으면 {sizes[min(idx + 1, len(sizes) - 1)]}"
    else:
        alternative = f"정핏은 {recommended}, 여유 있게 입으려면 {sizes[min(idx + 1, len(sizes) - 1)]}"

    body_notes = {
        "마른": "어깨선이 살아 있는 핏이 잘 맞습니다. 몸통이 과하게 붙는 슬림은 피하세요.",
        "탄탄": "가슴·어깨가 있는 체형은 정사이즈가 자연스럽습니다.",
        "근육형": "가슴·팔 두께 때문에 한 사이즈 업을 권장합니다(암홀 당김 방지).",
        "보통": "평소 사이즈로 무난하며, 레이어드하면 한 사이즈 업이 편합니다.",
    }.get(req.body_type, "평소 사이즈로 무난합니다.")

    text = (
        f"{req.height_cm}cm/{req.weight_kg}kg {req.body_type} 체형 기준 {recommended} 사이즈를 권장합니다. "
        f"{fit}이라 어깨선은 안정적으로 떨어지고 몸통은 여유 있게 잡힙니다. {alternative}."
    )
    return FitGuide(text=text, recommended_size=recommended, alternative=alternative, body_notes=[body_notes])


# ═══════════════════════════════════════════════
# 3) 소재·세탁 안내
# ═══════════════════════════════════════════════
class CareArgs(BaseModel):
    material: str = Field(default="", description="도매처 표기 소재 (예: 면 60% 폴리에스터 40%)")
    colors: list[str] = Field(default_factory=list)


class CareGuide(BaseModel):
    composition: str
    wash: str
    dry: str
    iron: str
    bleach: str
    text: str
    notes: list[str] = Field(default_factory=list)


def _parse_composition(material: str) -> list[tuple[str, float]]:
    return [(name, float(pct)) for name, pct in _COMPOSITION_RE.findall(material or "")]


@tool(
    name="cn_care_guide",
    team=TeamName.CONTENT,
    description=(
        "혼용률을 파싱해 소재별 세탁·건조·다림질·표백 안내를 만든다. "
        "혼용률이 없으면 '라벨 확인' 안내로 대체하고 확인 필요를 남긴다."
    ),
    args=CareArgs,
    returns="CareGuide(혼용률·세탁·건조·다림질·표백·문장)",
    tags=("care", "material"),
)
def care_guide(req: CareArgs) -> CareGuide:
    pairs = _parse_composition(req.material)
    notes: list[str] = []
    if pairs:
        main = max(pairs, key=lambda p: p[1])[0]
        rule = FABRIC_CARE.get(main, DEFAULT_CARE)
        composition = " ".join(f"{name} {pct:g}%" for name, pct in pairs)
        notes.append(f"주 소재: {main}")
        if len(pairs) > 1:
            notes.append("혼용 소재는 가장 비중이 큰 소재 기준으로 안내했습니다")
    else:
        rule = DEFAULT_CARE
        composition = req.material.strip() or "미확인(사입처 확인 필요)"
        if not req.material.strip():
            notes.append("혼용률 미기재 — 등록 전 사입처 라벨 확인 필요")

    if any(c in ("화이트", "흰색", "아이보리", "크림") for c in req.colors):
        notes.append("밝은 색상은 다른 색과 분리 세탁(이염 주의)")

    text = (
        f"혼용률 {composition} / 세탁 {rule['wash']} / 건조 {rule['dry']} / "
        f"다림질 {rule['iron']} / {rule['bleach']}"
    )
    return CareGuide(
        composition=composition,
        wash=rule["wash"],
        dry=rule["dry"],
        iron=rule["iron"],
        bleach=rule["bleach"],
        text=text,
        notes=notes,
    )


# ═══════════════════════════════════════════════
# 4) 상품정보 고시
# ═══════════════════════════════════════════════
class DisclosureArgs(BaseModel):
    material: str = Field(default="", description="도매처 표기 소재")
    country_of_origin: str = Field(default="", description="제조국. 미기재 시 '확인 필요'로 남긴다")
    supplier: str = Field(default="", description="사입처(제조자/수입자 표기에 사용)")
    care_text: str = Field(default="", description="세탁 안내 문장")


@tool(
    name="cn_disclosure",
    team=TeamName.CONTENT,
    description=(
        "전자상거래법상 의류 상품정보 고시(혼용률·제조국·세탁법·제조자·품질보증·AS)를 채운다. "
        "모르는 값은 비워 두지 않고 '확인 필요'로 표시한다."
    ),
    args=DisclosureArgs,
    returns="ProductDisclosure(혼용률·제조국·세탁법·제조자·품질보증·AS)",
    tags=("compliance", "disclosure"),
)
def disclosure(req: DisclosureArgs) -> ProductDisclosure:
    composition = " ".join(f"{n} {p:g}%" for n, p in _parse_composition(req.material)) or (
        req.material.strip() or "확인 필요(사입처 문의)"
    )
    return ProductDisclosure(
        material_composition=composition,
        country_of_origin=req.country_of_origin.strip() or "확인 필요(사입처 문의)",
        care_instruction=req.care_text or DEFAULT_CARE["wash"],
        manufacturer=req.supplier.strip() or "확인 필요(사입처 문의)",
        quality_guarantee="소비자분쟁해결기준(공정거래위원회 고시)에 따름",
        as_contact="고객센터(상세페이지 하단 안내)",
    )


# ═══════════════════════════════════════════════
# 5) 숏폼(릴스) 대본
# ═══════════════════════════════════════════════
class ShortformArgs(BaseModel):
    name: str
    category: str
    fit: str = "regular"
    material: str = ""
    price: int = Field(default=0, ge=0)
    sizes: list[str] = Field(default_factory=list)
    hook: str = ""
    benefits: list[str] = Field(default_factory=list)


class Beat(BaseModel):
    time: str
    line: str
    shot: str


class ShortformScript(BaseModel):
    beats: list[Beat]
    total_seconds: int
    script: str
    caption: str


@tool(
    name="cn_shortform_script",
    team=TeamName.CONTENT,
    description="릴스·숏폼 15~30초 대본을 훅(0~3초)→핏/디테일→코디→CTA 4비트로 만든다. 자막 기준으로 짧게 끊는다.",
    args=ShortformArgs,
    returns="ShortformScript(비트별 대사·샷·총 길이·캡션)",
    tags=("sns", "shortform"),
)
def shortform_script(req: ShortformArgs) -> ShortformScript:
    leaf = _leaf(req.category)
    fit = FIT_LABEL.get(req.fit, req.fit)
    size_range = f"{req.sizes[0]}~{req.sizes[-1]}" if req.sizes else "M~2XL"
    hook = req.hook or f"{fit} 하나로 끝나는 데일리 {leaf}"
    benefit = req.benefits[0] if req.benefits else "구김이 적어 매일 입기 좋습니다"

    beats = [
        Beat(time="0-3초", line=f"{hook}.", shot="전신 착장, 카메라 정면. 첫 프레임에 어깨선 노출"),
        Beat(
            time="4-10초",
            line=f"어깨선은 딱 떨어지고 몸통은 여유 있게. {req.material or '탄탄한 원단'}이라 {benefit}.",
            shot="어깨→소매→밑단 순서로 천천히 팬",
        ),
        Beat(time="11-18초", line="출근엔 슬랙스, 주말엔 데님. 한 벌로 두 가지 분위기.", shot="코디 2종 교차"),
        Beat(time="19-25초", line=f"사이즈는 {size_range}. 프로필 링크에서 확인하세요.", shot="사이즈표+썸네일 고정"),
    ]
    script = " ".join(f"[{b.time}] {b.line}" for b in beats)
    caption = f"{fit} {leaf} | {size_range} | 무료배송"
    return ShortformScript(beats=beats, total_seconds=25, script=script, caption=caption)


# ═══════════════════════════════════════════════
# 6) 해시태그
# ═══════════════════════════════════════════════
class HashtagArgs(BaseModel):
    category: str
    fit: str = "regular"
    season: str = ""
    extra: list[str] = Field(default_factory=list)


class HashtagSet(BaseModel):
    hashtags: list[str]
    note: str


@tool(
    name="cn_hashtags",
    team=TeamName.CONTENT,
    description="상품 카테고리·핏·시즌에 맞는 인스타그램 해시태그 10개를 만든다. 공백·특수문자 없이 규격에 맞춘다.",
    args=HashtagArgs,
    returns="HashtagSet(해시태그 10개·메모)",
    tags=("sns", "seo"),
)
def hashtags(req: HashtagArgs) -> HashtagSet:
    leaf = _leaf(req.category).replace(" ", "")
    fit = FIT_LABEL.get(req.fit, req.fit)
    season_tag = {"봄": "봄코디", "여름": "여름코디", "가을": "가을코디", "겨울": "겨울코디"}.get(
        req.season.split(" ")[0], "데일리룩"
    )
    base = ["남성패션", fit, leaf, "남자코디", season_tag, "데일리룩", "신상입고", "무료배송", "보세의류", "오피스룩"]
    cleaned: list[str] = []
    for tag in [*base, *req.extra]:
        tag = "#" + re.sub(r"[^0-9A-Za-z가-힣]", "", tag.lstrip("#"))
        if len(tag) >= 3 and tag not in cleaned:
            cleaned.append(tag)
    return HashtagSet(hashtags=cleaned[:10], note=f"{len(cleaned[:10])}개 — 5~12개 권장 범위")


#: 콘텐츠팀이 LLM에 바인딩하는 도구 목록.
TOOLS = [seo_title, fit_guide, care_guide, disclosure, shortform_script, hashtags]
