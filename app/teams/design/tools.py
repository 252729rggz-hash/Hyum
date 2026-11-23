"""디자인팀 도구 — 모바일 우선 상세페이지 설계, 에셋 규격, 이미지 프롬프트, 팔레트.

상세페이지는 '스크롤 3초 안에 핏이 보이는가'로 승부가 갈립니다. 도구는 그 순서를
고정하고, 각 컷의 촬영 지시와 규격(px·용량)을 숫자로 남깁니다. 실제 이미지 생성은
`ds_image_prompt`가 만든 영문 프롬프트를 이미지 생성 API에 넘기는 방식으로 확장합니다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.shared.models import TeamName
from app.shared.tooling import tool


# ═══════════════════════════════════════════════
# 1) 상세페이지 블루프린트
# ═══════════════════════════════════════════════
class SectionSpec(BaseModel):
    order: int
    section: str
    headline: str
    visual: str
    copy_points: list[str] = Field(default_factory=list)
    height_px: int = Field(description="모바일 720px 기준 권장 세로 길이")
    mobile_note: str = ""


class BlueprintArgs(BaseModel):
    name: str = Field(description="상품명")
    category: str = Field(description="예: 남성 아우터 > 바람막이")
    fit: str = Field(default="regular")
    material: str = Field(default="")
    colors: list[str] = Field(default_factory=list)
    price: int = Field(default=0, ge=0, description="판매가(원). 혜택 문구에 사용")
    selling_points: list[str] = Field(default_factory=list, description="강조할 강점(없으면 핏·소재 중심)")


class DetailBlueprint(BaseModel):
    sections: list[SectionSpec]
    mobile_width_px: int = 720
    desktop_width_px: int = 860
    total_height_px: int
    scroll_hooks: list[str] = Field(description="이탈 방지용 스크롤 구간별 후킹")


@tool(
    name="ds_detail_blueprint",
    team=TeamName.DESIGN,
    description=(
        "모바일 우선 상세페이지 섹션을 순서대로 설계한다: 후킹 인트로 → 룩북/히어로 → 핏 포인트 → 디테일 컷 → "
        "소재/촉감 → 스펙·사이즈표 → 코디 제안 → 배송·고시정보. 각 섹션의 촬영 지시와 권장 높이를 함께 준다."
    ),
    args=BlueprintArgs,
    returns="DetailBlueprint(섹션 목록·모바일/PC 폭·총 높이·스크롤 후킹)",
    tags=("layout", "detail_page"),
)
def detail_blueprint(req: BlueprintArgs) -> DetailBlueprint:
    leaf = req.category.split(">")[-1].strip() or req.category
    fit_label = {"regular": "레귤러핏", "slim": "슬림핏", "oversized": "오버핏", "loose": "루즈핏"}.get(
        req.fit, req.fit
    )
    color_text = ", ".join(req.colors[:3]) or "기본 색상"

    sections = [
        SectionSpec(
            order=1,
            section="후킹 인트로",
            headline=f"{fit_label} {leaf}, 3초에 핏부터",
            visual="전신 착장컷 1장 + 3초 루프 영상(걷는 동작), 첫 화면에 얼굴과 어깨선이 함께 보이게",
            copy_points=[f"{fit_label} 실루엣 한 줄", "가격·무료배송·사이즈 범위"],
            height_px=640,
            mobile_note="첫 스크롤 전에 핏이 보여야 이탈률이 낮아집니다. 텍스트는 이미지에 굽지 않습니다",
        ),
        SectionSpec(
            order=2,
            section="룩북 / 히어로",
            headline=f"{color_text} 3색, 같은 핏 다른 분위기",
            visual="자연광 스튜디오 전신컷 2~3장, 컬러별 착장 비교",
            copy_points=["시즌 무드", "톤온톤 vs 컬러 포인트"],
            height_px=1080,
            mobile_note="정방형 썸네일과 다른 컷을 써야 재방문에서 새로움을 줍니다",
        ),
        SectionSpec(
            order=3,
            section="핏 포인트",
            headline=f"어깨선은 {fit_label}, 몸통은 여유 있게",
            visual="상반신 정면·측면 비교컷, 어깨 드롭·암홀·총장 가이드선",
            copy_points=["어깨 드롭", "암홀 깊이", "총장(힙 위)"],
            height_px=900,
            mobile_note="가이드선은 얇은 실선 1px, 3개 이하로 제한",
        ),
        SectionSpec(
            order=4,
            section="디테일 컷",
            headline="마감에서 가격이 보입니다",
            visual="봉제선·포켓·지퍼·밑단 접사 4컷(1:1), 손으로 만진 질감 1컷",
            copy_points=["봉제 밀도", "포켓 깊이", "지퍼 마감", *req.selling_points[:2]],
            height_px=860,
            mobile_note="접사컷은 1:1 정방형으로 잘라 2열 그리드에 배치",
        ),
        SectionSpec(
            order=5,
            section="소재 / 촉감",
            headline=f"{req.material or '탄탄한 원단'}의 촉감",
            visual="원단 매크로 2장 + 늘어남·구김 테스트 GIF(3초)",
            copy_points=["두께감", "신축성", "세탁 후 변형", "비침 여부"],
            height_px=780,
            mobile_note="GIF는 1MB 이하, 자동재생·무음",
        ),
        SectionSpec(
            order=6,
            section="스펙 / 사이즈표",
            headline="실측 사이즈표 (단위 cm)",
            visual="어깨·가슴·총장·소매 표 이미지 + 모델 착용 기준 1컷",
            copy_points=["모델 178cm/68kg 착용 L", "평균 사이즈 추천", "오차 ±1~2cm 안내"],
            height_px=720,
            mobile_note="표는 이미지가 아니라 HTML 표로도 노출해 검색·확대 대응",
        ),
        SectionSpec(
            order=7,
            section="코디 / 스타일링",
            headline="출근도 주말도, 이 한 벌",
            visual="코디 3종 컷(슬랙스·데님·트레이닝), 신발·가방까지 프레임 안에",
            copy_points=["톤온톤", "아우터 레이어링", "신발 매치"],
            height_px=900,
            mobile_note="코디컷 하단에 '함께 코디한 상품' 링크 자리 확보",
        ),
        SectionSpec(
            order=8,
            section="배송 / 교환 / 고시정보",
            headline="배송·교환·반품 안내",
            visual="아이콘 3종(택배·교환·반품) + 고시정보 텍스트 블록",
            copy_points=["평일 14시 이전 당일 출고", "수령 후 7일 내 교환", "혼용률·제조국·세탁법·AS"],
            height_px=520,
            mobile_note="고시정보는 이미지가 아닌 텍스트로 노출해야 법적 요건을 충족합니다",
        ),
    ]
    return DetailBlueprint(
        sections=sections,
        total_height_px=sum(s.height_px for s in sections),
        scroll_hooks=[
            "0~3초: 전신 착장 + 핏 한 줄 (이탈 방지)",
            "1~2스크롤: 핏 포인트 가이드선 (구매 이유 형성)",
            "3~4스크롤: 디테일·소재 접사 (가격 납득)",
            "5스크롤 이후: 사이즈표·코디 (구매 확신)",
            "마지막: 배송·교환·고시정보 (클레임 예방)",
        ],
    )


# ═══════════════════════════════════════════════
# 2) 에셋 규격
# ═══════════════════════════════════════════════
AssetKey = Literal["detail_page", "thumbnail", "banner", "lookbook", "detail_cut", "macro"]


class AssetSpecArgs(BaseModel):
    kind: AssetKey = Field(description="detail_page | thumbnail | banner | lookbook | detail_cut | macro")


class AssetSpec(BaseModel):
    kind: str
    width: int
    height: int
    ratio: str
    format: str
    max_kb: int
    safe_area: str
    note: str


_SPECS: dict[str, AssetSpec] = {
    "detail_page": AssetSpec(
        kind="detail_page", width=860, height=4000, ratio="세로 가변", format="jpg", max_kb=10_000,
        safe_area="좌우 40px 여백", note="모바일 720px 대응, 10장 이하 분할 업로드·장당 1MB 이하 권장",
    ),
    "thumbnail": AssetSpec(
        kind="thumbnail", width=1000, height=1000, ratio="1:1", format="jpg", max_kb=300,
        safe_area="상단 20% 헤드라인 영역", note="검색·랭킹 썸네일. 배경 단색, 텍스트는 3단어 이내",
    ),
    "banner": AssetSpec(
        kind="banner", width=1920, height=600, ratio="16:5", format="jpg", max_kb=500,
        safe_area="좌측 40% 텍스트, 우측 인물", note="모바일에서는 750×400 중앙 크롭",
    ),
    "lookbook": AssetSpec(
        kind="lookbook", width=1200, height=1600, ratio="3:4", format="jpg", max_kb=800,
        safe_area="인물 상단 10% 비움", note="룩북·상세 히어로 공용. 컬러별 최소 1컷",
    ),
    "detail_cut": AssetSpec(
        kind="detail_cut", width=860, height=860, ratio="1:1", format="jpg", max_kb=400,
        safe_area="중앙 피사체 80%", note="봉제·포켓·지퍼 접사. 2열 그리드 배치",
    ),
    "macro": AssetSpec(
        kind="macro", width=860, height=600, ratio="3:2", format="jpg", max_kb=400,
        safe_area="중앙", note="원단 결·신축 테스트 컷",
    ),
}


@tool(
    name="ds_asset_spec",
    team=TeamName.DESIGN,
    description="상세페이지·썸네일·배너·룩북·디테일컷의 픽셀 규격, 비율, 포맷, 용량 상한, 텍스트 안전영역을 돌려준다.",
    args=AssetSpecArgs,
    returns="AssetSpec(width·height·ratio·format·max_kb·safe_area·note)",
    tags=("spec", "asset"),
)
def asset_spec(req: AssetSpecArgs) -> AssetSpec:
    return _SPECS[req.kind]


# ═══════════════════════════════════════════════
# 3) 이미지 프롬프트
# ═══════════════════════════════════════════════
class ImagePromptArgs(BaseModel):
    kind: Literal["lookbook", "thumbnail", "detail_cut", "banner"] = "lookbook"
    category: str = Field(description="예: 남성 아우터 > 바람막이")
    fit: str = "regular"
    material: str = ""
    colors: list[str] = Field(default_factory=list)
    palette: list[str] = Field(default_factory=list, description="HEX 팔레트(배경·소품 톤)")
    mood: str = Field(default="clean minimal editorial")


class ImagePrompt(BaseModel):
    kind: str
    prompt: str
    negative_prompt: str
    ratio: str
    usage_note: str


@tool(
    name="ds_image_prompt",
    team=TeamName.DESIGN,
    description="한국 남성 모델 기준 룩북·썸네일·디테일컷 이미지 생성용 영문 프롬프트와 네거티브 프롬프트를 만든다.",
    args=ImagePromptArgs,
    returns="ImagePrompt(prompt·negative_prompt·ratio·usage_note)",
    tags=("image", "prompt"),
)
def image_prompt(req: ImagePromptArgs) -> ImagePrompt:
    leaf = req.category.split(">")[-1].strip() or "garment"
    color = (req.colors[0] if req.colors else "black").lower()
    material = req.material or "cotton blend"
    palette = ", ".join(req.palette[:4]) or "muted neutral palette"
    base = (
        f"editorial fashion photography of a 26-year-old Korean male model wearing a {color} {req.fit}-fit "
        f"{leaf} made of {material}, natural skin texture, calm expression"
    )
    common_neg = (
        "no text, no logos, no watermark, no distorted hands, no extra fingers, no plastic skin, "
        "no harsh flash, no oversaturated colors, no busy background"
    )

    if req.kind == "lookbook":
        prompt = (
            f"{base}, standing full body in a minimal concrete studio, soft north window light, "
            f"3:4 vertical crop with headroom, muted palette ({palette}), {req.mood}, 85mm lens f/2.0, "
            "shallow depth of field, high-end Korean menswear lookbook"
        )
        ratio, note = "3:4", "상세 히어로·룩북 공용. 컬러별 1컷 이상 생성"
    elif req.kind == "thumbnail":
        prompt = (
            f"{base}, waist-up 1:1 crop, seamless background in {palette.split(',')[0]}, "
            f"strong shoulder line visible, crisp studio light, room for a 3-word Korean headline at top, {req.mood}"
        )
        ratio, note = "1:1", "상단 20%는 텍스트 자리로 비워 둠. 얼굴·어깨선 중심"
    elif req.kind == "detail_cut":
        prompt = (
            f"extreme close-up product photography of the {leaf} fabric and stitching, {material}, "
            f"{color} color, visible seam density and texture, soft directional light, {req.mood}, 100mm macro lens"
        )
        ratio, note = "1:1", "봉제·포켓·지퍼 각 1컷, 2열 그리드"
    else:
        prompt = (
            f"{base}, wide banner composition with model on the right third, clean negative space on the left 40% "
            f"for Korean copy, {req.mood}, 16:5 crop"
        )
        ratio, note = "16:5", "좌측 40%는 카피 영역. 모바일은 중앙 크롭"

    return ImagePrompt(kind=req.kind, prompt=prompt, negative_prompt=common_neg, ratio=ratio, usage_note=note)


# ═══════════════════════════════════════════════
# 4) 팔레트 + 대비
# ═══════════════════════════════════════════════
class PaletteArgs(BaseModel):
    name: str = ""
    category: str = ""
    colors: list[str] = Field(default_factory=list, description="상품 컬러 옵션(한글/영문)")


class Palette(BaseModel):
    colors: list[str] = Field(description="HEX 4색: 배경·보조·포인트·텍스트")
    background: str
    text_on_background: str
    contrast_ratio: float = Field(description="배경 대비 텍스트 명도 대비(WCAG 기준 4.5 이상 권장)")
    accessible: bool
    mood: str


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _luminance(hex_color: str) -> float:
    def channel(c: int) -> float:
        srgb = c / 255
        return srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_rgb(hex_color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return round((lighter + 0.05) / (darker + 0.05), 2)


@tool(
    name="ds_palette",
    team=TeamName.DESIGN,
    description="상품 컬러에서 상세페이지 팔레트 4색을 뽑고, 배경 위 텍스트 명도 대비(WCAG)로 접근성을 확인한다.",
    args=PaletteArgs,
    returns="Palette(HEX 4색·배경·텍스트색·대비·접근성 통과 여부·무드)",
    tags=("color", "accessibility"),
)
def palette(req: PaletteArgs) -> Palette:
    text = f"{req.name} {req.category} {' '.join(req.colors)}".lower()
    if any(k in text for k in ("블랙", "black", "차콜", "charcoal", "네이비", "navy")):
        colors, background, mood = ["#111111", "#2B2B2B", "#E8E4DC", "#B08D57"], "#F4F1EA", "noir minimal"
    elif any(k in text for k in ("베이지", "beige", "아이보리", "ivory", "크림", "cream", "화이트", "white")):
        colors, background, mood = ["#F4F1EA", "#D9CFC0", "#8A7A66", "#2E2A26"], "#F4F1EA", "warm neutral"
    elif any(k in text for k in ("카키", "khaki", "올리브", "olive", "그린", "green")):
        colors, background, mood = ["#4B5340", "#7C8468", "#E6E2D6", "#1F211B"], "#E6E2D6", "outdoor utility"
    else:
        colors, background, mood = ["#F5F5F3", "#3A3A3A", "#9AA5AD", "#C8A27A"], "#F5F5F3", "clean studio"

    dark, light = "#1A1A1A", "#FFFFFF"
    contrast_dark = _contrast(background, dark)
    contrast_light = _contrast(background, light)
    text_color = dark if contrast_dark >= contrast_light else light
    best = max(contrast_dark, contrast_light)

    return Palette(
        colors=colors,
        background=background,
        text_on_background=text_color,
        contrast_ratio=best,
        accessible=best >= 4.5,
        mood=mood,
    )


#: 디자인팀이 LLM에 바인딩하는 도구 목록.
TOOLS = [detail_blueprint, asset_spec, image_prompt, palette]
