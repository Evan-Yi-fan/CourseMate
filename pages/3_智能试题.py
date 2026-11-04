"""智能试题：生成 → 选模式作答 → 判分 → 解析。

对应 F08 / F09。答题模式通过 modes 注册表切换，页面不认识具体玩法。
"""

from __future__ import annotations

import streamlit as st

from database import db
from knowledge.retriever import CourseIndex
from modes import PlayContext, all_modes, get_mode
from services.quiz_service import QuizError, QuizService, grade_batch
from ui_common import boot, course_selector, require_course
from ui_quiz import quiz_controls

st.set_page_config(page_title="智能试题 · CourseMate", page_icon="📝", layout="wide")

settings = boot()
course_id = require_course(course_selector(settings))
course = db.get_course(settings.db_path, course_id)

st.title("智能试题")
st.caption(f"当前课程：**{course['name']}**　·　题目由大模型依据课程资料生成，判分由程序完成")

if CourseIndex(settings, course_id).count() == 0:
    st.warning("这门课程还没有建立索引，请先到「课程知识库」上传资料。")
    st.stop()

if not settings.llm_ready:
    st.error("大模型未配置：请在 `.env` 中填写 LLM_API_KEY 与 LLM_MODEL 后重启。")
    st.stop()

QK, RK = "quiz_questions", "quiz_result"

# ----------------------------------------------------------------------
# 出题
# ----------------------------------------------------------------------
document_ids, count, qtype, gen = quiz_controls(settings, course_id, prefix="quiz")

if gen:
    with st.spinner(f"正在根据所选资料生成 {count} 道题…"):
        try:
            questions = QuizService(settings).generate(
                course_id, count=int(count), question_type=qtype,
                document_ids=document_ids,
            )
            st.session_state[QK] = [q.public() for q in questions]
            st.session_state[RK] = None
            st.success(f"已生成 {len(questions)} 道题。")
        except QuizError as exc:
            st.error(f"出题失败：{exc}")
            st.session_state[QK] = None
        except Exception as exc:  # noqa: BLE001
            st.error(f"出题失败：{type(exc).__name__}: {exc}")
            st.session_state[QK] = None

st.divider()

# ----------------------------------------------------------------------
# 作答
# ----------------------------------------------------------------------
questions = st.session_state.get(QK)
if not questions:
    st.info("先生成一组题目。")
    st.stop()

st.subheader(f"作答（共 {len(questions)} 题）")

modes = all_modes()
mode_labels = {m.label: m for m in modes}
default_label = modes[0].label
picked_label = st.radio(
    "答题模式",
    list(mode_labels),
    index=list(mode_labels).index(default_label),
    horizontal=True,
    help="普通答题与游戏答题共用同一套题库与判分逻辑",
)
mode = mode_labels[picked_label]
st.caption(f"**{mode.label}** — {mode.description}")

answers = mode.render(PlayContext(
    settings=settings, course_id=course_id, questions=questions, key_prefix=f"q{course_id}",
))

if answers:
    result = grade_batch(settings, {int(k): v for k, v in answers.items()})
    st.session_state[RK] = result
    st.rerun()

# ----------------------------------------------------------------------
# 结果
# ----------------------------------------------------------------------
result = st.session_state.get(RK)
if result:
    st.divider()
    st.subheader("答题结果")
    m1, m2, m3 = st.columns(3)
    m1.metric("得分", f"{result['score']:.0f}")
    m2.metric("答对", f"{result['correct']}/{result['total']}")
    m3.metric("正确率", f"{result['score']:.1f}%")

    blank = [r for r in result["results"] if not r["user_answer"]]
    if blank:
        st.warning(f"有 {len(blank)} 道题未作答，已按答错计入总分。")

    for i, r in enumerate(result["results"], start=1):
        ok = r["is_correct"]
        with st.container(border=True):
            st.markdown(f"{'✅' if ok else '❌'} **{i}. {r['question']}**")
            st.caption(
                f"你的答案：{r['user_answer'] or '（未作答）'}　·　"
                f"正确答案：{r['correct_answer']}　·　知识点：{r['knowledge_point']}"
            )
            if r["explanation"]:
                st.markdown(f"解析：{r['explanation']}")
            elif not ok:
                st.caption("（这题模型没有给出解析）")

    c1, c2 = st.columns(2)
    if c1.button("用同一批题再做一次"):
        st.session_state[RK] = None
        st.rerun()
    if c2.button("再生成一组新题"):
        st.session_state[QK] = None
        st.session_state[RK] = None
        st.rerun()
