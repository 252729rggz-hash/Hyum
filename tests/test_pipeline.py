"""7팀 파이프라인 스모크 테스트.

`pytest -q` 로 실행합니다. 외부 API 없이(LLM_PROVIDER=mock, MALL_API_KEY 없음)
프롬프트·도구 등록, 마진 계산, 검수 규칙, FastAPI 워크플로 전체를 확인합니다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.shared.models import ProductItem, TeamName
from app.shared.prompting import prompt_for
from app.shared.tooling import ToolInputError, dispatch, openai_tools, tools_for
from app.teams.md.tools import price_quote
from app.teams.qa.tools import scan_claims

PRODUCT = {
    "sku": "MN-OUT-2611-001",
    "name": "에어 턴 오버핏 바람막이",
    "category": "남성 아우터 > 바람막이",
    "fit": "oversized",
    "material": "폴리에스터 100%",
    "color_options": ["블랙", "차콜", "아이보리"],
    "size_options": ["M", "L", "XL", "2XL"],
    "cost_price": 21000,
    "stock": 45,
    "supplier": "동대문 A도매",
    "keywords": ["남자 바람막이", "오버핏 아우터"],
    "country_of_origin": "베트남",
}

TEAMS = [TeamName.MD, TeamName.DESIGN, TeamName.CONTENT, TeamName.QA, TeamName.DEV, TeamName.MARKETING, TeamName.CS]


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_every_team_has_prompt_and_tools() -> None:
    for team in TEAMS:
        bundle = prompt_for(team)
        assert bundle is not None, f"{team} 프롬프트 미등록"
        assert len(bundle.system) > 500, f"{team} 시스템 프롬프트가 너무 짧음"
        assert "$" in bundle.user_template
        assert tools_for(team), f"{team} 도구 없음"


def test_domain_keywords_in_prompts() -> None:
    expected = {
        TeamName.MD: "반품충당금",
        TeamName.DESIGN: "후킹 인트로",
        TeamName.CONTENT: "고시정보",
        TeamName.QA: "표시광고법",
        TeamName.DEV: "payload",
        TeamName.MARKETING: "손익분기 ROAS",
        TeamName.CS: "에스컬레이션",
    }
    for team, keyword in expected.items():
        bundle = prompt_for(team)
        assert bundle is not None
        assert keyword in bundle.system, f"{team} 프롬프트에 '{keyword}' 없음"


def test_tools_are_llm_bindable_and_team_scoped() -> None:
    schemas = openai_tools(TeamName.MD)
    assert schemas and all(s["type"] == "function" for s in schemas)
    assert all(s["function"]["parameters"]["properties"] for s in schemas)

    result = dispatch(TeamName.MD, "md_price_quote", {"cost_price": 21000, "target_margin_rate": 0.4})
    assert result.selling_price > 21000
    with pytest.raises(ToolInputError):
        dispatch(TeamName.MD, "qa_scan_claims", {"text": "최고급"})


def test_pricing_reflects_fees_and_reserve() -> None:
    quote = price_quote(
        cost_price=21000,
        shipping_cost=3000,
        platform_fee_rate=0.035,
        payment_fee_rate=0.018,
        return_reserve_rate=0.05,
        vat_rate=0.1,
        target_margin_rate=0.4,
    )
    assert quote.payment_fee > 0
    assert quote.return_reserve > 0
    assert quote.net_profit > 0
    assert abs(quote.margin_rate - 0.4) < 0.02
    assert quote.vat_amount == round(quote.selling_price * 0.1 / 1.1)


def test_claim_scanner_rules() -> None:
    assert not scan_claims(text="최고급 원단으로 완벽한 핏").passed
    assert not scan_claims(text="100% 만족 보장").passed
    assert not scan_claims(text="방수 기능").passed
    assert scan_claims(text="폴리에스터 100% 소재").passed
    assert scan_claims(text="어깨선은 안정적으로 떨어집니다").passed


def test_workflow_launch_and_approve(client: TestClient) -> None:
    res = client.post("/workflows/launch", json={"product": PRODUCT})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "awaiting_approval"
    assert body["qa_report"]["passed"] is True
    assert body["approval"]["payload"]["selling_price"] > PRODUCT["cost_price"]

    approved = client.post(
        f"/workflows/{body['workflow_id']}/approval",
        json={"approved": True, "decided_by": "대표", "note": "등록 진행"},
    )
    assert approved.status_code == 200
    result = approved.json()
    assert result["status"] == "completed"
    assert result["result"]["deployment"]["simulated"] is True
    assert result["result"]["marketing"]["channels"] == ["meta", "naver", "instagram_organic"]


def test_workflow_rejects_margin_inversion(client: TestClient) -> None:
    product = {**PRODUCT, "sku": "MN-BAD-001", "selling_price": 10000, "cost_price": 30000}
    body = client.post("/workflows/launch", json={"product": product}).json()
    assert body["status"] == "qa_blocked"
    assert not body["qa_report"]["passed"]
    assert any("PRICE" in item for item in body["qa_report"]["feedback"])


def test_team_catalog_endpoint(client: TestClient) -> None:
    body = client.get("/teams/catalog").json()
    assert {row["team"] for row in body["teams"]} == {str(t) for t in TEAMS}
    assert len(body["tools"]) >= 30


def test_product_item_accepts_origin() -> None:
    item = ProductItem.model_validate(PRODUCT)
    assert item.country_of_origin == "베트남"
