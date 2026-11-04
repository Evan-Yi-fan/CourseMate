"""把样例资料灌进项目真实数据库，方便直接演示。

会做去重：同名资料已存在且状态为 ready 的不会重复入库。

用法：python scripts/seed_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import Settings            # noqa: E402
from database import db                          # noqa: E402
from knowledge.retriever import CourseIndex      # noqa: E402
from services import document_service as docsvc  # noqa: E402

COURSE_NAME = "数字图像处理"
FILES = ["数字图像处理_课件.pdf", "课程补充说明.txt"]


def main() -> int:
    settings = Settings.load()
    settings.ensure_dirs()
    db.init_db(settings.db_path)

    course = next((c for c in db.list_courses(settings.db_path) if c["name"] == COURSE_NAME), None)
    if course:
        course_id = int(course["id"])
        print(f"复用已有课程：{COURSE_NAME} (#{course_id})")
    else:
        course_id = db.create_course(settings.db_path, COURSE_NAME, "课件、讲义与复习资料")
        print(f"已创建课程：{COURSE_NAME} (#{course_id})")

    existing = {d["filename"] for d in db.list_documents(settings.db_path, course_id)
                if d["status"] == "ready"}

    for name in FILES:
        path = ROOT / "samples" / name
        if not path.exists():
            print(f"跳过（文件不存在）：{name}")
            continue
        if name in existing:
            print(f"跳过（已入库）：{name}")
            continue
        result = docsvc.handle_upload(settings, course_id, name, path.read_bytes())
        print(f"已入库：{name} → {result['pages']} 页 / {result['chunks']} 块")

    index = CourseIndex(settings, course_id)
    print(f"当前课程向量块总数：{index.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
