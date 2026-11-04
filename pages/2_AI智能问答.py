"""AI 智能问答：基于课程资料检索 + 带来源引用作答。

对应 F05 / F06 / F07。两种提问方式：
- 普通模式：直接走 RAG 问答；
- Agent 模式：先判断意图（问答 / 出题 / 错题分析），再调用对应工具。
"""

from __future__ import annotations

import streamlit as st

from agent.assistant import Assistant
from database import db
from knowledge.retriever import CourseIndex
from services.llm_service import LLMService
from services.qa_service import QAService
from ui_common import boot, course_selector, require_course

st.set_page_config(page_title="AI 智能问答 · CourseMate", page_icon="💬", layout="wide")

settings = boot()
course_id = require_course(course_selector(settings))
course = db.get_course(settings.db_path, course_id)

st.title("AI 智能问答")
st.caption(
    f"当前课程：**{course['name']}**　·　"
    "回答只依据你上传的资料，"
    f"相似度低于 {settings.qa_min_score:.2f} 的片段不算依据，会直接告诉你资料里没有。"
)

chunk_count = CourseIndex(settings, course_id).count()
if chunk_count == 0:
    st.warning("这门课程还没有建立索引。请先到「课程知识库」上传资料。")
    st.stop()

if not settings.llm_ready:
    st.error("大模型未配置：请在 `.env` 中填写 LLM_API_KEY 与 LLM_MODEL 后重启。")
    st.stop()

with st.sidebar:
    st.divider()
    agent_mode = st.toggle(
        "Agent 自动路由", value=False,
        help="开启后，输入“帮我出 3 道题”“看看我的错题”会被识别成对应任务，而不是当成普通提问。",
    )
    st.caption(f"知识库：{chunk_count} 个向量块")

# ----------------------------------------------------------------------
# 会话状态
# ----------------------------------------------------------------------
key = f"qa_{course_id}"
if key not in st.session_state:
    st.session_state[key] = []

EXAMPLES = ["帮我总结这些资料", "帮我找一下这个知识点的位置："]
input_key = f"qa_input_{course_id}"


def fill_question(text):
    st.session_state[input_key] = text

if not st.session_state[key]:
    st.markdown("**可以试试：**")
    pool = EXAMPLES
    cols = st.columns(len(pool))
    for col, q in zip(cols, pool):
        col.button(q, key=f"qa_example_{pool.index(q)}", width="stretch",
                   on_click=fill_question, args=(q,))


def render_sources(sources: list[dict], cited: list[int]) -> None:
    if not sources:
        return
    with st.expander(f"📎 引用来源（{len(sources)} 条片段）", expanded=True):
        for i, s in enumerate(sources, start=1):
            mark = "✅ 已被引用" if i in cited else "• 未直接引用"
            page = f" · 第 {s['page']} 页" if s.get("page") else ""
            st.markdown(
                f"**[{i}] {s['filename']}**{page}  \n"
                f"<span style='color:#6b7280;font-size:12px'>相似度 {s['score']} · {mark}</span>",
                unsafe_allow_html=True,
            )
            st.caption(s["text"][:300] + ("…" if len(s["text"]) > 300 else ""))


for msg in st.session_state[key]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] != "assistant":
            continue
        badge = msg.get("badge")
        if badge:
            st.caption(badge)
        render_sources(msg.get("sources", []), msg.get("cited", []))
        if msg.get("goto_quiz"):
            st.page_link("pages/3_智能试题.py", label="→ 去「智能试题」作答", icon="📝")

# ----------------------------------------------------------------------
# 输入
# ----------------------------------------------------------------------
question = st.chat_input("针对这门课程的资料提问…", key=input_key)

if question:
    st.session_state[key].append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("正在理解你的问题…" if agent_mode else "正在检索资料并作答…"):
            try:
                if agent_mode:
                    reply = Assistant(settings, LLMService(settings)).handle(course_id, question)
                else:
                    reply = None
                    result = QAService(settings, LLMService(settings)).ask(course_id, question)
            except Exception as exc:  # noqa: BLE001
                st.error(f"处理失败：{type(exc).__name__}: {exc}")
                st.stop()

        # ---- Agent 分支 ----
        if reply is not None:
            if not reply.ok:
                st.error(f"执行失败：{reply.message}")
                entry = {"role": "assistant", "content": f"执行失败：{reply.message}",
                         "badge": f"意图 {reply.intent} · 路由 {reply.routed_by}"}
            elif reply.intent == "generate_quiz":
                questions = reply.payload.get("questions") or []
                st.session_state["quiz_questions"] = [
                    {k: v for k, v in q.items() if k != "answer"} for q in questions
                ]
                st.session_state["quiz_result"] = None
                st.success(reply.message)
                st.page_link("pages/3_智能试题.py", label="→ 去「智能试题」作答", icon="📝")
                entry = {"role": "assistant", "content": reply.message,
                         "badge": f"意图 generate_quiz · 工具 {reply.tool} · 路由 {reply.routed_by}",
                         "goto_quiz": True}
            elif reply.intent == "analyze_mistakes":
                st.markdown(reply.message)
                p = reply.payload
                if p.get("total"):
                    c1, c2 = st.columns(2)
                    c1.metric("作答总数", p["total"])
                    c2.metric("正确率", f"{p['accuracy']:.0%}")
                    for kp in p.get("by_knowledge", [])[:5]:
                        st.caption(
                            f"· {kp['knowledge_point']}：错 {kp['wrong']}/{kp['total']}"
                        )
                entry = {"role": "assistant", "content": reply.message,
                         "badge": f"意图 analyze_mistakes · 工具 {reply.tool} · 路由 {reply.routed_by}"}
            else:
                p = reply.payload
                st.markdown(reply.message)
                if p.get("refused"):
                    st.caption(f"⚠️ 已拒答：{p.get('reason', '')}")
                else:
                    st.caption(
                        f"模型 {p.get('model', '-')} · 检索耗时 {p.get('latency_ms', 0)}ms · "
                        f"最高相似度 {p.get('top_score', 0):.2f}"
                    )
                render_sources(p.get("sources", []), p.get("cited", []))
                entry = {"role": "assistant", "content": reply.message,
                         "sources": p.get("sources", []), "cited": p.get("cited", []),
                         "badge": f"意图 knowledge_qa · 工具 {reply.tool} · 路由 {reply.routed_by}"}

        # ---- 普通 RAG 分支 ----
        else:
            st.markdown(result.answer)
            if result.refused:
                st.caption(f"⚠️ 已拒答：{result.reason}")
            else:
                st.caption(
                    f"模型 {result.model} · 检索耗时 {result.latency_ms}ms · "
                    f"最高相似度 {result.top_score:.2f}"
                )
            render_sources([s.as_dict() for s in result.sources], result.cited)
            entry = {
                "role": "assistant", "content": result.answer,
                "sources": [s.as_dict() for s in result.sources], "cited": result.cited,
                "badge": ("⚠️ 已拒答：" + result.reason) if result.refused else "",
            }

    st.session_state[key].append(entry)
    st.rerun()

if st.session_state[key] and st.button("清空当前对话"):
    st.session_state[key] = []
    st.rerun()
