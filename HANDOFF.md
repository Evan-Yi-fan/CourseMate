> **路线与四星木修复（2026-11-04）**：怪物下侧旧坐标4.55落在棋盘第五行，现改为5.7；四周路线距棋盘0.7格。道路使用SVG开放直角折线，与怪物共用PATH，左上入口至人皇之间不绘制连接段。四星木保留内部升阶标识，改用固定四木田字形矢量字形，避免字体替换造成结构差异。148项游戏断言通过（含200/320/480像素棋盘全路线边界检查）。浏览器截图验收受本地预览访问权限拒绝，未完成实际浏览器显示核验。

> **上传、问答与出题交互更新（2026-11-04）**：上传批次结束后重置上传组件并保留成功/失败提示；问答示例改为总结资料与定位知识点，点击仅填入草稿、不自动发送。智能试题与灵玉秘境共用 ui_quiz.py，支持题型、1–10题、已入库资料必选多选与全选，QuizService.document_ids 严格校验课程归属并逐份取样。灵玉统一每局初始30、答对一题10，仅按答对题数发奖，取消连对/完成/全对额外奖励；试玩及游戏内重开恢复30，不重复发答题奖励。当前135项Python用例（全量134通过后新增1项游戏奖励交互，页面10项通过）、139项游戏断言通过。

> **课程管理更新（2026-11-04）**：创建课程只需名称，已移除简介输入框。首页课程卡片支持删除整门课程（含文件、索引、题目、答题和聊天记录）；课程知识库支持删除单份资料（保留题目与学习历史）。页面均需勾选确认，删除过程支持文件和索引失败回退。127项Python测试通过。新增服务services/deletion_service.py，回归用例tests/test_deletion.py。

> **PPT课件支持更新**：现在接受.pptx与.ppt。PPTX按幻灯片提取正文、表格、组合图形、常见图表和备注，保留真实页序；旧版PPT需Windows本机PowerPoint，禁用宏后在独立进程转换。111项Python测试通过，并已实测真实旧版PPT完整入库检索。详见docs/PPT课件支持验收.md。

> **字形与界面最新修订**：四星已改为燚等完整四叠汉字，删除了“拆”按钮及右上角青龙共鸣标识。神兽仍可直接拖走单字拆解。最新139项游戏断言通过；下文此前的“四角拼字”“拆按钮”描述已过时。

> **最新规则修订**：水系二星为沝，普通字可合成四星并四角堆字显示。棋盘字在备战/闯关均可移动与交换；神兽可拆解，吞噬三星以上字按55%升星，最高五星；拆解重组保留本局星级。最新98项Python测试、136项游戏断言通过。以下旧版条目以此及当前代码为准。

> **2026-11-04 更新**：游戏已按参考视频重做为黄沙古道版。当前98项Python测试、106项游戏断言通过；三点生命、十二波、四层60牌、靠边随机连通五格、独立暂存格及免答题试玩。下文为旧版交接历史，游戏相关规则以 `docs/黄沙古道改版验收.md` 与当前代码为准。

# 接手文档（Handoff）

> 项目：**CourseMate · 灵玉秘境**　｜　最后更新：2026-11-03 23:20
> 面向对象：接手继续开发的工程师 / AI 编程助手（Codex）
> 请先完整读一遍本文件，再动代码。**第 9 节的坑踩过一遍就够了。**

---

## 1. 一页速览

一个**本地单机**的课程学习助手 + 一个**独立小游戏**：

- **学习闭环**（Python / Streamlit）：上传课程资料 → 建向量库 → 带来源的 RAG 问答 → AI 出题 → 在线答题判分 → 学习分析。
- **游戏《灵玉秘境》**（自包含 HTML/JS，跑在 iframe 里）：先答题赚「灵玉」→ 进游戏点卡池 → 暂存格三合一 → 5×5 棋盘布阵 → 抵挡妖怪三波。

当前状态：**功能完整可玩，94 个 Python 测试 + 45 个游戏内核测试全绿**，卡在一个"还能再打磨"的阶段。

比赛背景：单人参赛、3 天开发、**周四 12:00 作品信息封版**（提交项：作品信息 / 海报 / 源码仓库 / 3 分钟演示视频 / 可选体验链接）。

---

## 2. 环境与运行

| 项 | 值 |
|---|---|
| 项目根 | `C:\deepseek\CourseMate` |
| 虚拟环境 | `C:\deepseek\CourseMate\.venv`（**Python 3.11.15**，由 uv 安装） |
| 依赖 | `requirements.txt`（版本已锁定，全部实测通过） |
| 服务端口 | 8501 |

```powershell
cd C:\deepseek\CourseMate

# 启动
.venv\Scripts\python.exe -m streamlit run app.py --server.port 8501 --server.headless true

# 全量测试
.venv\Scripts\python.exe -m unittest discover -s tests
```

`.env` 已配好（**含真实 Key，不要提交到仓库**）：

```
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-****            # 已在 .env 中
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_OFFLINE=true         # 模型已缓存，只读本地、不联网
HF_ENDPOINT=https://hf-mirror.com
```

> ⚠️ 换机器时把 `EMBEDDING_OFFLINE` 改回 `false`，让 bge 模型重新下载一次。

---

## 3. 目录与职责

```
CourseMate/
├─ app.py                    # 首页：课程总览 / 创建课程 / 系统自检
├─ ui_common.py              # 页面共用：boot() 配置+建库、课程选择器
├─ config/settings.py        # 全部环境变量 → Settings（frozen dataclass）
├─ database/db.py            # sqlite3：5 张表 + 全部 SQL（无 ORM）
│
├─ services/                 # 业务层
│  ├─ llm_service.py         # OpenAI 兼容封装（超时/重试/错误分类/ping）
│  ├─ document_service.py    # 上传校验、落盘、解析入库、同名替换
│  ├─ qa_service.py          # RAG 问答：检索→两段式拒答→引用解析→落库
│  ├─ quiz_service.py        # 出题 + JSON 严格校验 + 判分
│  └─ analysis_service.py    # 学习分析 + AI 复习建议
│
├─ knowledge/                # RAG 组件
│  ├─ parser.py              # PDF(保留页序)/DOCX(含表格)/TXT(GBK 兜底)
│  ├─ splitter.py            # 中文分块，按页切、不跨页
│  ├─ embeddings.py          # local / openai / hash 三种向量后端
│  └─ retriever.py           # ChromaDB，按课程一个 collection
│
├─ agent/                    # 单 Agent
│  ├─ assistant.py           # 意图路由：规则优先 → LLM 分类 → 兜底问答
│  ├─ tools.py               # knowledge_search / generate_quiz / analyze_mistakes
│  └─ prompts.py             # 问答与出题 Prompt
│
├─ modes/                    # 答题模式插件（现在只剩 normal）
│  ├─ base.py                # QuizMode 协议 + complete_answers()
│  └─ normal_mode.py         # 普通答题表单
│
├─ pages/
│  ├─ 1_课程知识库.py         # 上传 / 状态 / 重建索引
│  ├─ 2_AI智能问答.py         # 问答 + Agent 路由开关
│  ├─ 3_智能试题.py           # 出题 → 作答 → 判分 → 解析
│  ├─ 4_学习分析.py           # 正确率 / 错题 / 知识点 / AI 建议
│  └─ 5_灵玉秘境.py           # ★ 游戏页：答题 → 进游戏 → 结算
│
├─ game/                     # ★ 游戏
│  ├─ config/economy_config.py  # 奖励/价格/波次/五行链，数值唯一来源
│  ├─ systems/reward_system.py  # 服务端算灵玉（去重、连对、完成、全对）
│  ├─ view.py                   # 读 web/ 资源 + 注入配置 → 完整 HTML
│  └─ web/
│     ├─ index.html             # 骨架（含 __CSS__/__CONFIG__/__JS__ 占位）
│     ├─ game.css               # 全部样式（自写，无第三方素材）
│     ├─ game.js                # 游戏内核（约 800 行）
│     └─ test_game.js           # 内核交互测试（Node + jsdom，45 项）
│
├─ samples/                  # 自建课程样例（无版权问题）
├─ scripts/                  # check_env / make_sample_docs / seed_demo
├─ tests/                    # 94 个 Python 用例
└─ docs/                     # 各阶段验收报告 + 代码检查报告
```

---

## 4. 两套系统怎么连起来

### 4.1 学习闭环（纯 Python）

```
上传 → parser 抽文本 → splitter 分块 → bge 向量化 → ChromaDB
提问 → 检索 top_k → 相似度阈值 → Prompt → LLM → 解析 [n] 引用 → 落库
出题 → 检索上下文 → LLM 出 JSON → 严格校验（数量/选项/答案）→ 落库
判分 → 纯字符串比对（不交给模型）→ quiz_attempts
```

关键设计（改动前务必理解）：

- **两段式拒答**：阈值 0.35 先挡"完全不相关"；模型再说"资料中没有依据"时再挡"相关但无答案"。少一层就会出现看着专业却没依据的回答。
- **判分不交给模型**：`user_answer == correct` 由 Python 比对。
- **同名上传=替换**：`document_service.handle_upload` 按 `(course_id, filename)` 查旧记录，覆盖向量，避免重复。

### 4.2 游戏（iframe 内运行）

```
pages/5_灵玉秘境.py
  ├─ 战前答题（Python）：QuizService 出题 → grade_batch 判分 → RewardCalculator 算灵玉
  ├─ 注入：game/view.py 把 economy_config 打包成 window.CM_CONFIG
  ├─ 游戏：components.html(html, height=1180)  ← 自包含，无外部请求
  └─ 结束：JS 把战报写成 ?game_result=<base64> → 页面读取 → 展示结算
```

**为什么用 iframe**：拖拽合成、卡片遮挡层级、妖怪逐帧移动，Streamlit 原生控件做不到。
**边界**：灵玉**来源**在服务端算（页面伪造不了），局内**消费**在 JS 侧扣减。

战报回写实现（`game.js` 的 `reportResult`）：

```js
window.parent.location.href =
  window.parent.location.pathname + '?game_result=' + encodeURIComponent(b64);
```

页面侧（`pages/5_灵玉秘境.py` 顶部 `_take_game_result()`）读 `st.query_params`，
写进 `session_state` 后 `st.query_params.clear()` 并 rerun。

---

## 5. 游戏规则现状（精确值）

### 5.1 棋盘与流程

| 项 | 值 | 位置 |
|---|---|---|
| 棋盘 | 5×5 | `economy_config.BOARD_SIZE` |
| 开局开放格 | **随机连通的 5 格**（偏向左侧） | `game.js::randomUnlock` |
| 暂存格 | 5（可扩到 7） | `CFG.slots` |
| 波数 | 3，每波 6/8/10 只 | `GAME_SETTINGS` |
| 人皇生命 | 10 | 同上 |
| 漏怪伤害 | 妖兵 1 / 妖将 2 / 妖王 3 | `game.js::ENEMY` |

### 5.2 五行与升阶

只保留 **金木水火土**，每行三阶（生僻字照用）：

```
金 → 鍂 → 鑫
木 → 林 → 森
水 → 沝 → 淼
火 → 炎 → 焱
土 → 圭 → 垚
```

- **暂存格**：同字满 3 张 → 合成**该字本身**（三个金还是金），自动落到棋盘。
- **棋盘**：两个**同级同字**合并 → 升一阶（金+金→鍂，鍂+鍂→鑫）。
- 关掉底部「自动合成」后，暂存格满 3 张不自动合，需**点一下**才合。

### 5.3 神兽

- 棋盘**左侧竖排 2 格**是神兽槽。
- 青+龙 → 青龙；白+虎 → 白虎（**顺序敏感**，可拖动交换）。
- 凑齐即作为**横跨两格**的单位上阵，右侧格被占据；攻击判定取两格中点。
- 青龙 34 伤 / 3.2 范围；白虎 26 伤 / 2.8 范围 / 1.5 攻速。

### 5.4 妖怪路径

左侧进入 → 沿下边向右 → 右边向上 → 扑向顶部中央的人皇：

```js
const PATH = [[-0.55,-0.4],[-0.55,4.55],[5.55,4.55],[5.55,-0.55],[2.5,-0.55]];
```

### 5.5 底部按钮

| 按钮 | 价格 | 行为 |
|---|---|---|
| 铲子 | 20 灵玉 | 解锁一个封锁格（挑离中心最近的） |
| 打乱 | 15 灵玉 | 重排牌堆，**只替换仍存在的位置**（否则会凭空补牌） |
| 出战 | — | 开始下一波 |
| 刷新 | 30 灵玉 | 整副牌堆换新 |
| 清空 | 免费 | 棋盘上普通字撤回暂存格（神兽不动） |
| 自动合成 | — | 勾选框，控制暂存格是否自动三合一 |

---

## 6. 测试

### 6.1 Python（94 个）

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests
```

| 文件 | 数量 | 覆盖 |
|---|---|---|
| test_core | 10 | 配置校验、密钥打码、建表、外键、级联 |
| test_app_smoke | 2 | `AppTest` 真跑 app.py |
| test_knowledge | 21 | 解析、分块、索引、同名替换、路径穿越 |
| test_qa | 11 | 拒答两道闸、引用越界、历史落库 |
| test_quiz | 29 | JSON 校验、出题、判分、工具参数、意图路由 |
| test_reward | 7 | 奖励规则（含文档示例 55） |
| test_analysis | 5 | 学习分析口径、无数据不编 |
| test_modes | 9 | 评分口径、模式注册表 |

### 6.2 游戏内核（45 项，Node + jsdom）

```powershell
# 首次需要装 jsdom（用 pnpm，机器上没有 npm）
node "C:\Users\27303\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\pnpm\bin\pnpm.mjs" add jsdom
node game/web/test_game.js
```

- 测试跑在 jsdom 里，真实构造 DOM、真实派发 click / drag 事件。
- 用 `beforeParse` 注入固定种子（`mulberry32(20261103)`），**保证可复现**——之前不加种子，同一套代码两次结果不同。
- 游戏对象通过 `window.__CM_DEBUG` 暴露（`S`、`addToSlot`、`tryMerge`、`placeBeastChar`、`startWave`、`checkWaveEnd` 等），加新逻辑时记得同步暴露。

---

## 7. 已知问题 / 技术债（按严重度）

| # | 问题 | 影响 | 建议 |
|---|---|---|---|
| 1 | **iframe 会在任何 Streamlit rerun 时重载**，本局进度丢失 | 玩到一半点了页面其他控件就全没了 | 页面在 play 阶段尽量不放控件；或把游戏状态序列化进 `st.query_params`/localStorage |
| 2 | **吞噬升星功能在重写后丢了** | 你之前要求"三阶字拖到激活神兽上概率升星"，现在没有 | 见 TODO P1 |
| 3 | **价格重复定义**：`game.js` 里 `const PRICE = {shovel:20,...}` 与 `economy_config.GAME_SHOP` 各写一份 | 改价要改两处 | 统一从 `CFG.shop` 读 |
| 4 | **关卡进度/战绩不落库** | 通关后没有"解锁下一关"、没有历史战绩 | 加 `game_runs` 表，靠 `?game_result=` 回写时写入 |
| 5 | 局内消费在 JS 侧结算 | 无法服务端审计 | 若需要，把每笔购买随战报回传 |
| 6 | 神兽不能拆解/移动 | 点击只提示"不能撤回" | 原作"激活后仍可拆解"，要补 |
| 7 | 无音效，动画只有卡片 hover 与受击闪动 | 演示观感偏素 | 见 TODO P2 |
| 8 | 合体字配方（日+月→明、小+大→尖）未做 | 玩法深度少一层 | 用户明确说"暂不加" |
| 9 | 金币系统未做 | 原作局内有金币（看广告给） | **不要做广告**，可换成灵玉 |
| 10 | 数值未经过真人试玩 | 难度可能偏难/偏易 | 用户试玩后调 `GAME_SETTINGS` 与 `ENEMY` |

---

## 8. TODO（按优先级，带验收标准）

### P0 · 交付前必须有

- [ ] **重开一局**：结算面板里能直接开下一关，不用回 Streamlit 页面重进。
      *验收*：点「再来一关」后灵玉归零、卡槽 5 格、棋盘重新随机开放 5 格。
- [ ] **跑通完整演示流程一遍**（见第 10 节），确认无异常。
- [ ] **确认仓库不含 `.env`**（`.gitignore` 已包含，提交前仍需肉眼确认）。

### P1 · 体验完整性

- [ ] **补回吞噬升星**：三阶字（焱/淼/垚/鑫）拖到已激活神兽字上 → 消耗一张 → 55% 升 1 星（上限 5 星），星级提高该神兽的全局增益。
      *验收*：jsdom 测试里能断言"一阶字不能吞、三阶字能吞、星级单调不减"。
- [ ] **神兽拆解**：点击已上阵的神兽 → 拆回两个部件字（回到神兽槽），并移除棋盘上的两格占用。
- [ ] **价格统一**：删掉 `game.js::PRICE`，改读 `CFG.shop`。
- [ ] **数值调平衡**：根据试玩反馈调 `GAME_SETTINGS.enemies_per_wave` / `ENEMY` 血量。

### P2 · 打磨

- [ ] 合成/上阵/结算的动效（CSS transform + transition 即可，别引入库）。
- [ ] 简单音效（可用 WebAudio 合成，避免引入音频文件）。
- [ ] 战报里显示"本局最高星级""总击杀"，让结算更有成就感。
- [ ] 关卡进度落库（`game_runs` 表），支持"解锁下一关"。

### P3 · 明确不做

- ❌ 广告解锁位（赛事任务书明确要求不复刻广告机制）
- ❌ 合体字配方（用户暂缓）
- ❌ 登录/多用户/多租户

---

## 9. 踩坑记录（重要，能省你几个小时）

### 9.1 PowerShell 与中文字符串

- 用 `python -c "..."` 传中文/引号时，PowerShell 会把引号和反引号吃掉，报莫名其妙的 SyntaxError。
- **正确做法**：把补丁脚本写成 `.py` 文件再执行，不要用内联 `-c`。
  本项目大量改动都是"写 `_tmp.py` → 运行 → 删掉"。
- 反引号在双引号字符串里是转义符，markdown 的反引号会被吃掉。

### 9.2 Streamlit

- `st.success()` 后立刻 `st.rerun()` → **提示会被吞掉**。要么用 `session_state` 传一次性消息，要么把提示放到 rerun 之后。
- `@st.cache_resource` 会在测试之间缓存，**换临时目录的测试必须 `st.cache_resource.clear()`**，否则连到上一个已删除的库。
- 表单里的控件在提交前改值不会生效，`AppTest` 要"先填完再一次性点提交"。

### 9.3 ChromaDB / Windows

- Chroma 持有文件句柄，`TemporaryDirectory` 清理会报 `WinError 32`。
  → 用 `tempfile.TemporaryDirectory(ignore_cleanup_errors=True)` + `retriever.reset_clients()`。

### 9.4 依赖

- `uv venv` 建的环境**不含 pip**，`pip install -r` 会失败。已补装 pip。
- 本机 `py -0p` 里的 Python 3.12 是**注册表残留**（路径不存在），别用。
- sentence-transformers 6.x 把 `get_sentence_embedding_dimension` 改名为 `get_embedding_dimension`，代码里已做兼容。

### 9.5 游戏内核

- jsdom 里 `getBoundingClientRect()` 全是 0，敌人坐标会算成 0 —— 逻辑测试没问题，但**别在 jsdom 里断言像素位置**。
- 每次 `renderDeck()` 都会重建 DOM，**测试里持有的旧节点会失效**，要用 `querySelector` 重新查。
- `Math.random` 不固定会让测试时好时坏，见 6.2。
- 「打乱」如果按 `filter(Boolean)` 后从 0 填充，会把已取走的空位补满 → 牌数变多。只能替换原位置。

---

## 10. 演示流程（3 分钟视频照着走）

| 时间 | 画面 | 要点 |
|---|---|---|
| 0:00–0:25 | 首页 | 痛点：课程资料分散、问答没出处、练习费时 |
| 0:25–0:55 | 课程知识库 | 上传 PDF → 状态变"已入库"，6 个向量块 |
| 0:55–1:35 | AI 智能问答 | 问课程问题 → 展开引用（文件名 + 页码 + 片段）；再问一个资料外的问题，展示**拒答** |
| 1:35–2:20 | 灵玉秘境 | 答 5 题拿灵玉 → 进游戏：点卡 → 三合一 → 布阵 → 出战 → 妖怪被拦 |
| 2:20–2:50 | 学习分析 | 正确率、错题、知识点、AI 复习建议 |
| 2:50–3:00 | 总结 | 技术亮点：RAG 带溯源、两段式拒答、Agent 工具调用、游戏化练习 |

---

## 11. 代码约定

1. **注释用中文**，写"为什么这么做"，不写"这是什么"。
2. **数值只放配置**：`economy_config.py` 是游戏数值唯一来源；`config/settings.py` 是运行时配置唯一来源。
3. **前端零依赖**：不引入 React/Vue/任何 CDN，`game/web` 必须是纯 HTML/CSS/JS。
4. **不给用户看堆栈**：页面层 `except Exception` 后只显示异常类型 + 人话。
5. **判分/奖励永远在 Python 侧**，前端只传"选了哪个选项"。
6. **改行为就补测试**：Python 进 `tests/`，游戏进 `game/web/test_game.js`。

---

## 12. 接手后第一小时建议

1. 跑 `unittest discover`，确认 94 绿。
2. 跑 `node game/web/test_game.js`（先装 jsdom），确认 45 绿。
3. 启动服务，把第 10 节的演示流程走一遍，**亲手玩一局游戏**。
4. 从 TODO 的 **P0** 开始：先做「重开一局」，再做「吞噬升星」。
5. 每改一处，跑一遍两套测试；游戏改动**必须**在 jsdom 里加断言。

有问题先看 `docs/` 下的阶段报告（A–E + 代码检查报告 + 灵玉经济系统实施报告），
里面记录了每个决策的取舍和当时的实测数据。
