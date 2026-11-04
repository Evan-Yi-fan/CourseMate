"""CourseMate 学习工作台，优先呈现当前课程与学习入口。"""
from __future__ import annotations

from html import escape
import streamlit as st
from config.settings import ConfigError, Settings
from database import db
from ui.common import boot, course_selector, clear_course_learning_state
from services import deletion_service

st.set_page_config(page_title="CourseMate 课友 · 学习工作台", page_icon="📚", layout="wide")
try:
    settings: Settings = boot()
except ConfigError as exc:
    st.error(f"配置有问题：{exc}")
    st.stop()
except Exception as exc:
    st.error(f"初始化失败：{type(exc).__name__}")
    st.stop()

course_id = course_selector(settings)
courses = db.list_courses(settings.db_path)
counts = db.table_counts(settings.db_path)
current = next((c for c in courses if c["id"] == course_id), None)

st.markdown('<div class="cm-eyebrow">YOUR LEARNING SPACE / 学习概览</div>', unsafe_allow_html=True)
st.title("CourseMate 课友")
st.caption("整理知识，找到答案。把今天的学习，再向前推进一点。")

st.markdown('''<section class="cm-hero"><div class="cm-hero-copy">
<span class="cm-hero-tag">从一份讲义开始，建立自己的知识库</span>
<h2>知识有出处，<br>学习有章法。</h2>
<p>让课程资料变成有据可查的答案、针对性的练习，和看得见的学习积累。</p>
<div class="cm-hero-trail">资料入库 &nbsp; → &nbsp; 来源问答 &nbsp; → &nbsp; 练习巩固 &nbsp; → &nbsp; 错题复习</div>
</div><svg class="cm-hero-art" viewBox="0 0 300 220" aria-hidden="true">
<circle cx="155" cy="111" r="88" fill="#d4dfc2"/><circle cx="155" cy="111" r="105" fill="none" stroke="#bdcfad" stroke-dasharray="3 8"/>
<path d="M76 63 169 41l38 118-94 23Z" fill="#b8cba5"/>
<rect x="112" y="25" width="105" height="142" rx="7" fill="#fffdf3" stroke="#a8bd9c" transform="rotate(10 164 96)"/>
<path d="m137 55 54 9m-58 11 57 10m-61 10 56 10m-61 10 40 7" stroke="#bcc9b0" stroke-width="4"/>
<path d="M57 130q45-20 94 5v63q-47-23-94-5Z" fill="#faf8e9" stroke="#5c8163" stroke-width="2"/>
<path d="M151 135q47-25 92-5v63q-47-18-92 5Z" fill="#f0f2df" stroke="#5c8163" stroke-width="2"/>
<path d="M151 136v60m-74-45 51 8m-51 5 51 9m46-15 47-8m-47 23 47-9" stroke="#b3c4a3" stroke-width="2"/>
<circle cx="233" cy="61" r="24" fill="#416d52"/><path d="m222 61 8 8 15-16" stroke="#eef6e0" stroke-width="3" fill="none" stroke-linecap="round"/>
<path d="m55 87 4-8 4 8 8 4-8 4-4 8-4-8-8-4Z" fill="#9cab7a"/>
</svg></section>''', unsafe_allow_html=True)

with st.container(key="overview_metrics"):
    for col, label, key in zip(st.columns(4), ("学习课程", "课程资料", "题库积累", "累计作答"),
                               ("courses", "documents", "questions", "quiz_attempts")):
        col.metric(label, counts.get(key, 0))
st.write("")

main, aside = st.columns([2.2, 1], gap="large")
with main:
    st.subheader("继续学习")
    if current:
        stats = db.attempt_stats(settings.db_path, course_id)
        with st.container(border=True, key="card_current"):
            st.markdown(f'''<div class="cm-course-label">CURRENT COURSE / 当前课程</div>
<div class="cm-course-name">{escape(current['name'])}</div>
<div class="cm-course-desc">{escape(current.get('description') or '从资料到理解，从理解到掌握。继续这一门课的学习。')}</div>
<div class="cm-chip-row"><span class="cm-chip">{current['doc_count']} 份资料</span><span class="cm-chip">{current['question_count']} 道试题</span><span class="cm-chip">{stats['total']} 次作答</span></div>''', unsafe_allow_html=True)
            if stats["total"]:
                st.progress(stats["accuracy"], text=f"当前课程答题正确率 {stats['accuracy']:.0%}")
            else:
                st.caption("还没有作答记录。准备好资料后，试着完成第一组练习。")
            a, b = st.columns(2)
            a.page_link("pages/2_AI智能问答.py", label="继续问答 →", icon=":material/forum:")
            b.page_link("pages/1_课程知识库.py", label="管理课程资料", icon=":material/folder_open:")
    else:
        st.info("欢迎来到你的学习空间。先在下方创建一门课程，再上传第一份资料。")

    st.subheader("学习工具")
    tools = [
        ("01 / KNOWLEDGE", "课程知识库", "集中管理讲义和笔记，为每个答案准备依据。", "pages/1_课程知识库.py", ":material/library_books:"),
        ("02 / ASK", "AI 智能问答", "带着问题读资料，沿着引用回到知识源头。", "pages/2_AI智能问答.py", ":material/chat_bubble_outline:"),
        ("03 / PRACTICE", "智能试题", "用一组针对性的练习，检查理解是否扎实。", "pages/3_智能试题.py", ":material/edit_note:"),
        ("04 / REFLECT", "学习分析", "回顾真实答题记录，找到下一次复习的重点。", "pages/4_学习分析.py", ":material/insights:"),
    ]
    for offset in (0, 2):
        for col, (tag, title, desc, page, icon) in zip(st.columns(2), tools[offset:offset+2]):
            with col, st.container(border=True, key=f"card_tool_{offset}_{title}"):
                st.markdown(f'<div class="cm-feature"><div class="cm-feature-label">{tag}</div><h3>{title}</h3><p>{desc}</p></div>', unsafe_allow_html=True)
                st.page_link(page, label="进入"+title+" →", icon=icon)

with aside:
    st.subheader("学习之外")
    with st.container(border=True, key="card_game"):
        st.markdown('''<div class="cm-game"><div class="cm-game-kicker">A LITTLE ADVENTURE</div><div class="cm-game-art" aria-hidden="true"><span>金</span><span>火</span><span>水</span></div><h3>灵玉秘境</h3><p>答题积攒灵玉，集字合成、布阵御妖。给认真学习的自己，一场小小的冒险。</p></div>''', unsafe_allow_html=True)
        st.page_link("pages/5_灵玉秘境.py", label="进入秘境 →", icon=":material/sports_esports:")
    with st.container(border=True, key="card_route"):
        st.markdown('<div class="cm-course-label">一步一步来</div>', unsafe_allow_html=True)
        for n, title, detail in [("1", "把资料放在一起", "上传 PDF、DOCX、TXT 或 PPT 课件"), ("2", "带着问题去理解", "查看答案，也查看它的出处"), ("3", "让练习形成反馈", "完成答题，回看错题与建议")]:
            st.markdown(f'<div class="cm-route"><span class="cm-route-number">{n}</span><div><b>{title}</b><p>{detail}</p></div></div>', unsafe_allow_html=True)

st.divider()
collection, creation = st.columns([2.2, 1], gap="large")

def activate_course(cid: int) -> None:
    # 回调在下一轮控件渲染前执行，避免旧选择框覆盖卡片切换结果。
    st.session_state["pending_course_id"] = cid

with creation:
    st.subheader("创建新课程")
    with st.form("create_course", clear_on_submit=True):
        name = st.text_input("课程名称", placeholder="例如：数字图像处理")
        submitted = st.form_submit_button("创建课程", type="primary", use_container_width=True)
    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(flash)
    for warning in st.session_state.pop("deletion_warnings", []):
        st.warning(warning)
    if submitted:
        try:
            cid = db.create_course(settings.db_path, name)
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"创建失败：{type(exc).__name__}")
        else:
            st.session_state["pending_course_id"] = cid
            st.session_state.flash = f"已创建课程「{name}」"
            st.rerun()

with collection:
    st.subheader("我的课程")
    st.caption(f"共 {len(courses)} 门课程 · 选择一门，继续你的学习")
    if not courses:
        st.caption("这里会显示你创建的课程。先从右侧添加第一门吧。")
    for offset in range(0, len(courses), 2):
        for col, course in zip(st.columns(2), courses[offset:offset+2]):
            with col, st.container(border=True, key=f"card_course_{course['id']}"):
                selected = course["id"] == course_id
                badge = '<span class="cm-selected">当前课程</span>' if selected else ''
                description = f'<div class="cm-list-desc">{escape(course["description"])}</div>' if course.get("description") else ""
                st.markdown(f'<div class="cm-list-name">{escape(course["name"])} {badge}</div>{description}<div class="cm-list-meta">{course["doc_count"]} 份资料 &nbsp;·&nbsp; {course["question_count"]} 道题目</div>', unsafe_allow_html=True)
                st.button("正在学习" if selected else "设为当前课程", key=f"choose_course_{course['id']}", disabled=selected, on_click=activate_course, args=(course["id"],), use_container_width=True)
                with st.popover("删除课程", icon=":material/delete_outline:", use_container_width=True):
                    st.warning(f"将永久删除「{course['name']}」及其资料、索引、题目、作答和聊天记录。")
                    confirmed = st.checkbox("确认删除这门课程及全部学习记录", key=f"confirm_delete_course_{course['id']}")
                    if st.button("确认删除课程", key=f"delete_course_{course['id']}", disabled=not confirmed, type="primary"):
                        try:
                            with st.spinner("正在删除课程…"):
                                result = deletion_service.delete_course(settings, course["id"])
                            clear_course_learning_state(course["id"])
                            if selected:
                                remaining = db.list_courses(settings.db_path)
                                st.session_state.course_id = None
                                st.session_state.pending_course_id = remaining[0]["id"] if remaining else None
                            st.session_state.flash = f"已删除课程「{result['course_name']}」"
                            st.session_state.deletion_warnings = result["warnings"]
                            st.rerun()
                        except deletion_service.DeletionError as exc:
                            st.error(str(exc))

st.write("")
with st.expander("连接与系统状态", expanded=False):
    st.caption("配置状态不代表已成功连接；可按需进行连接测试。")
    a, b, c = st.columns(3)
    a.metric("数据库", "就绪")
    b.metric("资料存储", "本机")
    c.metric("模型配置", "已配置" if settings.llm_ready else "待配置")
    if not settings.llm_ready:
        st.info("填写项目 .env 中的模型配置后重启应用，即可使用问答和出题功能。")
    if st.button("测试模型连接", disabled=not settings.llm_ready):
        from services.llm_service import LLMService
        with st.spinner("正在测试连接…"):
            result = LLMService(settings).ping()
        if result["ok"]:
            st.success(f"连接成功 · {result['model']} · {result['latency_ms']}ms")
        else:
            st.error(result["message"])
    with st.expander("查看配置详情（密钥已打码）"):
        st.json(settings.as_dict())
st.markdown('<div class="cm-footer">COURSEMATE &nbsp; / &nbsp; 每一次理解，都算进步。</div>', unsafe_allow_html=True)
