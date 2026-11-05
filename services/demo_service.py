"""公开展示：共享只读样例索引，各访客独立学习记录。"""
from __future__ import annotations
import sqlite3
import tempfile
import threading
import time
from collections import deque
from dataclasses import replace
from pathlib import Path
from config.settings import PROJECT_ROOT, Settings
from database import db
_budget_lock = threading.Lock()
_requests: deque[float] = deque()

def prepare_template(settings: Settings) -> Settings:
    """建立独立原创样例，不接触本地已有课程。"""
    root = Path(tempfile.mkdtemp(prefix="coursemate-public-"))
    template = replace(settings, db_path=root / "template.db",
                       chroma_path=root / "chroma", upload_dir=root / "uploads")
    template.ensure_dirs()
    db.init_db(template.db_path)
    cid = db.create_course(template.db_path, "数字图像处理", "原创示例课程 · 可直接问答与练习")
    from services.document_service import handle_upload
    for name in ("数字图像处理_课件.pdf", "课程补充说明.txt"):
        source = PROJECT_ROOT / "samples" / name
        handle_upload(template, cid, name, source.read_bytes())
    return template

def create_session(template: Settings) -> Settings:
    """仅复制关系数据；资料与索引只读共享。"""
    root = Path(tempfile.mkdtemp(prefix="visitor-", dir=template.db_path.parent))
    result = replace(template, db_path=root / "learning.db")
    with sqlite3.connect(template.db_path) as source, sqlite3.connect(result.db_path) as target:
        source.backup(target)
    return result

def reserve_request(*, now: float | None = None) -> None:
    """单进程滚动24小时200次、每分钟10次；失败重试计数，重启重置。"""
    from services.llm_service import LLMError
    moment = time.time() if now is None else now
    with _budget_lock:
        while _requests and _requests[0] <= moment - 86400:
            _requests.popleft()
        if len(_requests) >= 200:
            raise LLMError("展示版今日 AI 体验额度已用完，请稍后再试；小游戏仍可试玩。")
        if sum(t > moment - 60 for t in _requests) >= 10:
            raise LLMError("当前体验人数较多，请一分钟后再试。")
        _requests.append(moment)
