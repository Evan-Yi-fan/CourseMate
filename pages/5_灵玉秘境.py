"""灵玉秘境：独立的游戏页面。

结构：
    战前答题（Python，服务端判分与奖励）
      → 把灵玉注入游戏（iframe 内运行）
      → 关卡结束由游戏把战报写回 URL，本页读取并展示

为什么游戏放在 iframe 里：拖拽、逐帧移动、堆叠遮挡这些交互，
Streamlit 原生组件做不到；游戏内核因此是自包含的 HTML/JS，
Python 只负责「答题 → 灵玉」和「战报 → 成绩」两端。
"""

from __future__ import annotations

import base64
import json

import streamlit as st
import streamlit.components.v1 as components

from config.settings import Settings
from database import db
from game.systems.reward_system import AnswerRecord, RewardCalculator
from game.config import economy_config as cfg
from game.view import build_config, build_html
from modes.base import complete_answers
from services.quiz_service import QuizError, QuizService, grade_batch
from ui.common import boot, course_selector, require_course
from ui.quiz import quiz_controls

st.set_page_config(page_title="灵玉秘境 · CourseMate", page_icon="🀄", layout="wide")

settings = boot()


def _take_game_result() -> None:
    """游戏结束时 JS 会带着 ?game_result=... 跳回来，这里接住并落状态。"""
    raw = st.query_params.get("game_result")
    if not raw:
        return
    try:
        payload = json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception:
        payload = {"win": False, "error": "战报解析失败"}
    st.session_state["lj_result"] = payload
    st.session_state["lj_stage"] = "result"
    st.query_params.clear()
    st.rerun()


_take_game_result()

stage = st.session_state.setdefault("lj_stage", "quiz")
course_id = None

st.title("灵玉秘境")
st.caption("五行卡牌 · 三消合成 · 棋盘布阵 · 神兽共鸣 —— 用你答题赚来的灵玉守卫人皇")

# ----------------------------------------------------------------------
# 阶段一：战前答题
# ----------------------------------------------------------------------
if stage == "quiz":
    if st.button("免答题试玩新场景", key="lj_preview"):
        st.session_state["lj_stage"] = "preview"
        st.rerun()
    course_id = require_course(course_selector(settings))
    course = db.get_course(settings.db_path, course_id)

    left, right = st.columns([3, 2], gap="large")

    with left:
        st.subheader("战前知识挑战")
        st.caption("；".join(cfg.reward_rules_text()) + "。")

        document_ids, count, qtype, generate = quiz_controls(settings, course_id, prefix="lj")
        if not settings.llm_ready:
            st.info("请先到「模型设置」配置大模型后生成题目，或使用免答题试玩。")
            st.page_link("pages/6_模型设置.py", label="前往模型设置", icon=":material/settings:")
        if generate:
            try:
                with st.spinner("正在出题…"):
                    qs = QuizService(settings).generate(course_id, count=count, question_type=qtype,
                                                        document_ids=document_ids)
                st.session_state["lj_questions"] = [q.public() for q in qs]
                st.session_state["lj_reward"] = None
                st.rerun()
            except QuizError as exc:
                st.error(f"出题失败：{exc}")
            except Exception as exc:
                st.error(f"出题失败：{type(exc).__name__}: {exc}")

        questions = st.session_state.get("lj_questions") or []
        if questions:
            with st.form("lj_quiz_form"):
                picked = {}
                for i, q in enumerate(questions, start=1):
                    st.markdown(f"**{i}. {q['question']}**")
                    opts = q["options"]
                    choice = st.radio(
                        f"q{i}", [o["key"] for o in opts],
                        format_func=lambda k, o=opts: next(
                            (f"{x['key']}. {x['text']}" for x in o if x["key"] == k), k),
                        key=f"lj_q_{q['id']}", label_visibility="collapsed", index=None,
                    )
                    if choice:
                        picked[int(q["id"])] = choice
                submitted = st.form_submit_button("提交并进入秘境", type="primary")

            if submitted:
                answers = complete_answers(questions, picked)
                graded = grade_batch(settings, answers)
                records = [AnswerRecord.from_grade(r) for r in graded["results"]]
                reward = RewardCalculator().calculate(records, len(questions))

                st.session_state["lj_reward"] = reward
                st.session_state["lj_jade"] = cfg.INITIAL_JADE + reward["total"]
                st.session_state["lj_stage"] = "play"
                st.rerun()
        else:
            st.info("先点上面的按钮生成题目。")

    with right:
        st.subheader("怎么玩")
        st.markdown(
            "- 只有**没有被上层遮挡的字牌**能取，取走后露出下一层\n"
            "- 同字占三个暂存格，集齐三张合一上阵；可关闭自动合成\n"
            "- 合成的字会填进 5×5 棋盘；备战和闯关均可拖动：空格移动、不同字交换、同阶同字融合，最高四星\n"
            "- 铲子可拖到指定封锁格，也可先点铲子再点目标；底部支持打乱 / 刷新 / 清空；每打完一波也会自动解锁一格，共守卫十二波\n"
            "- 妖怪沿外围道路走向人皇，漏怪扣血，越高级扣得越多\n"
            "- 神兽残字每副牌 0–2 个且不重复；先入神兽槽，槽满则落空棋盘；拖到棋盘横排「青龙」或「白虎」才激活；拖走单字即可拆解，三星以上字可喂给神兽升星"
        )

# ----------------------------------------------------------------------
# 阶段二：游戏
# ----------------------------------------------------------------------
elif stage in ("play", "preview"):
    course_id = st.session_state.get("course_id")
    course = db.get_course(settings.db_path, course_id) if course_id else None
    jade = cfg.INITIAL_JADE if stage == "preview" else int(st.session_state.get("lj_jade", cfg.INITIAL_JADE))
    reward = st.session_state.get("lj_reward") or {}

    if stage == "preview":
        st.info(f"试玩模式：初始灵玉为 {cfg.INITIAL_JADE}，可取牌、合成和出战；不生成或记录答题成绩。")
    else:
        st.success(f"初始 {cfg.INITIAL_JADE} + 答题奖励 {reward.get('total', 0)} = 本局 **{jade}** 灵玉，进入秘境。")
    if stage != "preview" and reward.get("items"):
        st.caption("　".join(f"{i['name']} +{i['amount']}" for i in reward["items"]))

    html = build_html(build_config(jade, course_name=(course or {}).get("name", "")))
    components.html(html, height=1400, scrolling=True)

    st.caption("提示：游戏是独立运行的，期间不要操作下方按钮，否则页面刷新会重置本局。")
    if st.button("返回战前答题", key="lj_abort"):
        st.session_state["lj_stage"] = "quiz"
        st.session_state.pop("lj_reward", None)
        st.rerun()

# ----------------------------------------------------------------------
# 阶段三：结算
# ----------------------------------------------------------------------
else:
    result = st.session_state.get("lj_result") or {}
    win = bool(result.get("win"))
    if win:
        st.balloons()
        st.success("秘境通关！")
    else:
        st.error("防守失败，人皇被攻破了。")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("到达波次", f"{result.get('wave', 0)}")
    c2.metric("击杀妖怪", result.get("kills", 0))
    c3.metric("漏怪", result.get("leaked", 0))
    c4.metric("剩余生命", result.get("hp", 0))

    st.caption("答题记录已保存到学习数据里；本局灵玉与局内购买已清零。")
    if st.button("再来一局", type="primary", key="lj_again"):
        for k in ("lj_stage", "lj_reward", "lj_jade", "lj_result", "lj_questions"):
            st.session_state.pop(k, None)
        st.rerun()
