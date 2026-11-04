"""文本分块。

中文没有空格分词，按固定字数硬切会把句子切断，检索时语义就散了。
这里做两件事：
1. 优先在句末标点处下刀；
2. 相邻块保留重叠，避免答案正好跨在两块之间被割裂。

重要的工程选择：**按页分块**，不跨页合并。这样每个 chunk 的页码是精确的，
引用时能直接告诉用户"第 12 页"，而不会出现"第 12–13 页"这种含糊来源。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from knowledge.parser import PageText

log = logging.getLogger(__name__)

# 句末标点 + 换行，按"刀口"优先级排列
_BOUNDARY = "。！？；!?;\n"


@dataclass
class Chunk:
    text: str
    page: int | None
    chunk_index: int


def _split_one(text: str, size: int, overlap: int) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    out: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            window = text[start:end]
            # 只在后半段找句末标点，避免切出很短的碎块
            best = -1
            for ch in _BOUNDARY:
                pos = window.rfind(ch)
                if pos > best:
                    best = pos
            if best >= int(size * 0.6):
                end = start + best + 1
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return out


def split_pages(pages: list[PageText], chunk_size: int = 600,
                overlap: int = 100) -> list[Chunk]:
    """把每个页面的文本切块，chunk_index 在全文档内连续编号。"""
    if overlap >= chunk_size:
        raise ValueError("overlap 必须小于 chunk_size")

    chunks: list[Chunk] = []
    idx = 0
    for page in pages:
        for piece in _split_one(page.text, chunk_size, overlap):
            chunks.append(Chunk(text=piece, page=page.page, chunk_index=idx))
            idx += 1

    if not chunks:
        # 理论上 parse_file 已挡住空文本，这里是双保险
        raise ValueError("分块结果为空，文档可能没有有效文字。")

    log.info("分块完成：%d 块（size=%d, overlap=%d）", len(chunks), chunk_size, overlap)
    return chunks
