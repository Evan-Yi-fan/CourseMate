"""Streamlit 页面共用的启动逻辑与小组件。

共用界面代码集中在 ui 包内，避免与 Streamlit 页面入口混在一起。
"""

from __future__ import annotations

import logging
from pathlib import Path

import streamlit as st

from config.settings import Settings
from database import db

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format=LOG_FORMAT)


@st.cache_resource(show_spinner=False)
def _boot_settings() -> Settings:
    """加载配置、建目录、初始化数据库。整个进程只做一次。"""
    settings = Settings.load()
    setup_logging(settings.log_level)
    if settings.public_demo:
        from services.demo_service import prepare_template
        return prepare_template(settings)
    settings.ensure_dirs()
    db.init_db(settings.db_path)
    return settings


def boot() -> Settings:
    """配置缓存与页面渲染分开，否则主题只会在首次加载时出现。"""
    settings = _boot_settings()
    # 模型设置每次重绘重新读取，课程数据库初始化仍使用缓存。
    from config.model_settings import apply
    settings = apply(settings)
    if settings.public_demo:
        if "_public_demo_settings" not in st.session_state:
            from services.demo_service import create_session
            st.session_state["_public_demo_settings"] = create_session(settings)
        settings = st.session_state["_public_demo_settings"]
        st.info("公开体验版 · 已预置示例资料。聊天与答题记录仅属于当前会话，断开或重启后可能重置。")
    css = (Path(__file__).parent / "theme.css").read_text(encoding="utf-8")
    st.markdown("<style>" + css + "</style>", unsafe_allow_html=True)
    with st.sidebar:
        st.markdown('<div class="cm-brand"><div class="cm-brand-symbol">C</div><div><strong>CourseMate</strong><small>课友 · AI 学习助手</small></div></div><div class="cm-nav-label">学习工作台</div>', unsafe_allow_html=True)
        for page, label, icon in [
            ("app.py", "学习概览", ":material/space_dashboard:"),
            ("pages/1_课程知识库.py", "课程知识库", ":material/library_books:"),
            ("pages/2_AI智能问答.py", "AI 智能问答", ":material/chat_bubble_outline:"),
            ("pages/3_智能试题.py", "智能试题", ":material/edit_note:"),
            ("pages/4_学习分析.py", "学习分析", ":material/insights:"),
            ("pages/5_灵玉秘境.py", "灵玉秘境", ":material/sports_esports:"),
            ("pages/6_模型设置.py", "模型设置", ":material/settings:"),
        ]:
            if settings.public_demo and page == "pages/6_模型设置.py":
                continue
            if settings.public_demo and page == "app.py":
                page = "streamlit_demo.py"
            st.page_link(page, label=label, icon=icon, use_container_width=True)
        st.divider()
    return settings


def course_selector(settings: Settings, *, key: str = "course_select") -> int | None:
    """侧边栏课程选择器，返回当前课程 id。"""
    courses = db.list_courses(settings.db_path)
    if "course_id" not in st.session_state:
        st.session_state.course_id = None

    with st.sidebar:
        st.subheader("当前课程")
        if not courses:
            st.info("还没有课程，请先到首页创建。")
            st.session_state.course_id = None
            st.session_state.pop(key, None)
            st.session_state.pop("pending_course_id", None)
            return None

        options = {f"{c['name']}（#{c['id']}）": c["id"] for c in courses}
        labels = list(options)
        pending = st.session_state.pop("pending_course_id", None)
        if pending is not None:
            wanted = next((label for label, cid in options.items() if cid == pending), None)
            if wanted:
                st.session_state.course_id = pending
                st.session_state.pop(key, None)
        current = st.session_state.course_id
        index = next((i for i, lb in enumerate(labels) if options[lb] == current), 0)
        picked = st.selectbox("选择课程", labels, index=index, key=key)
        st.session_state.course_id = options[picked]
        st.caption("示例资料只读 · 学习记录按会话隔离" if settings.public_demo else "课程资料与学习记录保存在本机")
        return st.session_state.course_id


def require_course(course_id: int | None) -> int:
    """没有课程时给出引导并中止当前页渲染。"""
    if not course_id:
        st.warning("请先在首页创建一门课程，再回到本页。")
        st.stop()
    return course_id


def error_box(prefix: str, exc: BaseException) -> None:
    st.error(f"{prefix}：{type(exc).__name__}: {exc}")


def clear_course_learning_state(course_id: int) -> None:
    """删除后清理已展示的旧答案与题目，避免继续使用已删除资料的缓存。"""
    for key in (f"qa_{course_id}", f"advice_{course_id}"):
        st.session_state.pop(key, None)
    if st.session_state.get("course_id") == course_id:
        for key in list(st.session_state):
            if key.startswith("lj_") or key in ("quiz_questions", "quiz_result", "pending_question"):
                st.session_state.pop(key, None)
