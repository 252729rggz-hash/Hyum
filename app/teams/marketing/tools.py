"""마케팅팀 도구 — 채널별 광고 훅, 타겟팅 세그먼트, ROAS 손익분기, 예산 배분.

광고는 '감'이 아니라 손익분기선 위에서 굴려야 합니다. 마진율 55%인 상품은 ROAS 1.82가
손익분기이고, 그 아래로 내려가면 팔수록 손해입니다. 도구가 이 선을 먼저 계산하고,
그 위에서 소재 훅과 타겟을 만듭니다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.shared.models import TeamName
from app.shared.tooling import tool


# ═══════════════════════════════════════════════
# 1) 예산 배분
# ═══════════════════════════════════════════════
class BudgetArgs(BaseModel):
    daily_budget: int = Field(ge=0, description="일 예산(원)")
    weights: dict[str, float] = Field(
        default_factory=lambda: {"meta": 0.6, "naver": 0.4},
        description="채널별 비중. 합계 1.0 권장",
    )


class BudgetSplit(BaseModel):
    allocations: dict[str, int]
    total: int
    notes: list[str] = Field(default_factory=list)


@tool(
    name="mk_budget_split",
    team=TeamName.MARKETING,
    description="일 예산을 채널 비중대로 1,000원 단위 배분한다. 비중 합계가 1이 아니면 정규화하고 경고한다.",
    args=BudgetArgs,
    returns="BudgetSplit(채널별 금액·합계·메모)",
    tags=("budget",),
)
def budget_split(req: BudgetArgs) -> BudgetSplit:
    weights = {k: max(v, 0.0) for k, v in req.weights.items()}
    total_weight = sum(weights.values()) or 1.0
    notes: list[str] = []
    if abs(total_weight - 1.0) > 0.01:
        notes.append(f"비중 합계 {total_weight:.2f} — 1.0으로 정규화했습니다")
    raw = {k: req.daily_budget * (v / total_weight) for k, v in weights.items()}
    allocations = {k: int(v) // 1000 * 1000 for k, v in raw.items()}
    leftover = req.daily_budget - sum(allocations.values())
    if leftover > 0 and allocations:
        top = max(raw, key=lambda k: raw[k])
        allocations[top] += leftover
    if req.daily_budget < 30_000:
        notes.append("일 예산 3만원 미만 — 학습 구간(주 7회 이상 전환) 확보가 어렵습니다")
    return BudgetSplit(allocations=allocations, total=sum(allocations.values()), notes=notes)


# ═══════════════════════════════════════════════
# 2) ROAS 손익분기
# ═══════════════════════════════════════════════
class RoasArgs(BaseModel):
    margin_rate: float = Field(gt=0, lt=1, description="상품 순이익률(판매가 대비)")
    aov: int = Field(gt=0, description="객단가(장바구니 금액, 원)")
    daily_budget: int = Field(default=0, ge=0, description="일 광고 예산(원)")
    target_multiple: float = Field(default=1.7, gt=1.0, le=4.0, description="손익분기 대비 목표 배수")


class RoasBreakEven(BaseModel):
    be_roas: float = Field(description="손익분기 ROAS = 1 ÷ 마진율")
    target_roas: float
    max_cpa: int = Field(description="손익분기 CPA (객단가 × 마진율)")
    target_cpa: int
    break_even_orders_per_day: float
    notes: list[str] = Field(default_factory=list)


@tool(
    name="mk_roas_break_even",
    team=TeamName.MARKETING,
    description=(
        "마진율과 객단가로 손익분기 ROAS·목표 ROAS·최대 CPA·일 손익분기 주문수를 계산한다. "
        "광고비 집행 전 필수 확인."
    ),
    args=RoasArgs,
    returns="RoasBreakEven(손익분기 ROAS·목표 ROAS·최대/목표 CPA·일 주문수·메모)",
    tags=("roas", "unit_economics"),
)
def roas_break_even(req: RoasArgs) -> RoasBreakEven:
    be_roas = round(1 / req.margin_rate, 2)
    target_roas = round(be_roas * req.target_multiple, 2)
    max_cpa = int(req.aov * req.margin_rate)
    target_cpa = int(max_cpa / req.target_multiple)
    be_orders = round(req.daily_budget / max_cpa, 2) if req.daily_budget and max_cpa else 0.0
    notes = [
        f"ROAS {be_roas} 아래로 내려가면 팔수록 손해입니다",
        f"CPA가 {max_cpa:,}원을 넘으면 이 상품은 광고로 남는 게 없습니다",
    ]
    if req.target_multiple < 1.3:
        notes.append("목표 배수가 낮습니다 — 소재·타겟 개선 여지부터 확인하세요")
    return RoasBreakEven(
        be_roas=be_roas,
        target_roas=target_roas,
        max_cpa=max_cpa,
        target_cpa=target_cpa,
        break_even_orders_per_day=be_orders,
        notes=notes,
    )


# ═══════════════════════════════════════════════
# 3) 광고 훅
# ═══════════════════════════════════════════════
Channel = Literal["meta", "naver", "instagram_organic"]


class HookArgs(BaseModel):
    channel: Channel = "meta"
    name: str
    category: str
    price: int = Field(default=0, ge=0)
    hook: str = Field(default="", description="콘텐츠팀 후킹 문장")
    keywords: list[str] = Field(default_factory=list)
    fit: str = Field(default="regular")


class AdHook(BaseModel):
    angle: str
    headline: str
    primary_text: str
    cta: str


class AdHooks(BaseModel):
    channel: str
    hooks: list[AdHook]
    notes: list[str] = Field(default_factory=list)


@tool(
    name="mk_ad_hooks",
    team=TeamName.MARKETING,
    description=(
        "메타(릴스/피드)·네이버 쇼핑검색·인스타 유기 콘텐츠에 맞는 광고 훅 3종을 만든다. "
        "금지 표현 없이 핏·가격·코디 관점으로 나눈다."
    ),
    args=HookArgs,
    returns="AdHooks(채널·앵글별 헤드라인/본문/CTA·메모)",
    tags=("creative", "ad"),
)
def ad_hooks(req: HookArgs) -> AdHooks:
    leaf = req.category.split(">")[-1].strip()
    fit = {"regular": "레귤러핏", "slim": "슬림핏", "oversized": "오버핏", "loose": "루즈핏"}.get(req.fit, req.fit)
    price_text = f"{req.price:,}원" if req.price else "합리적인 가격"
    keyword = req.keywords[0] if req.keywords else f"남자 {leaf}"
    base_hook = req.hook or f"{fit} 하나로 끝나는 데일리 {leaf}"

    if req.channel == "meta":
        hooks = [
            AdHook(
                angle="핏 실루엣",
                headline=f"{fit} 하나로 출근룩 끝",
                primary_text=f"{base_hook}. 어깨선은 딱, 몸통은 여유 있게. 3초 안에 핏부터 보세요.",
                cta="사이즈 보기",
            ),
            AdHook(
                angle="가격 대비 완성도",
                headline=f"{price_text}, 마감에서 차이",
                primary_text="봉제·포켓·지퍼 접사까지 확인하고 고르세요. 데일리로 매일 입는 옷입니다.",
                cta="상세 보기",
            ),
            AdHook(
                angle="코디 활용도",
                headline="슬랙스에도, 데님에도",
                primary_text="출근엔 단정하게, 주말엔 캐주얼하게. 한 벌로 두 가지 분위기.",
                cta="코디 보기",
            ),
        ]
        notes = ["릴스 9:16 세로 소재 3종, 첫 3초에 전신 핏 노출", "자막 필수(무음 시청 80%)"]
    elif req.channel == "naver":
        hooks = [
            AdHook(
                angle="검색 키워드",
                headline=f"{keyword} {fit} {leaf}",
                primary_text=f"무료배송 · 당일출고 · {price_text}. 사이즈 실측표 제공.",
                cta="최저가 확인",
            ),
            AdHook(
                angle="사이즈 신뢰",
                headline=f"{leaf} 실측 사이즈표 공개",
                primary_text="178cm/68kg 모델 착용 컷과 실측표로 사이즈 실패를 줄입니다.",
                cta="사이즈 확인",
            ),
            AdHook(
                angle="배송 혜택",
                headline="평일 14시 이전 당일 출고",
                primary_text="주말 주문도 월요일 발송. 교환·반품 7일 보장.",
                cta="구매하기",
            ),
        ]
        notes = ["상품명 앞 15자에 핵심 키워드", "썸네일 1:1 단색 배경"]
    else:
        hooks = [
            AdHook(
                angle="착장 저장 유도",
                headline="오늘 코디 저장해두기",
                primary_text=f"{base_hook}. 룩북 3컷과 코디 아이템을 함께 정리했습니다.",
                cta="저장하기",
            ),
            AdHook(
                angle="디테일",
                headline="가격이 보이는 마감",
                primary_text="봉제·포켓·지퍼 접사로 마감을 먼저 보여줍니다.",
                cta="더 보기",
            ),
            AdHook(
                angle="사이즈 안내",
                headline="키·몸무게별 추천 사이즈",
                primary_text="마른·보통·탄탄·근육형 체형별 권장 사이즈를 정리했습니다.",
                cta="프로필 링크",
            ),
        ]
        notes = ["캐러셀 3컷 + 릴스 재업로드", "저장·공유 CTA 우선"]

    return AdHooks(channel=req.channel, hooks=hooks, notes=notes)


# ═══════════════════════════════════════════════
# 4) 타겟팅 세그먼트
# ═══════════════════════════════════════════════
class SegmentArgs(BaseModel):
    channel: Channel = "meta"
    category: str
    price: int = Field(default=0, ge=0)
    age_min: int = Field(default=25, ge=15, le=60)
    age_max: int = Field(default=34, ge=15, le=65)


class Segment(BaseModel):
    name: str
    definition: str
    priority: str = Field(description="core | test | exclude")
    bid_hint: str = ""


class Targeting(BaseModel):
    segments: list[Segment]
    excluded: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


@tool(
    name="mk_targeting",
    team=TeamName.MARKETING,
    description=(
        "채널별 타겟팅 세그먼트(관심사·키워드·유사타겟·연령)와 제외 조건을 만든다. "
        "예산이 작을 때 테스트 우선순위를 표시한다."
    ),
    args=SegmentArgs,
    returns="Targeting(세그먼트·제외 조건·메모)",
    tags=("targeting",),
)
def targeting(req: SegmentArgs) -> Targeting:
    leaf = req.category.split(">")[-1].strip()
    if req.channel == "meta":
        segments = [
            Segment(
                name="핵심 관심사",
                definition=f"{req.age_min}~{req.age_max}세 남성 · 남성의류·스트릿·오피스룩 관심사",
                priority="core",
                bid_hint="예산 50%",
            ),
            Segment(name="유사타겟", definition="구매자 기반 유사타겟 1~3%", priority="core", bid_hint="예산 30%"),
            Segment(name="리타겟팅", definition="상세 30일 조회·장바구니 이탈", priority="test", bid_hint="예산 20%"),
            Segment(name="신규 테스트", definition="패션 관심 광범위(18~44) 자동 타겟", priority="test"),
        ]
        excluded = ["최근 7일 구매자", "반품 2회 이상 고객"]
        notes = ["유사타겟은 구매 50건 이상 쌓인 뒤 생성", "리타겟팅은 상세 30초 이상 체류 조건 추가"]
    elif req.channel == "naver":
        segments = [
            Segment(name="정확 키워드", definition=f"남자 {leaf}, 남성 {leaf}", priority="core", bid_hint="입찰 1순위"),
            Segment(name="확장 키워드", definition=f"{leaf} 코디, 남자 데일리룩, 남자 출근룩", priority="test"),
            Segment(name="쇼핑검색", definition=f"카테고리: 남성의류 > {leaf}", priority="core", bid_hint="예산 60%"),
        ]
        excluded = ["브랜드명 키워드(상표권 리스크)"]
        notes = ["파워링크는 전환당 비용 상한 설정", "쇼핑검색은 상품명 앞 15자 최적화"]
    else:
        segments = [
            Segment(name="기존 팔로워", definition="최근 30일 저장·좋아요 반응 계정", priority="core"),
            Segment(name="착장 태그 유입", definition=f"#{leaf} 관련 해시태그 탐색층", priority="test"),
        ]
        excluded = []
        notes = ["유기 콘텐츠는 저장·공유가 지표", "주 3회 업로드 리듬 유지"]

    if req.price and req.price >= 100_000:
        notes.append(f"판매가 {req.price:,}원 — 가격 저항 구간, 리뷰·실착 컷을 소재에 우선 배치")

    return Targeting(segments=segments, excluded=excluded, notes=notes)


#: 마케팅팀이 LLM에 바인딩하는 도구 목록.
TOOLS = [budget_split, roas_break_even, ad_hooks, targeting]
