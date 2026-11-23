"""팀 공용 도구(Tool) 레지스트리.

각 팀의 `tools.py`는 pydantic 입력 모델과 순수 함수를 만들고 `@tool(...)`로 등록합니다.
등록된 Tool은 세 가지 방식으로 그대로 쓰입니다.

1. 워크플로 실행 중 직접 호출 — `md_price_quote(cost_price=21000, ...)`
2. LLM function calling 바인딩 — `openai_tools(TeamName.MD)` / `anthropic_tools(TeamName.MD)`
3. LLM이 고른 도구 실행 — `dispatch(TeamName.MD, "md_price_quote", {...})`

도구 이름은 OpenAI 규격(영문·숫자·밑줄)에 맞춰 `md_price_quote`처럼 팀 접두사를 붙입니다.
같은 이름을 두 번 등록하면 `ValueError`로 즉시 실패해, 프롬프트와 스키마가 어긋나는
사고를 배포 전에 잡습니다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.shared.models import TeamName


class ToolInputError(ValueError):
    """도구 인자가 스키마와 맞지 않거나, 해당 팀에 없는 도구를 부를 때."""


@dataclass(frozen=True, slots=True)
class Tool:
    """LLM에 바인딩 가능한 도구 한 건.

    `args_model`이 곧 계약(스키마)이고, `func`은 검증된 입력 모델 하나를 받습니다.
    """

    name: str
    team: TeamName
    description: str
    args_model: type[BaseModel]
    func: Callable[[Any], Any]
    returns: str = ""
    tags: tuple[str, ...] = ()

    @property
    def parameters(self) -> dict[str, Any]:
        """LLM에 넘길 JSON Schema (pydantic 모델에서 자동 생성)."""
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return schema

    def invoke(self, arguments: dict[str, Any] | None = None) -> Any:
        try:
            args = self.args_model.model_validate(arguments or {})
        except ValidationError as exc:
            raise ToolInputError(f"{self.name}: 인자 검증 실패 — {exc}") from exc
        return self.func(args)

    def __call__(self, **kwargs: Any) -> Any:
        return self.invoke(kwargs)

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }

    def anthropic_schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.parameters}

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "team": str(self.team),
            "description": self.description,
            "returns": self.returns,
            "tags": list(self.tags),
            "parameters": self.parameters,
        }


_REGISTRY: dict[str, Tool] = {}

F = TypeVar("F", bound=Callable[[Any], Any])


def register(spec: Tool) -> Tool:
    if spec.name in _REGISTRY:
        raise ValueError(f"도구 이름 중복 등록: {spec.name}")
    _REGISTRY[spec.name] = spec
    return spec


def tool(
    *,
    name: str,
    team: TeamName,
    description: str,
    args: type[BaseModel],
    returns: str = "",
    tags: tuple[str, ...] = (),
) -> Callable[[F], Tool]:
    """도구 등록 데코레이터. 함수는 검증된 입력 모델 1개를 받아야 합니다."""

    def decorate(func: F) -> Tool:
        # LLM 스키마와 docstring이 어긋나지 않도록 설명을 함수 문서로도 남긴다.
        if not func.__doc__:
            func.__doc__ = description
        return register(
            Tool(
                name=name,
                team=team,
                description=description,
                args_model=args,
                func=func,
                returns=returns,
                tags=tags,
            )
        )

    return decorate


def tools_for(team: TeamName | str | None = None) -> list[Tool]:
    """팀 도구 목록. `team=None`이면 전체."""
    if team is None:
        return list(_REGISTRY.values())
    key = TeamName(str(team))
    return [t for t in _REGISTRY.values() if t.team == key]


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def tool_map(team: TeamName | str) -> dict[str, Tool]:
    return {t.name: t for t in tools_for(team)}


def openai_tools(team: TeamName | str | None = None) -> list[dict[str, Any]]:
    return [t.openai_schema() for t in tools_for(team)]


def anthropic_tools(team: TeamName | str | None = None) -> list[dict[str, Any]]:
    return [t.anthropic_schema() for t in tools_for(team)]


def dispatch(team: TeamName | str, name: str, arguments: dict[str, Any] | None = None) -> Any:
    """LLM이 고른 도구를 팀 범위 안에서만 실행한다 (팀 간 도구 오용 차단)."""
    found = _REGISTRY.get(name)
    if found is None or found.team != TeamName(str(team)):
        raise ToolInputError(
            f"{team} 팀에서 '{name}' 도구를 쓸 수 없습니다. 사용 가능: {sorted(tool_map(team))}"
        )
    return found.invoke(arguments)


def tool_manifest(team: TeamName | str) -> str:
    """시스템 프롬프트에 넣을 도구 설명서(이름·설명·반환값)."""
    lines = []
    for spec in tools_for(team):
        tags = f" [{', '.join(spec.tags)}]" if spec.tags else ""
        lines.append(f"- {spec.name}{tags}: {spec.description} → {spec.returns or '결과 객체'}")
    return "\n".join(lines)


def catalog() -> list[dict[str, Any]]:
    """전체 도구 카탈로그 (문서·API 노출용)."""
    return [t.summary() for t in all_tools()]
