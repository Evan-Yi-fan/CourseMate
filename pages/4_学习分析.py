"""学习分析：正确率、错题列表、知识点薄弱排行、AI 复习建议。

对应 P1 的三项：错题分析、学习报告、AI 学习建议。
所有数字来自真实答题记录，没有数据就明说，不编统计。
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from database import db
from services.analysis_service import advice, overview
from ui.common import boot, course_selector, require_course

st.set_page_config(page_title="学习分析 · CourseMate", page_icon="📊", layout="wide")

settings = boot()
course_id = require_course(course_selector(settings))
course = db.get_course(settings.db_path, course_id)

st.title("学习分析")
st.caption(f"当前课程：**{course['name']}**　·　数据来自真实答题记录")

data = overview(settings, course_id)

if not data["has_data"]:
    st.info("这门课程还没有答题记录。先去「智能试题」做几道题，这里就会有数据。")
    c1, c2 = st.columns(2)
    c1.metric("作答总数", 0)
    c2.metric("正确率", "—")
    st.page_link("pages/3_智能试题.py", label="→ 去「智能试题」出题", icon="📝")
    st.stop()

# ----------------------------------------------------------------------
# 概览
# ----------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("作答总数", data["total"])
c2.metric("答对", data["correct"])
c3.metric("正确率", f"{data['accuracy']:.0%}")
c4.metric("错题", len(data["wrong_questions"]))

st.divider()

# ----------------------------------------------------------------------
# 知识点分布
# ----------------------------------------------------------------------
st.subheader("知识点掌握情况")

rows = data["by_knowledge"]
if rows:
    df = pd.DataFrame([
        {"知识点": r["knowledge_point"], "答对": r["total"] - r["wrong"], "答错": r["wrong"]}
        for r in rows
    ])
    fig = px.bar(
        df, x="知识点", y=["答对", "答错"], barmode="stack",
        color_discrete_map={"答对": "#34a853", "答错": "#ea4335"},
        height=320,
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        legend_title_text="", xaxis_title="", yaxis_title="题数",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, width="stretch")

    weak = data["weak_points"]
    if weak:
        st.markdown("**薄弱知识点（按错题数排序）**")
        for kp in weak[:5]:
            st.markdown(
                f"- **{kp['knowledge_point']}**：错 {kp['wrong']}/{kp['total']} 题"
            )
    else:
        st.success("各知识点目前都没有答错，掌握情况不错。")
else:
    st.caption("题目还没有标注知识点。")

st.divider()

# ----------------------------------------------------------------------
# 错题
# ----------------------------------------------------------------------
st.subheader("错题列表")
wrong = data["wrong_questions"]
if not wrong:
    st.success("没有错题。")
else:
    for i, w in enumerate(wrong, start=1):
        with st.container(border=True):
            st.markdown(f"**{i}. {w['question']}**")
            opts = "　".join(f"{o['key']}. {o['text']}" for o in w.get("options", []))
            if opts:
                st.caption(opts)
            st.markdown(
                f"<span style='color:#c0392b'>你的答案：{w['user_answer'] or '（未作答）'}</span>　·　"
                f"<span style='color:#1e7e34'>正确答案：{w['answer']}</span>　·　"
                f"知识点：{w['knowledge_point']}",
                unsafe_allow_html=True,
            )
            if w["explanation"]:
                st.caption(f"解析：{w['explanation']}")
            st.caption(f"作答时间：{w['created_at']}")

st.divider()

# ----------------------------------------------------------------------
# AI 学习建议
# ----------------------------------------------------------------------
st.subheader("AI 复习建议")
st.caption("基于你的错题和薄弱知识点生成，只依据真实作答记录。")

key = f"advice_{course_id}"
if st.button("生成复习建议", type="primary"):
    if not settings.llm_ready:
        st.error("大模型未配置，无法生成建议。")
    else:
        with st.spinner("正在分析你的错题…"):
            try:
                result = advice(settings, course_id, course["name"])
            except Exception as exc:  # noqa: BLE001  不给用户看堆栈
                result = {"ok": False, "reason": f"生成建议失败：{type(exc).__name__}"}
        if result["ok"]:
            st.session_state[key] = result["text"]
        else:
            st.error(result["reason"])

if st.session_state.get(key):
    st.markdown(st.session_state[key])
    if st.button("清空建议"):
        st.session_state[key] = None
        st.rerun()
