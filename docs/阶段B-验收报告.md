# 阶段 B 验收报告

> 日期：2026-11-03　范围：课程资料上传 → 解析 → 分块 → 向量化 → ChromaDB 持久化

## 1. 新增文件

| 文件 | 作用 |
|---|---|
| `knowledge/parser.py` | PDF（PyMuPDF，保留真实页序）/ DOCX（段落 + 表格）/ TXT（UTF-8→GB18030 自动回退） |
| `knowledge/splitter.py` | 中文友好分块：优先在句末标点下刀，相邻块重叠；**按页切分，不跨页合并** |
| `knowledge/embeddings.py` | 三种后端：`local`（bge-small-zh）/ `openai` / `hash`（测试用），按配置缓存单例 |
| `knowledge/retriever.py` | 按课程一个 collection；写入前先删旧向量，避免重复 chunk |
| `services/document_service.py` | 上传校验、安全落盘、入库编排、状态回写、重建索引 |
| `pages/1_课程知识库.py` | 上传 / 状态 / 块数 / 失败原因 / 重建索引 |
| `ui_common.py` | 页面共用启动逻辑与课程选择器 |
| `scripts/make_sample_docs.py` | 生成自建样例讲义（PDF 5 页 + TXT） |
| `scripts/seed_demo.py` | 把样例灌入真实库，可重复执行（自动去重） |
| `tests/test_knowledge.py` | 19 个用例 |

## 2. 实现要点

1. **页码必须真实**：PDF 用 `enumerate(doc, start=1)` 取物理页序；DOCX/TXT 没有页概念，记为 `None`，
   在引用时显示"文档：xxx"。分块不跨页，保证 chunk 的页码是精确的。
2. **重复上传不产生重复向量**：`add_chunks` 先按 `document_id` 删除旧向量再写入，
   id 形如 `c1_d3_k0002`，天然幂等。
3. **状态一致性**：解析或写入失败时，文档状态置 `failed` 并记录原因，不会留下"看着成功、其实检不到"的假状态。
4. **安全**：文件名先 `Path(name).name` 去掉路径成分，再过滤危险字符；上传前校验扩展名与大小。
5. **可降级**：`EMBEDDING_PROVIDER` 可在 local / openai / hash 之间切换，本地模型跑不动时不必推翻架构。

## 3. 真实运行结果

### 3.1 样例资料（自建，无版权问题）

```
python scripts/make_sample_docs.py
→ samples/数字图像处理_课件.pdf（5 页）
→ samples/课程补充说明.txt
```

回读验证：

```
页数: 5
 page 1 | 首行: 第 1 页 · 课程概览
 page 2 | 首行: 第 2 页 · 直方图与均衡化
 ...
chunks: 5 | 页码分布: [1, 2, 3, 4, 5]
```

### 3.2 入库 + 检索（本地 bge 模型）

```
已入库：数字图像处理_课件.pdf → 5 页 / 5 块
已入库：课程补充说明.txt → 1 页 / 1 块
当前课程向量块总数：6
```

检索质量（余弦相似度）：

| 问题 | Top-1 命中 | 分数 |
|---|---|---|
| PSNR 和 SSIM 分别衡量什么 | 第 5 页（正确） | 0.544 |
| 直方图均衡化的四个步骤是什么 | 第 2 页（正确） | — |
| 今天食堂吃什么（资料外） | 第 1 页（无关） | **0.272** |

这张表同时说明了阶段 C 的关键设计：**必须设相似度阈值**。资料外问题的最高分只有 0.27，
而真实问题都在 0.5 以上，阈值取 0.35~0.4 就能区分"有依据"和"没依据"，
从而避免对大模型编造答案。

### 3.3 界面验证

用 Streamlit `AppTest` 真实执行 `pages/1_课程知识库.py`：

```
exceptions: []
title: ['课程知识库']
metrics: [('资料数量', '2'), ('已入库', '2'), ('向量块总数', '6')]
```

## 4. 测试

```
python -m unittest discover -s tests
Ran 31 tests — OK
```

## 5. 踩到并修掉的问题

| 问题 | 原因 | 处理 |
|---|---|---|
| 8 个用例 teardown 报 `WinError 32` | ChromaDB 在 Windows 上持有文件句柄，临时目录删不掉 | `TemporaryDirectory(ignore_cleanup_errors=True)` + `reset_clients()` 释放句柄 |
| Streamlit 冒烟测试第二个用例失败 | `boot()` 用 `st.cache_resource` 跨用例缓存了指向已删除临时库的 Settings | 用例间 `st.cache_resource.clear()` |
| 模型维度接口 FutureWarning | sentence-transformers 6.x 把 `get_sentence_embedding_dimension` 改名 | 新旧方法名兼容 |

## 6. 已知限制

- 扫描版 PDF 无文字层时不解析，直接提示用户（OCR 不在范围）。
- 更换 Embedding 模型后需对已有文档「重建索引」，否则维度不一致。
- 尚未做批量删除课程（任务书默认不提供，避免误删文件与向量）。

## 7. 下一步（阶段 C）

1. `knowledge/retriever.py` 的检索结果接入 `qa_service`；
2. 设计回答 Prompt：只依据片段作答、标注 `[1][2]`、无依据时明确说明；
3. **相似度阈值拒答**（阈值 0.35，用本次实测数据定标）；
4. 页面 `2_AI智能问答.py`：聊天区 + 可折叠来源面板（文件名 / 页码 / 片段）；
5. 用两类问题验证：资料内（T05）与资料外（T06）。
