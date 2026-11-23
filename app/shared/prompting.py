"""팀별 프롬프트 번들.

각 팀 `agent.py`는 `SYSTEM_PROMPT`(역할·규칙·금지사항)와 `USER_TEMPLATE`(상품 데이터를
끼워 넣는 틀)을 `PromptBundle`로 등록합니다. `LLM_PROVIDER=mock`일 때도 이 번들은
"LLM을 붙이면 무엇을 물어볼지"를 코드에 고정해 두는 계약서 역할을 합니다.

사용자 메시지는 `string.Template`($변수) 문법이라, 프롬프트 안에 JSON 예시의 중괄호를
그대로 써도 됩니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from string import Template
from typing import Any

from app.shared.models import TeamName


@dataclass(frozen=True, slots=True)
class PromptBundle:
    """팀 하나의 시스템 프롬프트 + 사용자 메시지 템플릿."""

    team: TeamName
    role: str
    system: str
    user_template: str
    output_contract: str = ""

    def render(self, **values: Any) -> str:
        return Template(self.user_template).substitute(**values).strip()

    def messages(self, **values: Any) -> list[dict[str, str]]:
        """OpenAI/Anthropic 공통 messages 형식."""
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.render(**values)},
        ]

    def preview(self, limit: int = 220) -> str:
        body = " ".join(self.system.split())
        return body[:limit] + ("…" if len(body) > limit else "")

    def summary(self) -> dict[str, Any]:
        return {
            "team": str(self.team),
            "role": self.role,
            "system_chars": len(self.system),
            "user_template_chars": len(self.user_template),
            "output_contract": self.output_contract,
            "preview": self.preview(),
        }


_PROMPTS: dict[TeamName, PromptBundle] = {}


def register_prompt(bundle: PromptBundle) -> PromptBundle:
    _PROMPTS[bundle.team] = bundle
    return bundle


def prompt_for(team: TeamName | str) -> PromptBundle | None:
    return _PROMPTS.get(TeamName(str(team)))


def prompt_catalog() -> list[dict[str, Any]]:
    return [b.summary() for b in _PROMPTS.values()]
