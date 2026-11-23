"""개발팀 도구 — 몰 등록 payload 매핑, 옵션(컬러×사이즈) 조합, 재고 임계치 알림.

쇼핑몰마다 상품 등록 스펙이 달라서, 팀 안에서는 '우리 표준 payload'를 만들고 어댑터가
플랫폼 스펙으로 변환합니다. 옵션 조합과 재고 분배는 여기서 계산해 두면 등록 후
품절 옵션이 그대로 노출되는 사고를 줄일 수 있습니다.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from app.shared.models import TeamName
from app.shared.tooling import tool

Platform = Literal["cafe24", "imweb", "custom"]


# ═══════════════════════════════════════════════
# 1) 옵션 조합
# ═══════════════════════════════════════════════
class OptionMatrixArgs(BaseModel):
    sku: str = Field(description="상품 SKU")
    colors: list[str] = Field(min_length=1, description="컬러 옵션")
    sizes: list[str] = Field(min_length=1, description="사이즈 옵션")
    stock: int = Field(default=0, ge=0, description="총 재고(장). 조합에 균등 배분")
    disabled: list[str] = Field(default_factory=list, description="판매하지 않을 조합 '컬러/사이즈'")
    extra_price: dict[str, int] = Field(default_factory=dict, description="사이즈별 추가 금액(예: 2XL +2000)")


class OptionCombination(BaseModel):
    code: str
    color: str
    size: str
    stock: int
    price_delta: int = 0
    status: str = Field(description="active | disabled | soldout")


class OptionMatrix(BaseModel):
    options: list[OptionCombination]
    active_count: int
    disabled_count: int
    total_stock: int
    notes: list[str] = Field(default_factory=list)


def _distribute(total: int, count: int) -> list[int]:
    if count <= 0:
        return []
    base, remainder = divmod(total, count)
    return [base + (1 if i < remainder else 0) for i in range(count)]


@tool(
    name="dev_option_matrix",
    team=TeamName.DEV,
    description="컬러×사이즈 옵션 조합을 만들고 SKU 옵션 코드, 재고 배분, 사이즈별 추가금, 판매중지 조합을 계산한다.",
    args=OptionMatrixArgs,
    returns="OptionMatrix(조합 목록·활성/비활성 수·총 재고·주의사항)",
    tags=("option", "stock"),
)
def option_matrix(req: OptionMatrixArgs) -> OptionMatrix:
    disabled = {d.replace(" ", "") for d in req.disabled}
    active_pairs = [(c, s) for c in req.colors for s in req.sizes if f"{c}/{s}".replace(" ", "") not in disabled]
    stocks = _distribute(req.stock, len(active_pairs)) if active_pairs else []

    options: list[OptionCombination] = []
    idx = 0
    for color in req.colors:
        for size in req.sizes:
            idx += 1
            key = f"{color}/{size}".replace(" ", "")
            if key in disabled:
                options.append(
                    OptionCombination(
                        code=f"{req.sku}-{idx:02d}", color=color, size=size, stock=0, status="disabled"
                    )
                )
                continue
            pos = active_pairs.index((color, size))
            qty = stocks[pos]
            options.append(
                OptionCombination(
                    code=f"{req.sku}-{idx:02d}",
                    color=color,
                    size=size,
                    stock=qty,
                    price_delta=req.extra_price.get(size, 0),
                    status="active" if qty > 0 else "soldout",
                )
            )

    notes: list[str] = []
    if req.disabled:
        notes.append(f"판매중지 조합 {len(req.disabled)}개는 등록 시 숨김 처리")
    if any(o.status == "soldout" for o in options):
        notes.append("재고 0 옵션이 있습니다 — 등록 시 '품절' 표시하거나 옵션을 숨기세요")
    if req.stock == 0:
        notes.append("총 재고 0장 — 등록만 하고 판매는 재고 동기화 후 시작")
    if len(active_pairs) > 12:
        notes.append(f"옵션 {len(active_pairs)}개 — 관리 부담이 큽니다. 컬러 3색 이하 권장")

    return OptionMatrix(
        options=options,
        active_count=sum(1 for o in options if o.status == "active"),
        disabled_count=sum(1 for o in options if o.status == "disabled"),
        total_stock=sum(o.stock for o in options),
        notes=notes,
    )


# ═══════════════════════════════════════════════
# 2) 등록 payload
# ═══════════════════════════════════════════════
class PayloadArgs(BaseModel):
    platform: Platform = Field(default="custom", description="cafe24 | imweb | custom")
    sku: str
    name: str = Field(description="판매 상품명(SEO 제목)")
    price: int = Field(ge=0)
    stock: int = Field(ge=0)
    category: str
    description: str = Field(default="", description="상세 설명(카피 합본)")
    meta_description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list, description="이미지 URL 목록")
    options: list[OptionCombination] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class MallPayload(BaseModel):
    platform: str
    payload: dict
    missing_required: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


_REQUIRED_BY_PLATFORM: dict[str, tuple[str, ...]] = {
    "cafe24": ("product_name", "price", "supply_price", "description", "category", "options"),
    "imweb": ("name", "price", "stock", "description", "options"),
    "custom": ("sku", "name", "price", "stock", "description"),
}


@tool(
    name="dev_product_payload",
    team=TeamName.DEV,
    description=(
        "승인된 상품 데이터를 몰별 등록 payload로 변환한다. "
        "cafe24/imweb/custom 키 이름 차이를 흡수하고 필수값 누락을 표시한다."
    ),
    args=PayloadArgs,
    returns="MallPayload(플랫폼·payload·필수값 누락·메모)",
    tags=("payload", "mall"),
)
def product_payload(req: PayloadArgs) -> MallPayload:
    options = [
        {"code": o.code, "color": o.color, "size": o.size, "stock": o.stock, "price_delta": o.price_delta}
        for o in req.options
        if o.status != "disabled"
    ]
    if req.platform == "cafe24":
        payload: dict = {
            "product_name": req.name,
            "price": str(req.price),
            "supply_price": str(req.price),
            "display": "T",
            "selling": "T",
            "description": req.description,
            "category": req.category,
            "options": options,
            "images": req.images,
            "seo": {"title": req.name, "description": req.meta_description, "keywords": ",".join(req.hashtags)},
        }
    elif req.platform == "imweb":
        payload = {
            "name": req.name,
            "price": req.price,
            "stock": req.stock,
            "category": req.category,
            "description": req.description,
            "options": options,
            "images": req.images,
            "tags": req.tags or req.hashtags,
        }
    else:
        payload = {
            "sku": req.sku,
            "name": req.name,
            "price": req.price,
            "stock": req.stock,
            "category": req.category,
            "description": req.description,
            "options": options,
            "images": req.images,
            "seo": {"title": req.name, "description": req.meta_description, "hashtags": req.hashtags},
        }

    missing = [key for key in _REQUIRED_BY_PLATFORM[req.platform] if not payload.get(key) and payload.get(key) != 0]
    notes: list[str] = []
    if not req.images:
        notes.append("이미지 URL 없음 — 에셋 생성 후 file_url 채워 재전송 필요")
    if req.price <= 0:
        notes.append("판매가 0원 — 등록 중단")
    return MallPayload(platform=req.platform, payload=payload, missing_required=missing, notes=notes)


# ═══════════════════════════════════════════════
# 3) 재고 임계치 알림
# ═══════════════════════════════════════════════
class StockAlertArgs(BaseModel):
    sku: str
    stock: int = Field(ge=0, description="현재 재고(장)")
    threshold: int = Field(default=5, ge=0, description="알림 임계치(장)")
    daily_sales: float = Field(default=0, ge=0, description="일평균 판매량")
    lead_time_days: int = Field(default=3, ge=0, description="사입 리드타임")


class StockAlert(BaseModel):
    level: str = Field(description="soldout | critical | low | ok")
    message: str
    action: str
    reorder_qty: int = 0


@tool(
    name="dev_stock_alert",
    team=TeamName.DEV,
    description=(
        "재고·일판매·리드타임으로 품절 임계 알림을 만들고, 판매중지·리오더·정상 중 "
        "무엇을 할지 정한다. 크론에서 SKU별로 호출하는 용도."
    ),
    args=StockAlertArgs,
    returns="StockAlert(단계·메시지·조치·리오더 수량)",
    tags=("stock", "alert"),
)
def stock_alert(req: StockAlertArgs) -> StockAlert:
    if req.stock <= 0:
        return StockAlert(
            level="soldout",
            message=f"{req.sku} 재고 0장 — 품절",
            action="몰에서 품절 처리 후 긴급 사입 요청",
            reorder_qty=max(req.threshold * 2, 10),
        )
    cover = round(req.stock / req.daily_sales, 1) if req.daily_sales > 0 else 999.0
    if req.stock <= req.threshold or (req.daily_sales > 0 and cover <= req.lead_time_days):
        need = (
            math.ceil(req.daily_sales * (req.lead_time_days + 7)) - req.stock
            if req.daily_sales > 0
            else req.threshold * 2
        )
        return StockAlert(
            level="critical",
            message=f"{req.sku} 재고 {req.stock}장 (소진 {cover}일)",
            action="대표님 알림 + 리오더 발주",
            reorder_qty=max(math.ceil(need / 10) * 10, 10),
        )
    if cover <= req.lead_time_days + 7:
        return StockAlert(
            level="low",
            message=f"{req.sku} 재고 {req.stock}장 (소진 {cover}일)",
            action="리오더 검토 알림",
            reorder_qty=0,
        )
    return StockAlert(level="ok", message=f"{req.sku} 재고 {req.stock}장 (소진 {cover}일)", action="정상")


#: 개발팀이 LLM에 바인딩하는 도구 목록.
TOOLS = [option_matrix, product_payload, stock_alert]
