"""애플리케이션 설정. .env 또는 실제 환경 변수에서 읽습니다."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """모든 팀이 공유하는 설정값.

    값 우선순위: 생성자 인자 > 환경 변수 > .env 파일 > 아래 기본값.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── 앱 ─────────────────────────────────────
    app_name: str = "mens-mall-agents"
    app_env: Literal["local", "dev", "prod"] = "local"
    log_level: str = "INFO"
    api_prefix: str = ""

    # ── LLM ────────────────────────────────────
    llm_provider: Literal["mock", "openai", "anthropic"] = "mock"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 60.0
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    # ── 저장소 ─────────────────────────────────
    database_url: str = "postgresql+psycopg://mall:mall@localhost:5432/mall"
    redis_url: str = "redis://localhost:6379/0"

    # ── 쇼핑몰 연동 ────────────────────────────
    mall_platform: Literal["cafe24", "imweb", "custom"] = "custom"
    mall_api_base_url: str = "https://mall.example.com/api"
    mall_shop_id: str | None = None
    mall_api_key: SecretStr | None = None
    mall_client_id: str | None = None
    mall_client_secret: SecretStr | None = None

    # ── 운영 / 승인 ────────────────────────────
    approval_webhook_url: str | None = None
    approval_timeout_hours: int = 24
    qa_max_revisions: int = Field(default=2, ge=0, le=10)

    # ── 가격 계산 기본값 ───────────────────────
    default_target_margin_rate: float = Field(default=0.55, gt=0, lt=1)
    platform_fee_rate: float = Field(default=0.035, ge=0, lt=1)
    payment_fee_rate: float = Field(default=0.018, ge=0, lt=1, description="PG 결제 수수료율(결제액 기준)")
    return_reserve_rate: float = Field(default=0.05, ge=0, lt=1, description="반품·불량 충당금 비율(판매가 기준)")
    default_shipping_fee: int = Field(default=3000, ge=0)
    vat_rate: float = Field(default=0.1, ge=0, lt=1)
    minimum_margin_rate: float = Field(default=0.25, ge=0, lt=1)
    monthly_fixed_cost: int = Field(default=0, ge=0, description="월 고정비(광고·툴). 손익분기 수량 계산용")
    initial_order_multiplier: float = Field(default=1.6, gt=0, description="예상 판매량 대비 초도 사입 배수")

    @property
    def is_production(self) -> bool:
        return self.app_env == "prod"


@lru_cache
def get_settings() -> Settings:
    """프로세스당 한 번만 파싱한 설정 객체를 돌려줍니다."""
    return Settings()
