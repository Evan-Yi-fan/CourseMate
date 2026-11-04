# 阶段 A 验收报告

> 日期：2026-11-03　执行环境：Windows / Python 3.11.15（uv 安装）/ 项目目录 `C:\deepseek\CourseMate`

## 1. 环境决策与差异说明

任务书建议 Python 3.11。本机实际情况：

| 版本 | 路径 | 可用性 |
|---|---|---|
| 3.13.15 | `...\Programs\Python\Python313\python.exe` | 可用（系统默认） |
| 3.12 | `...\Programs\Python\Python312\python.exe` | **注册表残留，路径不存在**，`py -3.12` 直接报错 |
| 3.11.15 | `%APPDATA%\uv\python\cpython-3.11.15-...` | 本次用 uv 安装 |

**决策**：用 `uv python install 3.11` 装了一个干净的 3.11.15，并据此创建 `.venv`，
而不是迁就系统的 3.13。理由：与任务书一致；chromadb / onnxruntime / torch 在 3.13 上
轮子还不齐。**未删除、未覆盖任何现有 Python 环境。**

另：`uv venv` 创建的虚拟环境默认不含 pip，已额外安装 pip，保证 README 里的
`pip install -r requirements.txt` 在交付环境下能直接执行。

## 2. 依赖安装结果

`requirements.txt` 中 10 项全部安装成功，版本经实测锁定：

```
streamlit 1.66.1    openai 3.42.1        python-dotenv 1.2.4
pymupdf 2.1         python-docx 1.2.0    chromadb 1.5.9
sentence-transformers 6.2.0 (torch 2.15.0)   pandas 3.1.0   plotly 7.1.0
```

## 3. 自检结果

命令：`.venv\Scripts\python.exe scripts\check_env.py`

```
[ OK ] Python 版本  —  3.11.15 @ ...\CourseMate\.venv\Scripts\python.exe
[ OK ] 虚拟环境  —  ...\CourseMate\.venv
[ OK ] 依赖 streamlit / openai / dotenv / pymupdf / docx / chromadb
[ OK ] 可选依赖 sentence_transformers 6.2.0 / plotly 7.1.0 / pandas 3.1.0
[ OK ] 配置文件  —  ...\CourseMate\.env
[ OK ] 配置加载  —  chunk=600/100, top_k=4
[FAIL] LLM 配置  —  缺少 LLM_API_KEY、LLM_MODEL
[ OK ] 目录  —  data / data\chroma / data\uploads
[ OK ] SQLite  —  data\coursemate.db | 表 5/5 可读
[ OK ] ChromaDB  —  版本 1.5.9，写入+检索成功（已清理探测数据）
[WARN] 大模型连通性  —  未配置，已跳过
合计 20 项：OK 18 / WARN 1 / FAIL 1
```

唯一 FAIL 是**缺少用户自己的 API Key**，属于预期状态——密钥必须由用户填入 `.env`，
我没有也不应该伪造一次成功的模型调用。

## 4. 测试结果

命令：`.venv\Scripts\python.exe -m unittest discover -s tests -v`

```
Ran 12 tests in 0.975s
OK
```

包含 2 个 Streamlit `AppTest` 用例，真实执行 `app.py` 并模拟"填表→提交"，验证页面无异常、
成功提示可见。修复过程中发现并解决了一个真实缺陷：`st.success()` 后紧跟 `st.rerun()`
会把提示丢掉，导致用户创建课程后看不到反馈，已改为 `session_state` flash 传递。

## 5. 运行状态

`streamlit run app.py --server.port 8501` 启动成功，`/_stcore/health` 返回 `ok`，
首页可访问：http://127.0.0.1:8501

## 6. 未完成 / 待用户操作

1. **填入 API Key**：在 `.env` 里设置 `LLM_API_KEY` 与 `LLM_MODEL`（以账号实际可用列表为准），
   然后执行 `python scripts\check_env.py`，应看到 `[ OK ] 大模型连通性`。
2. 阶段 B 起的内容（上传、解析、分块、Embedding、ChromaDB 写入）尚未开始。
3. `EMBEDDING_PROVIDER=local` 首次运行需下载 `bge-small-zh-v1.5`（约 100MB），
   该步骤属于阶段 B 的联网风险点，尚未验证。
