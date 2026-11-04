"""无需创建课程即可配置模型，保存后各页面立即使用新配置。"""
from __future__ import annotations

import streamlit as st

from config import model_settings
from config.settings import ConfigError
from services.llm_service import LLMService
from ui.common import boot

st.set_page_config(page_title="模型设置 · CourseMate", page_icon="⚙️", layout="wide")
settings = boot()
st.title("模型设置")
st.caption("在这里连接你的大模型，保存后即可用于问答、出题和复习建议，无需修改 .env 或重启。")

if st.session_state.pop("model_clear_secret", False):
    st.session_state.pop("model_api_key", None)
flash = st.session_state.pop("model_settings_flash", None)
if flash:
    st.success(flash)
try:
    model_settings.read(settings)
except ConfigError as exc:
    st.warning(str(exc))

PRESETS = {
    "DeepSeek": ("deepseek", "https://api.deepseek.com"),
    "通义千问（兼容接口）": ("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "自定义 OpenAI 兼容接口": ("custom", ""),
}
default = next((name for name, (provider, url) in PRESETS.items()
                if url and settings.llm_base_url.rstrip('/') == url), "自定义 OpenAI 兼容接口")


def choose_preset():
    _, url = PRESETS[st.session_state.model_preset]
    st.session_state.model_base_url = url
    st.session_state.model_name = ""
    st.session_state.model_api_key = ""


for key, value in {"model_base_url": settings.llm_base_url, "model_name": settings.llm_model}.items():
    if key not in st.session_state:
        st.session_state[key] = value

left, right = st.columns([3, 2], gap="large")
with left:
    with st.container(border=True):
        st.subheader("连接信息")
        preset = st.selectbox("服务类型", list(PRESETS), index=list(PRESETS).index(default),
                              key="model_preset", on_change=choose_preset)
        with st.form("model_settings_form"):
            url = st.text_input("API 地址（Base URL）",
                                key="model_base_url", placeholder="https://你的服务地址/v1")
            model = st.text_input("模型名称", key="model_name",
                                  placeholder="填写账号中可用的模型 ID")
            secret = st.text_input("API 密钥", type="password", key="model_api_key",
                                   placeholder="已配置，留空沿用（仅限相同接口地址）" if settings.llm_api_key else "输入你的 API 密钥")
            st.caption("已有密钥不会回填到输入框。更换接口地址后，请重新填写对应服务的密钥。")
            timeout = st.number_input("请求超时（秒）", min_value=5, max_value=180,
                                       value=max(5, min(180, int(settings.llm_timeout))), step=5, key="model_timeout")
            save_col, test_col = st.columns(2)
            save = save_col.form_submit_button("保存配置", type="primary", use_container_width=True)
            test = test_col.form_submit_button("测试当前填写配置", use_container_width=True)
        st.caption("保存不会发起模型请求；连接测试会发送一条短消息，可能产生少量 API 用量。")

    if save or test:
        try:
            candidate = model_settings.candidate(settings, provider=PRESETS[preset][0],
                                                  base_url=url, api_key=secret, model=model, timeout=timeout)
            if save:
                model_settings.save(candidate)
                st.session_state.model_settings_flash = "模型配置已保存并立即生效，可以开始问答或出题。"
                st.session_state.model_clear_secret = True
                st.rerun()
            else:
                with st.spinner("正在验证接口、密钥和模型…"):
                    result = LLMService(candidate).ping()
                if result["ok"]:
                    st.success(f"连接成功 · 模型 {result['model']} · 耗时 {result['latency_ms']}ms")
                    st.caption("测试通过后，点击「保存配置」应用当前填写的内容。")
                else:
                    st.error(result["message"])
        except ConfigError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"操作未完成：{type(exc).__name__}，请检查配置后重试。")

with right:
    st.subheader("当前应用配置")
    st.metric("模型状态", "已配置" if settings.llm_ready else "待配置")
    st.write("**模型名称：**", settings.llm_model or "未设置")
    st.write("**接口地址：**", settings.llm_base_url or "未设置")
    st.caption("已配置表示字段完整，是否能够调用请以连接测试结果为准。")
    st.info("配置保存在本机数据目录，不会提交到 GitHub。密钥以本地明文文件保存，请勿分享该配置文件。")
    st.caption("界面保存的模型设置优先于环境变量和 .env。本地向量模型与资料索引保持原配置，更换聊天模型无需重建资料索引。")
    st.page_link("pages/2_AI智能问答.py", label="前往 AI 智能问答", icon=":material/forum:")
