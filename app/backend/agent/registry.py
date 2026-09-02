from __future__ import annotations

from typing import Any, Protocol


class RegisteredAgent(Protocol):
    name: str
    version: str

    def run(self, context: dict[str, Any]) -> Any: ...


class AgentRegistry:
    """Explicit, app-local registry. Register during app construction, then freeze."""

    def __init__(self) -> None:
        self._agents: dict[str, RegisteredAgent] = {}
        self._frozen = False

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(self, agent: RegisteredAgent) -> None:
        if self._frozen:
            raise RuntimeError("Agent 注册表已经冻结")
        if not agent.name.strip():
            raise ValueError("Agent 名称不能为空")
        if agent.name in self._agents:
            raise ValueError(f"Agent 已注册：{agent.name}")
        self._agents[agent.name] = agent

    def get(self, name: str) -> RegisteredAgent:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise LookupError(f"Agent 未注册：{name}") from exc

    def freeze(self) -> None:
        self._frozen = True

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._agents))
