"""라이브 오피스 UI·API 테스트.

`GET /`(웹 UI), `GET /workflows`(실행 목록), `GET /office/state`(회의실 상태)를 확인합니다.
외부 API 없이(mock LLM) 실제 런칭 → 승인 흐름까지 한 번 돌려 봅니다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

PRODUCT = {
    "sku": "MN-OUT-2611-777",
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


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_web_ui_is_served(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    body = res.text
    assert "라이브 오피스" in body
    assert "대표 승인 회의실" in body
    assert "staff.roster" in body
    assert "/office/state" in body
    assert "/workflows" in body


def test_office_state_shape(client: TestClient) -> None:
    body = client.get("/office/state").json()
    assert len(body["staff"]) == 7
    teams = {row["team"] for row in body["staff"]}
    assert teams == {"md", "design", "content", "qa", "dev", "marketing", "cs"}
    for row in body["staff"]:
        assert row["name"] and row["role"] and row["badge"]
        assert row["status"] in {"작업 중", "결재 대기", "완료", "대기 중"}
        assert row["task"]
        assert row["salary_monthly"] == 0
    assert body["speech"]["text"]
    assert body["speech"]["speaker"] in teams
    assert isinstance(body["activity"], list)
    assert len(body["pipeline"]) == 7
    assert body["room"]["title"] == "대표 승인 회의실"
    assert body["counts"]["teams"] == 7


def test_workflows_endpoint_shape(client: TestClient) -> None:
    body = client.get("/workflows").json()
    assert isinstance(body["workflows"], list)
    assert body["count"] == len(body["workflows"])
    assert body["pending_approval"] == len(body["pending"])
    assert body["stage_order"][0] == "md"
    assert body["stage_order"][-1] == "done"


def test_launch_appears_in_office_and_can_be_approved(client: TestClient) -> None:
    launched = client.post("/workflows/launch", json={"product": PRODUCT})
    assert launched.status_code == 200
    body = launched.json()
    assert body["status"] == "awaiting_approval"
    workflow_id = body["workflow_id"]

    listing = client.get("/workflows").json()
    runs = {run["workflow_id"]: run for run in listing["workflows"]}
    assert listing["count"] >= 1
    assert workflow_id in runs
    run = runs[workflow_id]
    assert run["sku"] == PRODUCT["sku"]
    assert run["stage"] == "approval"
    assert run["stage_label"] == "대표 승인"
    assert run["status"] == "awaiting_approval"
    assert run["selling_price"] > PRODUCT["cost_price"]
    assert run["qa_score"] is not None
    assert run["approval"]["title"]
    assert run["design"] and run["content"]
    assert any(item["workflow_id"] == workflow_id for item in listing["pending"])

    office = client.get("/office/state").json()
    statuses = {row["team"]: row["status"] for row in office["staff"]}
    assert statuses["qa"] == "결재 대기"
    assert statuses["md"] == "완료"
    assert office["counts"]["pending_approval"] >= 1
    assert office["speech"]["text"]
    assert office["pipeline"][4]["key"] == "approval"

    approved = client.post(
        f"/workflows/{workflow_id}/approval",
        json={"approved": True, "decided_by": "대표", "note": "테스트 승인"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "completed"

    after = {run["workflow_id"]: run for run in client.get("/workflows").json()["workflows"]}
    assert after[workflow_id]["status"] == "completed"
    assert after[workflow_id]["stage"] == "done"
    assert after[workflow_id]["progress"] == 100

    done_office = client.get("/office/state").json()
    assert all(row["status"] == "완료" or row["team"] == "cs" for row in done_office["staff"])
