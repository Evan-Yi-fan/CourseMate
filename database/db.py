"""SQLite 访问层。

刻意只用标准库 sqlite3：本项目的关系模型很小（5 张表），
引入 ORM 只会增加依赖和调试成本，而任务书允许 sqlite3 作为选项。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    description TEXT    DEFAULT '',
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    filename    TEXT    NOT NULL,
    file_path   TEXT    NOT NULL,
    file_type   TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending',   -- pending|ready|failed
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error       TEXT    DEFAULT '',
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id       INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    question        TEXT    NOT NULL,
    question_type   TEXT    NOT NULL DEFAULT 'single', -- single|judge
    options         TEXT    NOT NULL DEFAULT '[]',     -- JSON 字符串
    answer          TEXT    NOT NULL,
    explanation     TEXT    DEFAULT '',
    knowledge_point TEXT    DEFAULT '',
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    user_answer TEXT    NOT NULL,
    is_correct  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id  INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    role       TEXT    NOT NULL,                       -- user|assistant
    content    TEXT    NOT NULL,
    sources    TEXT    DEFAULT '[]',                   -- JSON 字符串
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_course   ON documents(course_id);
CREATE INDEX IF NOT EXISTS idx_questions_course   ON questions(course_id);
CREATE INDEX IF NOT EXISTS idx_attempts_question  ON quiz_attempts(question_id);
CREATE INDEX IF NOT EXISTS idx_messages_course    ON chat_messages(course_id);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")   # sqlite 默认关闭，必须显式打开
    conn.execute("PRAGMA journal_mode = WAL")  # 允许读写并发，避免 Streamlit 重跑时锁库
    return conn


@contextmanager
def session(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    with session(db_path) as conn:
        conn.executescript(SCHEMA)
    log.info("数据库已初始化: %s", db_path)


def table_counts(db_path: Path) -> dict[str, int]:
    """首页/自检用：确认库能连、表存在、数据量可读。"""
    tables = ["courses", "documents", "questions", "quiz_attempts", "chat_messages"]
    out: dict[str, int] = {}
    with session(db_path) as conn:
        for t in tables:
            try:
                out[t] = conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
            except sqlite3.Error:
                out[t] = -1
    return out


# ----------------------------------------------------------------------
# 课程（F01）
# ----------------------------------------------------------------------

def create_course(db_path: Path, name: str, description: str = "") -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("课程名称不能为空")
    with session(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO courses (name, description, created_at) VALUES (?, ?, ?)",
            (name[:80], (description or "").strip()[:500], now()),
        )
        return int(cur.lastrowid)


def list_courses(db_path: Path) -> list[dict[str, Any]]:
    with session(db_path) as conn:
        rows = conn.execute(
            """SELECT c.*,
                      (SELECT COUNT(*) FROM documents d WHERE d.course_id = c.id) AS doc_count,
                      (SELECT COUNT(*) FROM questions q WHERE q.course_id = c.id) AS question_count
               FROM courses c ORDER BY c.id DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_course(db_path: Path, course_id: int) -> dict[str, Any] | None:
    with session(db_path) as conn:
        row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    return dict(row) if row else None


# ----------------------------------------------------------------------
# 文档（F02–F04 的状态记录）
# ----------------------------------------------------------------------

def create_document(db_path: Path, course_id: int, filename: str,
                    file_path: str, file_type: str) -> int:
    with session(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO documents
               (course_id, filename, file_path, file_type, status, chunk_count, created_at)
               VALUES (?, ?, ?, ?, 'pending', 0, ?)""",
            (course_id, filename[:200], str(file_path), file_type, now()),
        )
        return int(cur.lastrowid)


def find_document_by_name(db_path: Path, course_id: int, filename: str) -> dict[str, Any] | None:
    """同名文档查找：用于"重复上传同一份资料"时替换而不是新增。"""
    with session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE course_id = ? AND filename = ? ORDER BY id DESC LIMIT 1",
            (course_id, filename),
        ).fetchone()
    return dict(row) if row else None


def update_document_file(db_path: Path, document_id: int, filename: str,
                         file_path: str, file_type: str) -> None:
    with session(db_path) as conn:
        conn.execute(
            "UPDATE documents SET filename = ?, file_path = ?, file_type = ? WHERE id = ?",
            (filename, str(file_path), file_type, document_id),
        )


def set_document_status(db_path: Path, document_id: int, status: str,
                        chunk_count: int = 0, error: str = "") -> None:
    if status not in {"pending", "ready", "failed"}:
        raise ValueError(f"非法状态: {status}")
    with session(db_path) as conn:
        conn.execute(
            "UPDATE documents SET status = ?, chunk_count = ?, error = ? WHERE id = ?",
            (status, int(chunk_count), (error or "")[:500], document_id),
        )


def list_documents(db_path: Path, course_id: int) -> list[dict[str, Any]]:
    with session(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE course_id = ? ORDER BY id DESC", (course_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_document(db_path: Path, document_id: int) -> dict[str, Any] | None:
    with session(db_path) as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    return dict(row) if row else None


# ----------------------------------------------------------------------
# 问答历史（P1，但落库成本很低，问答时顺手写入）
# ----------------------------------------------------------------------

def add_chat_message(db_path: Path, course_id: int, role: str, content: str,
                     sources: list[dict[str, Any]] | None = None) -> int:
    if role not in {"user", "assistant"}:
        raise ValueError(f"非法角色: {role}")
    with session(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO chat_messages (course_id, role, content, sources, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (course_id, role, content, json.dumps(sources or [], ensure_ascii=False), now()),
        )
        return int(cur.lastrowid)


def list_chat_messages(db_path: Path, course_id: int, limit: int = 50) -> list[dict[str, Any]]:
    with session(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE course_id = ? ORDER BY id DESC LIMIT ?",
            (course_id, int(limit)),
        ).fetchall()
    out = []
    for r in reversed(rows):           # 按时间正序返回，便于直接渲染
        d = dict(r)
        try:
            d["sources"] = json.loads(d.get("sources") or "[]")
        except json.JSONDecodeError:
            d["sources"] = []
        out.append(d)
    return out


# ----------------------------------------------------------------------
# 试题与答题记录（F08–F10）
# ----------------------------------------------------------------------

def add_question(db_path: Path, course_id: int, *, question: str, question_type: str,
                 options: list[dict[str, str]], answer: str, explanation: str = "",
                 knowledge_point: str = "") -> int:
    with session(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO questions
               (course_id, question, question_type, options, answer, explanation,
                knowledge_point, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (course_id, question, question_type,
             json.dumps(options, ensure_ascii=False), answer,
             explanation, knowledge_point, now()),
        )
        return int(cur.lastrowid)


def get_question(db_path: Path, question_id: int) -> dict[str, Any] | None:
    with session(db_path) as conn:
        row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["options"] = json.loads(d["options"] or "[]")
    return d


def list_questions(db_path: Path, course_id: int, limit: int = 50) -> list[dict[str, Any]]:
    with session(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM questions WHERE course_id = ? ORDER BY id DESC LIMIT ?",
            (course_id, int(limit)),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["options"] = json.loads(d["options"] or "[]")
        out.append(d)
    return out


def add_attempt(db_path: Path, question_id: int, user_answer: str, is_correct: bool) -> int:
    with session(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO quiz_attempts (question_id, user_answer, is_correct, created_at)"
            " VALUES (?, ?, ?, ?)",
            (question_id, user_answer, 1 if is_correct else 0, now()),
        )
        return int(cur.lastrowid)


def list_attempts(db_path: Path, course_id: int, *, only_wrong: bool = False,
                  limit: int = 100) -> list[dict[str, Any]]:
    """答题明细（含题目与解析），用于错题列表。按时间倒序。"""
    sql = """SELECT a.id, a.question_id, a.user_answer, a.is_correct, a.created_at,
                    q.question, q.question_type, q.options, q.answer,
                    q.explanation, q.knowledge_point
             FROM quiz_attempts a JOIN questions q ON q.id = a.question_id
             WHERE q.course_id = ?"""
    if only_wrong:
        sql += " AND a.is_correct = 0"
    sql += " ORDER BY a.id DESC LIMIT ?"

    with session(db_path) as conn:
        rows = conn.execute(sql, (course_id, int(limit))).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        d["options"] = json.loads(d.pop("options") or "[]")
        d["is_correct"] = bool(d["is_correct"])
        out.append(d)
    return out


def attempt_stats(db_path: Path, course_id: int) -> dict[str, Any]:
    """按课程统计答题情况，并给出知识点维度的错题分布。"""
    with session(db_path) as conn:
        rows = conn.execute(
            """SELECT a.is_correct, a.user_answer, q.knowledge_point, q.question, q.answer
               FROM quiz_attempts a JOIN questions q ON q.id = a.question_id
               WHERE q.course_id = ?""", (course_id,),
        ).fetchall()

    total = len(rows)
    correct = sum(1 for r in rows if r["is_correct"])
    by_kp: dict[str, dict[str, int]] = {}
    for r in rows:
        kp = (r["knowledge_point"] or "未标注").strip() or "未标注"
        slot = by_kp.setdefault(kp, {"total": 0, "wrong": 0})
        slot["total"] += 1
        if not r["is_correct"]:
            slot["wrong"] += 1

    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 3) if total else 0.0,
        "by_knowledge": [
            {"knowledge_point": k, "total": v["total"], "wrong": v["wrong"]}
            for k, v in sorted(by_kp.items(), key=lambda kv: -kv[1]["wrong"])
        ],
    }


def delete_course(db_path: Path, course_id: int) -> bool:
    """外键级联清理课程的资料、题目、作答和聊天记录。"""
    with session(db_path) as conn:
        return conn.execute("DELETE FROM courses WHERE id = ?", (int(course_id),)).rowcount == 1


def delete_document(db_path: Path, document_id: int, course_id: int) -> bool:
    with session(db_path) as conn:
        return conn.execute("DELETE FROM documents WHERE id = ? AND course_id = ?",
                            (int(document_id), int(course_id))).rowcount == 1
