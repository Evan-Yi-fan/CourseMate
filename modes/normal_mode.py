"""普通答题：一次性填完所有题，提交后统一判分。"""

from __future__ import annotations

import streamlit as st

from modes.base import PlayContext, complete_answers


class NormalMode:
    key = "normal"
    label = "普通答题"
    description = "一次性作答全部题目，提交后查看分数、正确答案与解析。"
    available = True

    def render(self, ctx: PlayContext) -> dict[int, str] | None:
        with st.form(key=f"{ctx.key_prefix}_normal_form"):
            picked: dict[int, str] = {}
            for i, q in enumerate(ctx.questions, start=1):
                st.markdown(f"**{i}. {q['question']}**")
                options = q["options"]
                choice = st.radio(
                    "选择答案",
                    options=[o["key"] for o in options],
                    format_func=lambda k, opts=options: next(
                        (f"{o['key']}. {o['text']}" for o in opts if o["key"] == k), k
                    ),
                    key=f"{ctx.key_prefix}_q_{q['id']}",
                    label_visibility="collapsed",
                    index=None,
                )
                if choice:
                    picked[int(q["id"])] = choice
                if i < len(ctx.questions):
                    st.divider()

            submitted = st.form_submit_button("提交答案", type="primary")

        if not submitted:
            return None

        # 未作答的题必须补成空字符串再交出去（见 complete_answers 的说明）
        return complete_answers(ctx.questions, picked)
