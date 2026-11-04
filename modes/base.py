"""答题模式的接口定义。

设计目标：**换玩法不动业务代码**。

页面只认 `QuizMode` 这个协议：
    answers = mode.render(ctx)      # 返回 {question_id: 选项key}，没提交就返回 None
页面拿到 answers 后交给 `quiz_service.grade_batch` 判分——判分逻辑与玩法无关。

所以以后新增"限时挑战""连击""闯关地图"等玩法，只需要：
1. 在 modes/ 下新建一个文件，实现 key/label/description/render；
2. 在 modes/__init__.py 的注册表里加一行。
不需要改页面，也不需要改判分。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from config.settings import Settings


@dataclass
class PlayContext:
    """交给某个模式渲染所需的全部上下文。"""

    settings: Settings
    course_id: int
    questions: list[dict]          # 已去掉答案的题目（public() 的结果）
    key_prefix: str = "quiz"       # 给控件 key 加前缀，避免同页冲突


@runtime_checkable
class QuizMode(Protocol):
    key: str
    label: str
    description: str
    available: bool
    # 是否由模式下挂自己的提交按钮（普通模式用表单内置按钮，游戏模式通常要自己控制）

    def render(self, ctx: PlayContext) -> dict[int, str] | None:
        """渲染作答界面。

        返回 {question_id: 用户选择的选项 key} 表示"用户已提交"；
        返回 None 表示"还没提交"。调用方负责调用 grade_batch。
        """
        ...


def complete_answers(questions: list[dict], picked: dict[int, str]) -> dict[int, str]:
    """把未作答的题补成空字符串。

    这是评分口径的关键：如果未作答的题被漏掉，它们会从分母里消失，
    "只答一题且答对"就会变成 100 分——等于少答反而得分高。
    所以这里独立成纯函数，既能被所有模式复用，也能直接单测。
    """
    result = {int(k): v for k, v in picked.items()}
    for q in questions:
        qid = int(q["id"])
        result.setdefault(qid, "")
    return result
