"""Main-flow stage registry (EP-01): each stage is a replaceable implementation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

DEFAULT_STAGES = (
    "model_completion",
    "requirement_structuring",
    "strategy",
    "case_generation",
    "execution",
    "report",
)


@runtime_checkable
class Stage(Protocol):
    name: str

    def run(self, context: dict) -> dict: ...


class NotImplementedStage:
    def __init__(self, name: str):
        self.name = name

    def run(self, context: dict) -> dict:
        raise NotImplementedError(f"stage '{self.name}' has no implementation yet")


class StageRegistry:
    def __init__(self, order: tuple[str, ...] = DEFAULT_STAGES):
        self._order = list(order)
        self._impls: dict[str, Stage] = {n: NotImplementedStage(n) for n in order}

    @property
    def order(self) -> list[str]:
        return list(self._order)

    def register(self, stage: Stage, *, after: str | None = None) -> None:
        """Replace an existing stage, or insert a new one after `after` (or at the end)."""
        if not isinstance(stage, Stage):
            raise TypeError("stage must define name and run(context)")
        if stage.name not in self._impls:
            if after is not None and after not in self._impls:
                raise KeyError(after)
            index = self._order.index(after) + 1 if after else len(self._order)
            self._order.insert(index, stage.name)
        self._impls[stage.name] = stage

    def remove(self, name: str) -> None:
        self._order.remove(name)
        del self._impls[name]

    def get(self, name: str) -> Stage:
        return self._impls[name]
