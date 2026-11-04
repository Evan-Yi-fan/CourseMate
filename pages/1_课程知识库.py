"""课程知识库：上传资料、解析入库、查看处理状态。

对应 F02 / F03 / F04。
"""

from __future__ import annotations

import streamlit as st

from database import db
from knowledge.retriever import CourseIndex
from services import document_service as docsvc
from services import deletion_service
from ui_common import boot, course_selector, error_box, require_course, clear_course_learning_state

st.set_page_config(page_title="课程知识库 · CourseMate", page_icon="📄", layout="wide")

settings = boot()
course_id = require_course(course_selector(settings))

course = db.get_course(settings.db_path, course_id)
st.title("课程知识库")
st.caption(f"当前课程：**{course['name']}**　·　上传 PDF / DOCX / TXT / PPTX / PPT 后自动解析并建立向量索引")

flash = st.session_state.pop("document_flash", None)
if flash:
    st.success(flash)
for warning in st.session_state.pop("document_deletion_warnings", []):
    st.warning(warning)

index = CourseIndex(settings, course_id)
docs = docsvc.describe_documents(settings, course_id)

# ----------------------------------------------------------------------
# 概览
# ----------------------------------------------------------------------
ready = [d for d in docs if d["status"] == "ready"]
c1, c2, c3 = st.columns(3)
c1.metric("资料数量", len(docs))
c2.metric("已入库", len(ready))
c3.metric("向量块总数", index.count())

st.divider()

# ----------------------------------------------------------------------
# 上传
# ----------------------------------------------------------------------
st.subheader("上传资料")
for message in st.session_state.pop("upload_successes", []):
    st.success(message)
upload_failures = st.session_state.pop("upload_failures", [])
if upload_failures:
    with st.expander(f"有 {len(upload_failures)} 个文件失败，点击查看原因", expanded=True):
        for name, message in upload_failures:
            st.error(f"**{name}**\n\n{message}")
st.caption(
    f"支持 PDF / DOCX / TXT / PPTX / PPT，单个文件不超过 {settings.max_upload_mb}MB。"
    "扫描版 PDF（无文字层）无法解析，本项目不含 OCR。PPTX 按幻灯片页码提取正文、表格、组合图形和备注；旧版 PPT 需本机 PowerPoint。"
)

upload_version_key = f"upload_version_{course_id}"
uploaded = st.file_uploader(
    "选择文件（可多选）",
    type=["pdf", "docx", "txt", "pptx", "ppt"],
    accept_multiple_files=True,
    label_visibility="collapsed",
    key=f"course_upload_{course_id}_{st.session_state.get(upload_version_key, 0)}",
)

if uploaded and st.button(f"开始处理 {len(uploaded)} 个文件", type="primary"):
    progress = st.progress(0.0, text="准备处理…")
    successes, failed = [], []
    for i, uf in enumerate(uploaded, start=1):
        progress.progress((i - 1) / len(uploaded), text=f"正在处理 {uf.name} …")
        try:
            data = uf.getvalue()
            # 先做类型/大小校验，把错误挡在落盘之前
            docsvc.validate_upload(settings, uf.name, len(data))
            result = docsvc.handle_upload(settings, course_id, uf.name, data)
            successes.append(
                f"「{uf.name}」已入库：{result['pages']} 页 → {result['chunks']} 个向量块"
            )
        except Exception as exc:  # noqa: BLE001
            failed.append((uf.name, f"{type(exc).__name__}: {exc}"))
    progress.progress(1.0, text="处理完成")

    st.session_state.upload_successes = successes
    st.session_state.upload_failures = failed
    # 换一个上传组件实例清空选择，处理结果跨重绘保留。
    st.session_state[upload_version_key] = st.session_state.get(upload_version_key, 0) + 1
    st.rerun()

st.divider()

# ----------------------------------------------------------------------
# 文档列表
# ----------------------------------------------------------------------
st.subheader("文档列表")

STATUS_STYLE = {
    "ready": ("✅ 已入库", "normal"),
    "pending": ("⏳ 处理中", "normal"),
    "failed": ("❌ 失败", "inverse"),
}

if not docs:
    st.info("还没有上传任何资料。")
else:
    for d in docs:
        label, _ = STATUS_STYLE.get(d["status"], (d["status"], "normal"))
        with st.container(border=True):
            left, mid, right = st.columns([3, 2, 1])
            with left:
                st.markdown(f"**{d['filename']}**")
                st.caption(f"{d['file_type'].upper()} · 上传于 {d['created_at']}")
            with mid:
                st.markdown(f"{label}　·　{d['chunk_count']} 个向量块")
                if d["status"] == "failed" and d.get("error"):
                    st.caption(d["error"][:200])
            with right:
                if st.button("重建索引", key=f"reindex_{d['id']}"):
                    try:
                        with st.spinner("重建中…"):
                            r = docsvc.reindex_document(settings, d["id"])
                        st.success(f"已重建：{r['chunks']} 个向量块")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        error_box("重建失败", exc)

                with st.popover("删除资料", icon=":material/delete_outline:", use_container_width=True):
                    st.warning(f"将永久删除「{d['filename']}」的上传文件与检索索引。")
                    st.caption("已有题目、答题记录和历史聊天保留。")
                    confirmed = st.checkbox("确认删除这份资料", key=f"confirm_delete_document_{d['id']}")
                    if st.button("确认删除资料", key=f"delete_document_{d['id']}", disabled=not confirmed, type="primary"):
                        try:
                            with st.spinner("正在删除资料…"):
                                result = deletion_service.delete_document(settings, course_id, d["id"])
                            clear_course_learning_state(course_id)
                            st.session_state.document_flash = f"已删除资料「{result['filename']}」"
                            st.session_state.document_deletion_warnings = result["warnings"]
                            st.rerun()
                        except deletion_service.DeletionError as exc:
                            st.error(str(exc))
