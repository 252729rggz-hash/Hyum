"""FastAPI 진입점.

- `GET  /`                            : 라이브 오피스 웹 UI (`app/web/index.html`)
- `GET  /health`                      : 헬스체크
- `GET  /workflows`                   : 실행한 워크플로 전체 목록 (대시보드·대표 할 일)
- `GET  /office/state`                : 라이브 오피스 상태 (팀장 7명·회의실·활동 로그)
- `POST /workflows/launch`            : 상품 1건으로 워크플로 시작 (승인 대기에서 멈춤)
- `POST /workflows/{id}/approval`     : 대표님 승인/반려로 워크플로 재개
- `GET  /workflows/{id}`              : 현재 상태 조회
- `GET  /teams/catalog`               : 7개 팀의 프롬프트 요약과 바인딩된 도구 스키마

라이브 오피스 UI는 이 프로세스의 인메모리 저장소(`_WORKFLOWS`, `_ACTIVITY`)를 읽습니다.
서버를 재시작하면 실행 목록과 활동 로그도 함께 초기화됩니다(체크포인터와 같은 수명).
"""

from __future__ import annotations

import logging
import re
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from langgraph.types import Command

from app import __version__
from app.integrations.notifications import notify_approval
from app.orchestrator.graph import get_graph
from app.orchestrator.state import initial_state
from app.shared.config import get_settings
from app.shared.models import (
    ApprovalDecision,
    ApprovalRequest,
    ContentCopy,
    DesignPlan,
    DevDeployment,
    MDPlan,
    ProductItem,
    QAReport,
    WorkflowLaunchRequest,
    WorkflowLaunchResponse,
    WorkflowStatus,
)
from app.teams import all_tools, team_catalog

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("mall.api")

app = FastAPI(
    title="남성 보세몰 AI 직원 시스템",
    version=__version__,
    description="MD → 디자인 → 콘텐츠 → 검수 → 대표 승인 → 개발 → 마케팅 오케스트레이션 API",
)

WEB_INDEX = Path(__file__).resolve().parent / "web" / "index.html"


# ═══════════════════════════════════════════════
# 라이브 오피스 상태 저장소 (인메모리)
# ═══════════════════════════════════════════════
def _now() -> datetime:
    return datetime.now(UTC)


_STARTED_AT = _now()
_MAX_WORKFLOWS = 200

#: workflow_id → 대시보드/할 일 탭에 그대로 내보내는 실행 요약.
_WORKFLOWS: dict[str, dict[str, Any]] = {}
#: 라이브 오피스 활동 피드 (오래된 것부터).
_ACTIVITY: deque[dict[str, Any]] = deque(maxlen=120)

STAGE_ORDER: tuple[str, ...] = ("md", "design", "content", "qa", "approval", "dev", "marketing", "done")
STAGE_LABELS: dict[str, str] = {
    "md": "상품기획",
    "design": "디자인",
    "content": "콘텐츠",
    "qa": "검수",
    "approval": "대표 승인",
    "dev": "개발·등록",
    "marketing": "마케팅",
    "done": "완료",
    "blocked": "확인 필요",
    "rejected": "반려",
}
_STAGE_PROGRESS: dict[str, int] = {
    "md": 10,
    "design": 25,
    "content": 40,
    "qa": 55,
    "approval": 70,
    "dev": 85,
    "marketing": 95,
    "done": 100,
    "blocked": 55,
    "rejected": 60,
}

TEAM_SEQUENCE: tuple[str, ...] = ("md", "design", "content", "qa", "dev", "marketing", "cs")
_STAGE_TEAM_INDEX: dict[str, int] = {
    "md": 0,
    "design": 1,
    "content": 2,
    "qa": 3,
    "approval": 3,
    "blocked": 3,
    "rejected": 3,
    "dev": 4,
    "marketing": 5,
    "done": 6,
}

#: 회의실 픽셀 캐릭터 설정. slot은 프론트엔드 좌석 번호(1~7, 대표는 별도).
STAFF: tuple[dict[str, Any], ...] = (
    {
        "team": "md",
        "team_label": "상품기획",
        "name": "송민재",
        "role": "MD",
        "badge": "MD",
        "avatar": "🧮",
        "slot": 4,
        "color": "#f4a7b9",
        "hair": "#3b2f2a",
        "shirt": "#f4a7b9",
        "pants": "#5a4a5e",
    },
    {
        "team": "design",
        "team_label": "디자인",
        "name": "최아름",
        "role": "디자인",
        "badge": "디자인",
        "avatar": "🎨",
        "slot": 1,
        "color": "#9ecbe8",
        "hair": "#4a3b32",
        "shirt": "#9ecbe8",
        "pants": "#45516b",
    },
    {
        "team": "content",
        "team_label": "콘텐츠",
        "name": "김세리",
        "role": "콘텐츠",
        "badge": "콘텐츠",
        "avatar": "✍️",
        "slot": 2,
        "color": "#f6d48f",
        "hair": "#2f2a28",
        "shirt": "#f6d48f",
        "pants": "#5e4a3a",
    },
    {
        "team": "qa",
        "team_label": "검수",
        "name": "한도빈",
        "role": "검수",
        "badge": "QA",
        "avatar": "🔍",
        "slot": 3,
        "color": "#b7e4c7",
        "hair": "#3b2f2a",
        "shirt": "#b7e4c7",
        "pants": "#3f5148",
    },
    {
        "team": "dev",
        "team_label": "개발",
        "name": "이지혜",
        "role": "개발",
        "badge": "DEV",
        "avatar": "💻",
        "slot": 5,
        "color": "#c3b4ee",
        "hair": "#2b2b33",
        "shirt": "#c3b4ee",
        "pants": "#3d3a52",
    },
    {
        "team": "marketing",
        "team_label": "마케팅",
        "name": "박지훈",
        "role": "마케팅",
        "badge": "MKT",
        "avatar": "📣",
        "slot": 6,
        "color": "#f8b26a",
        "hair": "#4a362e",
        "shirt": "#f8b26a",
        "pants": "#4c3a30",
    },
    {
        "team": "cs",
        "team_label": "고객응대",
        "name": "윤하늘",
        "role": "CS",
        "badge": "CS",
        "avatar": "🎧",
        "slot": 7,
        "color": "#e9e3cf",
        "hair": "#3b2f2a",
        "shirt": "#efe8d4",
        "pants": "#4a4a55",
    },
)

CEO: dict[str, Any] = {
    "team": "ceo",
    "team_label": "대표",
    "name": "현민",
    "role": "대표",
    "avatar": "👑",
    "color": "#3e4a6b",
    "hair": "#26202a",
    "shirt": "#3e4a6b",
    "pants": "#2c3247",
}

#: 단계별 팀별 업무 문구. `{name}` 자리에 상품명이 들어간다.
_TASK_TEMPLATES: dict[str, dict[str, str]] = {
    "md": {
        "working": "'{name}' 마진·초도 발주 계산",
        "done": "'{name}' 판매가·발주 확정",
        "idle": "신상품 사입가·마진 계산 대기",
    },
    "design": {
        "working": "'{name}' 상세페이지 레이아웃 설계",
        "done": "'{name}' 상세 컷·배너 시안 완료",
        "idle": "상세페이지 템플릿 정리 중",
    },
    "content": {
        "working": "'{name}' SEO 카피·고시정보 작성",
        "done": "'{name}' 카피·릴스 대본 완료",
        "idle": "카피 라이브러리 정리 중",
    },
    "qa": {
        "working": "'{name}' 표시광고법·가격 검수",
        "done": "'{name}' 검수 통과",
        "idle": "검수 체크리스트 점검 중",
    },
    "dev": {
        "working": "'{name}' payload 생성·재고 동기화",
        "done": "'{name}' 몰 등록 완료",
        "idle": "상품 등록 양식 대기 중",
    },
    "marketing": {
        "working": "'{name}' 메타·네이버 캠페인 설계",
        "done": "'{name}' 캠페인 세팅 완료",
        "idle": "지난 캠페인 ROAS 복기 중",
    },
    "cs": {
        "working": "'{name}' 교환·반품 응대 중",
        "done": "'{name}' 응대 종료",
        "idle": "응대 템플릿 다듬는 중",
    },
}


def _staff(team: str) -> dict[str, Any]:
    for row in STAFF:
        if row["team"] == team:
            return row
    return STAFF[0]


def _task(team: str, kind: str, name: str) -> str:
    template = _TASK_TEMPLATES.get(team, {}).get(kind, "")
    return template.format(name=name) if template else ""


def _log_activity(
    message: str,
    *,
    team: str = "orchestrator",
    kind: str = "info",
    at: datetime | None = None,
) -> None:
    _ACTIVITY.append(
        {
            "at": (at or _now()).isoformat(),
            "team": team,
            "message": message,
            "kind": kind,
        }
    )


def _seed_activity() -> None:
    """서버를 켰을 때 빈 피드 대신 보여줄 기본 로그 (실제 상태 그대로)."""
    if _ACTIVITY:
        return
    base = _now()
    _log_activity(
        "🖥️ 라이브 오피스 가동 — 팀장 7명 접속 완료",
        team="orchestrator",
        kind="system",
        at=base - timedelta(minutes=9),
    )
    _log_activity(
        "☕ 회의실 정리 완료 — 대표님 오시면 바로 시작합니다",
        team="cs",
        kind="system",
        at=base - timedelta(minutes=6),
    )
    _log_activity(
        "📋 오늘 결재 대기 0건 — 대시보드에서 샘플 상품을 런칭해 보세요",
        team="orchestrator",
        kind="system",
        at=base - timedelta(minutes=3),
    )


_seed_activity()


def _record_logs(workflow_id: str, values: dict[str, Any]) -> None:
    """워크플로 로그 중 아직 피드에 올리지 않은 줄만 활동 피드로 옮긴다."""
    logs = [str(line) for line in (values.get("log") or [])]
    seen = int(_WORKFLOWS.get(workflow_id, {}).get("_log_count", 0))
    for line in logs[seen:]:
        team = "orchestrator"
        message = line
        match = re.match(r"\[([A-Za-z_]+)\]\s*", line)
        if match:
            team, message = match.group(1), line[match.end() :]
        _log_activity(message, team=team, kind="log")


def _derive_stage(values: dict[str, Any], awaiting: bool) -> str:
    status = str(values.get("status") or "")
    if status == str(WorkflowStatus.COMPLETED):
        return "done"
    if status == str(WorkflowStatus.REJECTED):
        return "rejected"
    if status == str(WorkflowStatus.QA_BLOCKED):
        return "blocked"
    if values.get("marketing_plan"):
        return "done"
    if values.get("human_approved") and values.get("dev_deployed"):
        return "dev"
    if awaiting or status == str(WorkflowStatus.AWAITING_APPROVAL):
        return "approval"
    if values.get("qa_report"):
        return "approval"
    if values.get("content_copy"):
        return "qa"
    if values.get("design_assets"):
        return "content"
    if values.get("md_plan"):
        return "design"
    return "md"


def _upsert_workflow(
    workflow_id: str,
    values: dict[str, Any],
    *,
    awaiting: bool = False,
    approval: ApprovalRequest | None = None,
) -> dict[str, Any]:
    """그래프 상태 → 대시보드/할 일 탭 레코드 (인메모리)."""
    existing = _WORKFLOWS.get(workflow_id, {})
    _record_logs(workflow_id, values)

    product = ProductItem.model_validate(values["product"]) if values.get("product") else None
    md = MDPlan.model_validate(values["md_plan"]) if values.get("md_plan") else None
    design = DesignPlan.model_validate(values["design_assets"]) if values.get("design_assets") else None
    copy = ContentCopy.model_validate(values["content_copy"]) if values.get("content_copy") else None
    qa = QAReport.model_validate(values["qa_report"]) if values.get("qa_report") else None
    deploy = DevDeployment.model_validate(values["dev_deployed"]) if values.get("dev_deployed") else None
    if values.get("approval_request") is not None:
        approval = ApprovalRequest.model_validate(values["approval_request"])

    stage = _derive_stage(values, awaiting)
    status = str(values.get("status") or str(WorkflowStatus.PENDING))
    if awaiting:
        status = str(WorkflowStatus.AWAITING_APPROVAL)

    selling_price = md.pricing.selling_price if md else (product.selling_price if product else None)
    created_at = existing.get("created_at") or _now().isoformat()

    record: dict[str, Any] = {
        "workflow_id": workflow_id,
        "sku": product.sku if product else existing.get("sku", ""),
        "name": product.name if product else existing.get("name", workflow_id),
        "category": product.category if product else existing.get("category", ""),
        "status": status,
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, stage),
        "progress": _STAGE_PROGRESS.get(stage, 0),
        "created_at": created_at,
        "updated_at": _now().isoformat(),
        "cost_price": product.cost_price if product else existing.get("cost_price"),
        "selling_price": selling_price,
        "margin_rate": md.pricing.margin_rate if md else existing.get("margin_rate"),
        "net_profit": md.pricing.net_profit if md else existing.get("net_profit"),
        "break_even_units": md.pricing.break_even_units if md else None,
        "qa_score": qa.score if qa else existing.get("qa_score"),
        "qa_passed": qa.passed if qa else existing.get("qa_passed"),
        "qa_feedback": list(qa.feedback) if qa else existing.get("qa_feedback", []),
        "approval": approval.model_dump(mode="json") if approval else existing.get("approval"),
        "design": (
            {
                "concept": design.concept,
                "mood_keywords": list(design.mood_keywords),
                "assets": [{"kind": a.kind, "name": a.name, "size": f"{a.width}x{a.height}"} for a in design.assets],
            }
            if design
            else existing.get("design")
        ),
        "content": (
            {
                "seo_title": copy.seo_title,
                "hook": copy.hook,
                "hashtags": list(copy.hashtags),
                "disclosure_missing": copy.disclosure.missing_required() if copy.disclosure else [],
            }
            if copy
            else existing.get("content")
        ),
        "inventory": {"stock": product.stock, "supplier": product.supplier} if product else existing.get("inventory"),
        "deployed": deploy.model_dump(mode="json") if deploy else existing.get("deployed"),
        "note": values.get("note", existing.get("note", "")),
        "_log_count": len(values.get("log") or []),
    }
    _WORKFLOWS[workflow_id] = record
    if len(_WORKFLOWS) > _MAX_WORKFLOWS:
        oldest = min(_WORKFLOWS, key=lambda key: _WORKFLOWS[key]["created_at"])
        _WORKFLOWS.pop(oldest, None)
    return record


def _public(record: dict[str, Any]) -> dict[str, Any]:
    """`_`로 시작하는 내부 필드를 빼고 내보낸다."""
    return {key: value for key, value in record.items() if not key.startswith("_")}


def _sorted_runs() -> list[dict[str, Any]]:
    return sorted(_WORKFLOWS.values(), key=lambda row: row["created_at"], reverse=True)


def _team_status(active: dict[str, Any] | None) -> tuple[dict[str, str], dict[str, str]]:
    """가장 최근 실행을 기준으로 7개 팀의 상태·업무 문구를 만든다."""
    statuses = {team: "대기 중" for team in TEAM_SEQUENCE}
    tasks = {team: _task(team, "idle", "") for team in TEAM_SEQUENCE}
    if not active:
        return statuses, tasks

    stage = str(active.get("stage") or "md")
    name = str(active.get("name") or "신상품")

    if stage == "approval":
        for team in TEAM_SEQUENCE[:3]:
            statuses[team] = "완료"
            tasks[team] = _task(team, "done", name)
        statuses["qa"] = "결재 대기"
        tasks["qa"] = f"'{name}' 등록 승인 대기"
        return statuses, tasks

    if stage == "blocked":
        for team in TEAM_SEQUENCE[:3]:
            statuses[team] = "완료"
            tasks[team] = _task(team, "done", name)
        statuses["qa"] = "결재 대기"
        tasks["qa"] = f"'{name}' 검수 반려 — 대표 확인 필요"
        return statuses, tasks

    if stage == "rejected":
        for team in TEAM_SEQUENCE[:4]:
            statuses[team] = "완료"
            tasks[team] = _task(team, "done", name)
        tasks["qa"] = f"'{name}' 대표님 반려 처리"
        return statuses, tasks

    if stage == "done":
        for team in TEAM_SEQUENCE[:6]:
            statuses[team] = "완료"
            tasks[team] = _task(team, "done", name)
        statuses["cs"] = "작업 중"
        tasks["cs"] = _task("cs", "working", name)
        return statuses, tasks

    index = _STAGE_TEAM_INDEX.get(stage, 0)
    for team in TEAM_SEQUENCE[:index]:
        statuses[team] = "완료"
        tasks[team] = _task(team, "done", name)
    current = TEAM_SEQUENCE[min(index, len(TEAM_SEQUENCE) - 1)]
    statuses[current] = "작업 중"
    tasks[current] = _task(current, "working", name)
    return statuses, tasks


def _speech(
    runs: list[dict[str, Any]],
    pending: list[dict[str, Any]],
    active: dict[str, Any] | None,
) -> dict[str, Any]:
    """회의실 말풍선: 지금 대표님이 알아야 할 한마디."""
    if pending:
        speaker = _staff("qa")
        count = len(pending)
        text = f"대표님, 오늘 결재하실 건 {count}건이에요." if count > 1 else "대표님, 오늘 결재하실 건 이거 하나예요."
        return {"speaker": "qa", "name": speaker["name"], "text": text, "kind": "approval"}

    if active:
        stage = str(active.get("stage") or "md")
        name = str(active.get("name") or "신상품")
        if stage == "blocked":
            speaker = _staff("qa")
            return {
                "speaker": "qa",
                "name": speaker["name"],
                "text": f"'{name}' 검수에서 막혔어요. 대표님 확인 부탁드려요.",
                "kind": "alert",
            }
        if stage == "done":
            speaker = _staff("marketing")
            return {
                "speaker": "marketing",
                "name": speaker["name"],
                "text": f"'{name}' 몰에 등록 끝났어요. 이제 광고만 남았습니다!",
                "kind": "done",
            }
        if stage in _STAGE_TEAM_INDEX and stage not in {"approval", "rejected"}:
            team = TEAM_SEQUENCE[min(_STAGE_TEAM_INDEX[stage], len(TEAM_SEQUENCE) - 1)]
            speaker = _staff(team)
            return {
                "speaker": team,
                "name": speaker["name"],
                "text": f"'{name}' {STAGE_LABELS.get(stage, stage)} 단계 진행 중이에요. 잠시만요!",
                "kind": "working",
            }

    if runs:
        speaker = _staff("cs")
        return {
            "speaker": "cs",
            "name": speaker["name"],
            "text": "대표님, 오늘 결재는 다 끝났어요. 새 상품 한 건 더 넣어볼까요?",
            "kind": "idle",
        }

    speaker = _staff("md")
    return {
        "speaker": "md",
        "name": speaker["name"],
        "text": "대표님, 오늘은 결재할 게 없어요. 새 상품 한 건 넣어볼까요?",
        "kind": "idle",
    }


def _pipeline(active: dict[str, Any] | None) -> list[dict[str, str]]:
    stages = ("md", "design", "content", "qa", "approval", "dev", "marketing")
    if not active:
        return [{"key": key, "label": STAGE_LABELS[key], "state": "wait"} for key in stages]

    stage = str(active.get("stage") or "md")
    done_until = {"done": 7, "rejected": 4}.get(stage)
    if done_until is None:
        done_until = _STAGE_TEAM_INDEX.get(stage, 0) + 1 if stage in STAGE_ORDER else 0
    steps: list[dict[str, str]] = []
    for index, key in enumerate(stages):
        if index < done_until:
            state = "done"
        elif index == done_until:
            state = "active"
        else:
            state = "wait"
        steps.append({"key": key, "label": STAGE_LABELS[key], "state": state})
    if stage == "done":
        steps = [{"key": key, "label": STAGE_LABELS[key], "state": "done"} for key in stages]
    return steps


def _brief(record: dict[str, Any]) -> dict[str, Any]:
    approval = record.get("approval") or {}
    return {
        "workflow_id": record["workflow_id"],
        "sku": record.get("sku"),
        "name": record.get("name"),
        "status": record.get("status"),
        "stage_label": record.get("stage_label"),
        "selling_price": record.get("selling_price"),
        "margin_rate": record.get("margin_rate"),
        "qa_score": record.get("qa_score"),
        "title": approval.get("title") or f"'{record.get('name')}' 승인 요청",
        "risks": list(approval.get("risks") or []),
        "created_at": record.get("created_at"),
    }


# ═══════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════
def _thread_config(workflow_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": workflow_id}}


def _interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    """invoke 결과에서 interrupt 값을 꺼낸다."""
    interrupts = result.get("__interrupt__") or ()
    if not interrupts:
        return None
    first = interrupts[0]
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else {"value": value}


def _summary(values: dict[str, Any]) -> dict[str, Any]:
    """응답에 담을 핵심 요약만 추린다 (전체 상태는 GET으로 조회)."""
    out: dict[str, Any] = {"status": str(values.get("status", ""))}
    if values.get("product"):
        product = ProductItem.model_validate(values["product"])
        out.update({"sku": product.sku, "name": product.name})
    if values.get("md_plan"):
        md = MDPlan.model_validate(values["md_plan"])
        out["pricing"] = md.pricing.model_dump(mode="json")
        out["trend_keywords"] = md.trend_keywords
    if values.get("design_assets"):
        design = DesignPlan.model_validate(values["design_assets"])
        out["design"] = {"concept": design.concept, "assets": [a.kind for a in design.assets]}
    if values.get("content_copy"):
        copy = ContentCopy.model_validate(values["content_copy"])
        out["seo_title"] = copy.seo_title
    if values.get("qa_report"):
        qa = QAReport.model_validate(values["qa_report"])
        out["qa"] = {"passed": qa.passed, "score": qa.score, "feedback": qa.feedback}
    if values.get("dev_deployed"):
        dep = DevDeployment.model_validate(values["dev_deployed"])
        out["deployment"] = dep.model_dump(mode="json")
    if values.get("marketing_plan"):
        plan = values["marketing_plan"]
        out["marketing"] = {
            "budget_total": plan.budget_total,
            "channels": [c.channel for c in plan.channels],
        }
    out["log"] = list(values.get("log") or [])[-8:]
    return out


def _response(workflow_id: str, values: dict[str, Any], result: dict[str, Any]) -> WorkflowLaunchResponse:
    payload = _interrupt_payload(result)
    approval: ApprovalRequest | None = None
    if payload:
        approval = ApprovalRequest.model_validate(payload)
    elif values.get("approval_request"):
        approval = ApprovalRequest.model_validate(values["approval_request"])

    qa = QAReport.model_validate(values["qa_report"]) if values.get("qa_report") else None
    status_raw = values.get("status") or WorkflowStatus.PENDING
    status = WorkflowStatus(str(status_raw))

    return WorkflowLaunchResponse(
        workflow_id=workflow_id,
        status=WorkflowStatus.AWAITING_APPROVAL if payload else status,
        awaiting_approval=payload is not None,
        approval=approval,
        qa_report=qa,
        result=_summary(values),
    )


# ═══════════════════════════════════════════════
# routes
# ═══════════════════════════════════════════════
@app.get("/", include_in_schema=False)
async def live_office_ui() -> FileResponse:
    """라이브 오피스 웹 UI."""
    if not WEB_INDEX.exists():  # pragma: no cover - 배포 사고 방지
        raise HTTPException(status_code=500, detail=f"웹 UI 파일이 없습니다: {WEB_INDEX}")
    return FileResponse(WEB_INDEX, media_type="text/html; charset=utf-8")


@app.get("/health", tags=["system"])
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": __version__,
        "env": settings.app_env,
        "llm_provider": settings.llm_provider,
        "mall_platform": settings.mall_platform,
        "workflows": len(_WORKFLOWS),
    }


@app.get("/teams/catalog", tags=["system"])
async def teams_catalog() -> dict[str, Any]:
    """팀별 시스템 프롬프트 요약과 LLM에 바인딩되는 도구(JSON Schema)를 조회한다."""
    return {"teams": team_catalog(), "tools": all_tools()}


@app.get("/workflows", tags=["workflow"])
async def list_workflows() -> dict[str, Any]:
    """실행한 워크플로 전체 목록 (대시보드·대표 할 일 탭 데이터)."""
    runs = [_public(record) for record in _sorted_runs()]
    pending = [run for run in runs if run["status"] == str(WorkflowStatus.AWAITING_APPROVAL)]
    completed = [run for run in runs if run["status"] == str(WorkflowStatus.COMPLETED)]
    scores = [run["qa_score"] for run in runs if isinstance(run.get("qa_score"), int)]
    return {
        "count": len(runs),
        "pending_approval": len(pending),
        "completed": len(completed),
        "blocked": sum(1 for run in runs if run["status"] == str(WorkflowStatus.QA_BLOCKED)),
        "average_qa_score": round(sum(scores) / len(scores), 1) if scores else None,
        "stage_order": list(STAGE_ORDER),
        "stage_labels": dict(STAGE_LABELS),
        "workflows": runs,
        "pending": pending,
    }


@app.get("/office/state", tags=["workflow"])
async def office_state() -> dict[str, Any]:
    """라이브 오피스: 7명 팀장 로스터 + 회의실 말풍선 + 최근 활동 로그."""
    runs = _sorted_runs()
    pending = [run for run in runs if run["status"] == str(WorkflowStatus.AWAITING_APPROVAL)]
    active = next((run for run in runs if run["status"] == str(WorkflowStatus.AWAITING_APPROVAL)), None)
    if active is None:
        active = next((run for run in runs if run["status"] == str(WorkflowStatus.RUNNING)), None)
    if active is None and runs:
        active = runs[0]

    statuses, tasks = _team_status(active)
    staff = [
        {
            "team": row["team"],
            "team_label": row["team_label"],
            "name": row["name"],
            "role": row["role"],
            "badge": row["badge"],
            "avatar": row["avatar"],
            "slot": row["slot"],
            "color": row["color"],
            "hair": row["hair"],
            "shirt": row["shirt"],
            "pants": row["pants"],
            "status": statuses[row["team"]],
            "task": tasks[row["team"]],
            "salary_monthly": 0,
        }
        for row in STAFF
    ]
    speech = _speech(runs, pending, active)
    speech["slot"] = next((row["slot"] for row in staff if row["team"] == speech["speaker"]), 4)

    activity = list(_ACTIVITY)[-14:][::-1]
    counts = {
        "working": sum(1 for row in staff if row["status"] == "작업 중"),
        "awaiting_approval": sum(1 for row in staff if row["status"] == "결재 대기"),
        "done": sum(1 for row in staff if row["status"] == "완료"),
        "idle": sum(1 for row in staff if row["status"] == "대기 중"),
    }

    return {
        "server_time": _now().isoformat(),
        "started_at": _STARTED_AT.isoformat(),
        "room": {
            "title": "대표 승인 회의실",
            "subtitle": "팀장 7명 · 대표 1명",
            "active_workflow": _brief(active) if active else None,
        },
        "ceo": {
            "name": CEO["name"],
            "role": CEO["role"],
            "avatar": CEO["avatar"],
            "hair": CEO["hair"],
            "shirt": CEO["shirt"],
            "pants": CEO["pants"],
            "status": "결재 대기" if pending else "대기 중",
        },
        "staff": staff,
        "counts": {"teams": len(staff), "pending_approval": len(pending), "total_runs": len(runs), **counts},
        "speech": speech,
        "pipeline": _pipeline(active),
        "pending_approvals": [_brief(run) for run in pending],
        "activity": activity,
        "salary_total": sum(row["salary_monthly"] for row in staff),
    }


@app.post("/workflows/launch", response_model=WorkflowLaunchResponse, tags=["workflow"])
async def launch_workflow(request: WorkflowLaunchRequest) -> WorkflowLaunchResponse:
    """상품 1건을 넣으면 검수까지 자동 진행하고, 배포 직전에 승인 대기로 멈춥니다."""
    workflow_id = request.workflow_id or f"wf_{uuid4().hex[:12]}"
    graph = get_graph()
    config = _thread_config(workflow_id)

    state = initial_state(request.product, workflow_id, request.note)
    state["status"] = WorkflowStatus.RUNNING

    try:
        result = await graph.ainvoke(state, config=config)
    except Exception as exc:  # pragma: no cover - 방어적
        logger.exception("workflow launch failed: %s", workflow_id)
        raise HTTPException(status_code=500, detail=f"워크플로 실행 실패: {exc}") from exc

    snapshot = await graph.aget_state(config)
    values = dict(snapshot.values)

    payload = _interrupt_payload(result)
    approval: ApprovalRequest | None = None
    if payload:
        approval = ApprovalRequest.model_validate(payload)
        notify_approval(approval)
        logger.info("workflow %s awaiting approval %s", workflow_id, approval.id)

    record = _upsert_workflow(workflow_id, values, awaiting=payload is not None, approval=approval)
    _log_activity(
        f"🎬 새 상품 런칭 — '{record['name']}' · 검수 {record.get('qa_score')}점 · 결재 대기",
        team="orchestrator",
        kind="start",
    )

    return _response(workflow_id, values, result)


@app.post("/workflows/{workflow_id}/approval", response_model=WorkflowLaunchResponse, tags=["workflow"])
async def decide_approval(workflow_id: str, decision: ApprovalDecision) -> WorkflowLaunchResponse:
    """승인/반려로 멈춰 있는 워크플로를 재개합니다."""
    graph = get_graph()
    config = _thread_config(workflow_id)
    snapshot = await graph.aget_state(config)

    if not snapshot.values:
        raise HTTPException(status_code=404, detail=f"워크플로를 찾을 수 없습니다: {workflow_id}")
    if not snapshot.next:
        raise HTTPException(status_code=409, detail="승인 대기 상태가 아닙니다 (이미 종료되었거나 실행 중)")

    try:
        result = await graph.ainvoke(Command(resume=decision.model_dump()), config=config)
    except Exception as exc:  # pragma: no cover
        logger.exception("workflow resume failed: %s", workflow_id)
        raise HTTPException(status_code=500, detail=f"워크플로 재개 실패: {exc}") from exc

    snapshot = await graph.aget_state(config)
    values = dict(snapshot.values)
    record = _upsert_workflow(workflow_id, values, awaiting=False)
    verb = "승인" if decision.approved else "반려"
    _log_activity(
        f"{'✅' if decision.approved else '🚫'} 대표님 {verb} — '{record['name']}'"
        + (f" / 메모: {decision.note}" if decision.note else ""),
        team="approval",
        kind="decision",
    )
    return _response(workflow_id, values, result)


@app.get("/workflows/{workflow_id}", tags=["workflow"])
async def get_workflow(workflow_id: str) -> dict[str, Any]:
    graph = get_graph()
    snapshot = await graph.aget_state(_thread_config(workflow_id))
    if not snapshot.values:
        raise HTTPException(status_code=404, detail=f"워크플로를 찾을 수 없습니다: {workflow_id}")
    return {
        "workflow_id": workflow_id,
        "next": list(snapshot.next),
        "summary": _summary(dict(snapshot.values)),
        "record": _public(_upsert_workflow(workflow_id, dict(snapshot.values), awaiting=bool(snapshot.next))),
    }
