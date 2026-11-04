"""两处出题入口共用资料范围与题型设置。"""
from __future__ import annotations

import streamlit as st

from database import db


def quiz_controls(settings, course_id: int, *, prefix: str):
    docs = [d for d in db.list_documents(settings.db_path, course_id) if d["status"] == "ready"]
    names = {d["id"]: d["filename"] for d in docs}
    ids = list(names)
    selection_key = f"{prefix}_docs_{course_id}"
    all_key = f"{prefix}_all_docs_{course_id}"
    selected = [did for did in st.session_state.get(selection_key, []) if did in names]
    st.session_state[selection_key] = selected
    st.session_state[all_key] = bool(ids) and len(selected) == len(ids)

    def select_all():
        st.session_state[selection_key] = ids if st.session_state[all_key] else []

    def sync_all():
        st.session_state[all_key] = bool(ids) and len(st.session_state[selection_key]) == len(ids)

    with st.container(border=True):
        left, right = st.columns(2)
        qtype = left.radio("题型", ["单选题", "判断题"], key=f"{prefix}_type", horizontal=True)
        count = right.number_input("题目数量", min_value=1, max_value=10, value=3, step=1, key=f"{prefix}_count")
        st.checkbox("全选课程资料", key=all_key, on_change=select_all, disabled=not ids)
        selected = st.multiselect("选择课程资料（必选，可多选）", ids,
                                  format_func=lambda did: names[did], key=selection_key,
                                  on_change=sync_all, placeholder="请选择出题依据的资料")
        if not ids:
            st.info("还没有已入库资料，请先到「课程知识库」上传。")
        elif not selected:
            st.caption("至少选择一份资料后才能生成题目。")
        generate = st.button("生成题目", type="primary", key=f"{prefix}_gen", disabled=not selected or not settings.llm_ready)
    return selected, int(count), "single" if qtype == "单选题" else "judge", generate
