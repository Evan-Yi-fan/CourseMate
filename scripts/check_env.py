"""阶段 A 自检：环境、依赖、目录、数据库、向量库、大模型连通性。

用法：
    .venv\\Scripts\\python.exe scripts\\check_env.py
    .venv\\Scripts\\python.exe scripts\\check_env.py --skip-llm   # 还没有 Key 时

退出码：0 全部通过；1 存在阻塞项（必需依赖/配置缺失）；2 仅有告警。
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

# 允许直接 python scripts/check_env.py 运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ConfigError, Settings, mask_secret  # noqa: E402
from database import db  # noqa: E402

OK, WARN, FAIL = "OK", "WARN", "FAIL"
MARK = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]"}

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"{MARK[status]} {name}" + (f"  —  {detail}" if detail else ""))


def check_python() -> None:
    v = sys.version_info
    detail = f"{v.major}.{v.minor}.{v.micro} @ {sys.executable}"
    if (v.major, v.minor) == (3, 11):
        record(OK, "Python 版本", detail)
    elif (v.major, v.minor) in {(3, 10), (3, 12)}:
        record(WARN, "Python 版本", detail + "（任务书建议 3.11，此版本通常兼容）")
    else:
        record(FAIL, "Python 版本", detail + "（建议 3.11）")

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    record(OK if in_venv else WARN, "虚拟环境", sys.prefix if in_venv else "未在 venv 中运行")


def check_packages() -> None:
    required = {
        "streamlit": "Streamlit 界面",
        "openai": "大模型 SDK",
        "dotenv": "环境变量加载",
        "pymupdf": "PDF 解析",
        "docx": "DOCX 解析",
        "chromadb": "向量库",
    }
    optional = {
        "sentence_transformers": "本地中文 Embedding（缺失时需切换 EMBEDDING_PROVIDER）",
        "plotly": "图表（可选）",
        "pandas": "数据表（Streamlit 依赖，通常已具备）",
    }
    for mod, label in required.items():
        try:
            m = importlib.import_module(mod)
            ver = getattr(m, "__version__", "")
            record(OK, f"依赖 {mod}", f"{label} {ver}".strip())
        except Exception as exc:
            record(FAIL, f"依赖 {mod}", f"{label} 导入失败：{exc}")

    for mod, label in optional.items():
        if importlib.util.find_spec(mod) is None:
            record(WARN, f"可选依赖 {mod}", f"{label} 未安装")
        else:
            try:
                m = importlib.import_module(mod)
                record(OK, f"可选依赖 {mod}", f"{label} {getattr(m, '__version__', '')}".strip())
            except Exception as exc:
                record(WARN, f"可选依赖 {mod}", f"{label} 导入失败：{exc}")


def check_settings(skip_llm: bool) -> Settings | None:
    try:
        s = Settings.load()
    except ConfigError as exc:
        record(FAIL, "配置加载", str(exc))
        return None
    except Exception as exc:
        record(FAIL, "配置加载", f"{type(exc).__name__}: {exc}")
        return None

    env_file = Path(__file__).resolve().parent.parent / ".env"
    record(OK if env_file.exists() else WARN, "配置文件",
           str(env_file) if env_file.exists() else "未找到 .env（可先用 .env.example 复制）")
    record(OK, "配置加载", f"chunk={s.chunk_size}/{s.chunk_overlap}, top_k={s.retrieval_top_k}")

    if s.llm_ready:
        record(OK, "LLM 配置",
               f"provider={s.llm_provider} model={s.llm_model} key={mask_secret(s.llm_api_key)}")
    else:
        record(FAIL if not skip_llm else WARN, "LLM 配置",
               "缺少 " + "、".join(s.llm_missing()))
    return s


def check_dirs_and_db(s: Settings) -> None:
    try:
        s.ensure_dirs()
        for p in (s.db_path.parent, s.chroma_path, s.upload_dir):
            record(OK if p.exists() else FAIL, "目录", str(p))
    except Exception as exc:
        record(FAIL, "目录创建", f"{type(exc).__name__}: {exc}")
        return

    try:
        db.init_db(s.db_path)
        counts = db.table_counts(s.db_path)
        wired = [k for k, v in counts.items() if v >= 0]
        record(OK if len(wired) == len(counts) else FAIL, "SQLite",
               f"{s.db_path} | 表 {len(wired)}/5 可读 | " +
               ", ".join(f"{k}={v}" for k, v in counts.items()))
    except Exception as exc:
        record(FAIL, "SQLite", f"{type(exc).__name__}: {exc}")


def check_chroma(s: Settings) -> None:
    """用显式向量探测写入+检索，避免触发 chromadb 默认 ONNX 模型下载，
    也避免用临时目录（Windows 上子进程仍持有文件会导致清理失败）。"""
    try:
        import chromadb
    except Exception as exc:
        record(FAIL, "ChromaDB", f"导入失败：{exc}")
        return

    name = "check_probe"
    try:
        client = chromadb.PersistentClient(path=str(s.chroma_path))
        try:
            client.delete_collection(name)
        except Exception:
            pass  # 不存在属正常
        col = client.get_or_create_collection(name)
        vec = [0.1, 0.2, 0.3, 0.4]
        col.add(ids=["probe-1"], documents=["连通性测试文本"],
                metadatas=[{"course_id": 0, "page": 1}], embeddings=[vec])
        got = col.query(query_embeddings=[vec], n_results=1)
        hit = bool(got["ids"] and got["ids"][0])
        client.delete_collection(name)   # 探测完立即清理，不留垃圾 collection
        record(OK if hit else FAIL, "ChromaDB",
               f"版本 {chromadb.__version__}，写入+检索{'成功' if hit else '失败'}（已清理探测数据）")
    except Exception as exc:
        record(FAIL, "ChromaDB", f"{type(exc).__name__}: {exc}")


def check_llm(s: Settings) -> None:
    if not s.llm_ready:
        record(WARN, "大模型连通性", "未配置，已跳过（--skip-llm 时属预期）")
        return
    from services.llm_service import LLMService

    r = LLMService(s).ping()
    if r["ok"]:
        record(OK, "大模型连通性",
               f"{r['model']} | {r['latency_ms']}ms | 回复「{r['reply']}」")
    else:
        status = FAIL if r.get("kind") != "not_configured" else WARN
        record(status, "大模型连通性", r["message"])


def main() -> int:
    ap = argparse.ArgumentParser(description="CourseMate 环境自检")
    ap.add_argument("--skip-llm", action="store_true", help="跳过真实模型调用（无 Key 时）")
    args = ap.parse_args()

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    print("=" * 66)
    print(" CourseMate 环境自检")
    print("=" * 66)

    check_python()
    check_packages()
    s = check_settings(args.skip_llm)
    if s is not None:
        check_dirs_and_db(s)
        check_chroma(s)
        if not args.skip_llm:
            check_llm(s)
        else:
            record(WARN, "大模型连通性", "按 --skip-llm 跳过")

    fails = [r for r in results if r[0] == FAIL]
    warns = [r for r in results if r[0] == WARN]
    print("-" * 66)
    print(f" 合计 {len(results)} 项：OK {len(results) - len(fails) - len(warns)} / "
          f"WARN {len(warns)} / FAIL {len(fails)}")
    if fails:
        print(" 阻塞项：")
        for _, name, detail in fails:
            print(f"   - {name}: {detail}")
        return 1
    if warns:
        print(" 以上 WARN 不阻塞启动，但建议处理，尤其是 LLM 配置。")
        return 0
    print(" 全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
