"""쇼핑몰 플랫폼 어댑터.

개발팀은 이 인터페이스만 알면 되고, 실제 몰이 카페24인지 아임웹인지 자체몰인지는
`MALL_PLATFORM` 환경변수로 결정됩니다. 새 플랫폼을 붙일 때는 `MallAdapter`를
상속해 세 메서드만 구현하고 `get_adapter()`에 등록하세요.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from app.shared.config import Settings, get_settings
from app.shared.models import ContentCopy, DesignPlan, ProductItem


class MallIntegrationError(RuntimeError):
    """쇼핑몰 API 호출 실패."""


class MallCredentialsMissing(MallIntegrationError):
    """API 키/토큰이 설정되지 않음."""


@dataclass(slots=True)
class MallProductRef:
    """몰에 등록된 상품 참조."""

    platform: str
    mall_product_id: str
    product_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class MallAdapter(ABC):
    """모든 쇼핑몰 어댑터의 공통 인터페이스."""

    platform: ClassVar[str] = "base"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # ── 공통 HTTP ──────────────────────────────
    def _headers(self) -> dict[str, str]:
        key = self.settings.mall_api_key
        if key is None or not key.get_secret_value():
            raise MallCredentialsMissing(
                f"{self.platform}: MALL_API_KEY가 설정되지 않았습니다. .env를 확인하세요."
            )
        return {
            "Authorization": f"Bearer {key.get_secret_value()}",
            "Content-Type": "application/json",
        }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.settings.mall_api_base_url.rstrip("/"),
            headers=self._headers(),
            timeout=httpx.Timeout(20.0),
        )

    # ── 기능 계약 ──────────────────────────────
    @abstractmethod
    async def register_product(
        self,
        product: ProductItem,
        copy: ContentCopy,
        design: DesignPlan,
        selling_price: int,
    ) -> MallProductRef:
        """상품을 몰에 등록하고 상품 ID/URL을 돌려준다."""

    @abstractmethod
    async def update_inventory(self, sku: str, stock: int) -> dict[str, Any]:
        """SKU 재고를 동기화한다."""

    @abstractmethod
    async def fetch_orders(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """주문 목록을 조회한다 (CS/운영팀이 사용)."""


def _payload(product: ProductItem, copy: ContentCopy, design: DesignPlan, selling_price: int) -> dict[str, Any]:
    """플랫폼 공통 전송 바디. 각 어댑터가 자기 스펙으로 변환한다."""
    return {
        "sku": product.sku,
        "name": copy.seo_title or product.name,
        "price": selling_price,
        "stock": product.stock,
        "category": product.category,
        "options": {"sizes": product.size_options, "colors": product.color_options},
        "description": "\n\n".join(
            filter(
                None,
                [
                    copy.hook,
                    copy.fit_copy,
                    copy.material_copy,
                    copy.coordi_copy,
                    copy.size_guide_copy,
                    copy.care_copy,
                ],
            )
        ),
        "images": [a.file_url for a in design.assets if a.file_url],
        "seo": {"title": copy.seo_title, "description": copy.meta_description, "hashtags": copy.hashtags},
    }


class Cafe24Adapter(MallAdapter):
    """카페24 Admin API 스텁.

    실제 연동 시: OAuth 토큰 발급(`/api/v2/admin/oauth/token`) → 상품 생성
    (`POST /api/v2/admin/products`) → 재고(`PUT /api/v2/admin/inventory`) 순.
    """

    platform = "cafe24"

    async def register_product(self, product, copy, design, selling_price) -> MallProductRef:
        body = _payload(product, copy, design, selling_price)
        async with self._client() as client:
            try:
                res = await client.post("/api/v2/admin/products", json=body)
                res.raise_for_status()
            except httpx.HTTPError as exc:  # TODO: 429/5xx 재시도 정책 추가
                raise MallIntegrationError(f"카페24 상품 등록 실패: {exc}") from exc
            data = res.json()
        product_no = str(data.get("product", {}).get("product_no", ""))
        return MallProductRef(
            platform=self.platform,
            mall_product_id=product_no,
            product_url=f"https://{self.settings.mall_shop_id}.cafe24.com/product/detail.html?product_no={product_no}",
            raw=data,
        )

    async def update_inventory(self, sku: str, stock: int) -> dict[str, Any]:
        async with self._client() as client:
            res = await client.put("/api/v2/admin/inventory", json={"sku": sku, "quantity": stock})
            res.raise_for_status()
            return res.json()

    async def fetch_orders(self, since: datetime | None = None) -> list[dict[str, Any]]:
        params = {"start_date": (since or datetime.now(UTC)).strftime("%Y-%m-%d")}
        async with self._client() as client:
            res = await client.get("/api/v2/admin/orders", params=params)
            res.raise_for_status()
            return res.json().get("orders", [])


class ImwebAdapter(MallAdapter):
    """아임웹 API 스텁 (상품 등록 / 재고 / 주문)."""

    platform = "imweb"

    async def register_product(self, product, copy, design, selling_price) -> MallProductRef:
        body = _payload(product, copy, design, selling_price)
        async with self._client() as client:
            try:
                res = await client.post("/v1/shop/products", json=body)
                res.raise_for_status()
            except httpx.HTTPError as exc:
                raise MallIntegrationError(f"아임웹 상품 등록 실패: {exc}") from exc
            data = res.json()
        pid = str(data.get("data", {}).get("id", ""))
        return MallProductRef(platform=self.platform, mall_product_id=pid, raw=data)

    async def update_inventory(self, sku: str, stock: int) -> dict[str, Any]:
        async with self._client() as client:
            res = await client.put(f"/v1/shop/products/{sku}/stock", json={"stock": stock})
            res.raise_for_status()
            return res.json()

    async def fetch_orders(self, since: datetime | None = None) -> list[dict[str, Any]]:
        async with self._client() as client:
            res = await client.get("/v1/shop/orders")
            res.raise_for_status()
            return res.json().get("data", [])


class CustomAdapter(MallAdapter):
    """자체몰(REST) 스텁. 우리가 정한 규격을 그대로 노출하는 가장 단순한 형태."""

    platform = "custom"

    async def register_product(self, product, copy, design, selling_price) -> MallProductRef:
        body = _payload(product, copy, design, selling_price)
        async with self._client() as client:
            try:
                res = await client.post("/products", json=body)
                res.raise_for_status()
            except httpx.HTTPError as exc:
                raise MallIntegrationError(f"자체몰 상품 등록 실패: {exc}") from exc
            data = res.json()
        pid = str(data.get("id") or product.sku)
        return MallProductRef(
            platform=self.platform,
            mall_product_id=pid,
            product_url=data.get("url"),
            raw=data,
        )

    async def update_inventory(self, sku: str, stock: int) -> dict[str, Any]:
        async with self._client() as client:
            res = await client.post("/inventory", json={"sku": sku, "stock": stock})
            res.raise_for_status()
            return res.json()

    async def fetch_orders(self, since: datetime | None = None) -> list[dict[str, Any]]:
        params = {"since": since.isoformat()} if since else {}
        async with self._client() as client:
            res = await client.get("/orders", params=params)
            res.raise_for_status()
            return res.json().get("orders", [])


_ADAPTERS: dict[str, type[MallAdapter]] = {
    "cafe24": Cafe24Adapter,
    "imweb": ImwebAdapter,
    "custom": CustomAdapter,
}


def get_adapter(settings: Settings | None = None) -> MallAdapter:
    s = settings or get_settings()
    try:
        return _ADAPTERS[s.mall_platform](s)
    except KeyError as exc:  # pragma: no cover - Literal로 이미 막혀 있음
        raise MallIntegrationError(f"지원하지 않는 플랫폼: {s.mall_platform}") from exc
