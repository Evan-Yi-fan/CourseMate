"""Prompt 模板集中管理。

把 Prompt 从业务代码里抽出来的原因：它是最需要反复调的东西，
放在一起才能对比版本、也才敢改。
"""

from __future__ import annotations

from typing import Sequence

from knowledge.retriever import Hit

# ----------------------------------------------------------------------
# 知识问答
# ----------------------------------------------------------------------
QA_SYSTEM = """你是一名严谨的课程助教。你的唯一信息来源是用户提供的【资料片段】。

必须遵守：
1. 只使用【资料片段】中的内容作答，不使用你自己的先验知识补充课程细节。
2. 每个关键结论后面用 [1]、[2] 标注它来自第几条片段，编号必须与给出的片段编号一致。
3. 如果片段不足以回答，直接说"当前课程资料中没有找到足够依据"，并说明缺什么，
   绝对不要猜测、不要编造页码或引用。
4. 用中文回答，结构清晰；能分点时用分点，不要写套话和免责声明。
5. 不要复述片段原文的整段，要用自己的话组织后回答。"""

QA_USER_TEMPLATE = """【资料片段】
{context}

【问题】
{question}

请依据上述片段回答，并用 [n] 标注引用。"""

NO_EVIDENCE_ANSWER = (
    "当前课程资料中没有找到足够依据来回答这个问题。\n\n"
    "可能的原因：\n"
    "1. 这个问题超出了已上传资料的范围；\n"
    "2. 资料里用了不同的表述方式，检索没有召回。\n\n"
    "建议：换个更贴近课件用语的说法再问，或先上传相关章节的资料。"
)


def format_context(hits: Sequence[Hit]) -> str:
    """把检索片段拼成带编号的上下文，编号与引用 [n] 一一对应。"""
    blocks: list[str] = []
    for i, h in enumerate(hits, start=1):
        loc = f"{h.filename}"
        if h.page is not None:
            loc += f" 第 {h.page} 页"
        blocks.append(f"[{i}] 来源：{loc}\n{h.text.strip()}")
    return "\n\n".join(blocks)


def build_qa_messages(question: str, hits: Sequence[Hit]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": QA_SYSTEM},
        {"role": "user", "content": QA_USER_TEMPLATE.format(
            context=format_context(hits), question=question.strip()
        )},
    ]


# ----------------------------------------------------------------------
# 阶段 D 会用到，先占位，避免业务代码里散落字符串
# ----------------------------------------------------------------------
QUIZ_SYSTEM = """你是一名课程出题老师。请根据给定的课程资料片段出题。

只输出一个 JSON 对象，不要输出任何解释文字或 Markdown 代码块标记。格式：
{
  "questions": [
    {
      "question": "题干",
      "type": "single",
      "options": [{"key": "A", "text": "选项内容"}, ...],
      "answer": "A",
      "explanation": "解析",
      "knowledge_point": "对应知识点"
    }
  ]
}

要求：
1. 题目必须能由给定片段直接判定对错，不要出需要外部知识的题；
2. 单选题必须有 4 个选项、且只有 1 个正确答案；
3. answer 必须是选项 key 之一；
4. 题干和选项都不出现"根据资料"之类的措辞。"""
