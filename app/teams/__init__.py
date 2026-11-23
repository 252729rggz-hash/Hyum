"""7개 실무팀 패키지.

MD → 디자인 → 콘텐츠 → 검수(QA) → 개발 → 마케팅 → CS 순으로 협업합니다.
각 팀의 `agent.run(state)`는 MallWorkflowState의 일부만 담은 dict를 돌려줍니다.

이 패키지를 import하면 7개 팀의 프롬프트 번들과 도구가 레지스트리에 등록됩니다.
`team_catalog()`로 팀별 시스템 프롬프트 요약과 바인딩된 도구 목록을 확인할 수 있습니다.
"""

from __future__ import annotations

from typing import Any

from app.shared.models import TeamName
from app.shared.prompting import prompt_catalog, prompt_for
from app.shared.tooling import catalog as tool_catalog
from app.shared.tooling import tools_for
from app.teams.content.agent import run as run_content
from app.teams.cs.agent import run as run_cs
from app.teams.design.agent import run as run_design
from app.teams.dev.agent import run as run_dev
from app.teams.marketing.agent import run as run_marketing
from app.teams.md.agent import run as run_md
from app.teams.qa.agent import run as run_qa

__all__ = [
    "run_md",
    "run_design",
    "run_content",
    "run_qa",
    "run_dev",
    "run_marketing",
    "run_cs",
    "team_catalog",
    "all_tools",
    "all_prompts",
]

TEAM_ORDER = (
    TeamName.MD,
    TeamName.DESIGN,
    TeamName.CONTENT,
    TeamName.QA,
    TeamName.DEV,
    TeamName.MARKETING,
    TeamName.CS,
)


def team_catalog() -> list[dict[str, Any]]:
    """팀별 역할·프롬프트 요약·도구 목록."""
    rows: list[dict[str, Any]] = []
    for team in TEAM_ORDER:
        bundle = prompt_for(team)
        rows.append(
            {
                "team": str(team),
                "role": bundle.role if bundle else "",
                "tools": [spec.name for spec in tools_for(team)],
                "prompt": bundle.summary() if bundle else None,
            }
        )
    return rows


def all_tools() -> list[dict[str, Any]]:
    return tool_catalog()


def all_prompts() -> list[dict[str, Any]]:
    return prompt_catalog()
