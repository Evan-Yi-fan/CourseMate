"""答题模式注册表。

新增玩法只需要在这里加一行，页面会自动出现在选择器里。
"""

from __future__ import annotations

from modes.base import PlayContext, QuizMode
from modes.normal_mode import NormalMode

_MODES: list[QuizMode] = [NormalMode()]


def all_modes() -> list[QuizMode]:
    return list(_MODES)


def get_mode(key: str) -> QuizMode:
    for m in _MODES:
        if m.key == key:
            return m
    raise KeyError(f"未知的答题模式: {key}")


def available_modes() -> list[QuizMode]:
    return [m for m in _MODES if m.available]


__all__ = ["PlayContext", "QuizMode", "all_modes", "get_mode", "available_modes"]
