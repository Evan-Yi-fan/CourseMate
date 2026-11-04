"""课程与资料删除：先暂存文件，可回退地清理向量和数据库，再清理暂存目录。"""
from __future__ import annotations

import logging
import re
import shutil
import stat
import tempfile
from pathlib import Path

from config.settings import Settings
from database import db
from knowledge.retriever import CourseIndex

log = logging.getLogger(__name__)


class DeletionError(RuntimeError):
    pass


def _no_links(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    info = path.lstat()
    if path.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise DeletionError("上传目录中存在链接，请先检查文件位置后重试。")
    if path.is_dir():
        for child in path.iterdir():
            _no_links(child)


def _course_dir(settings: Settings, course_id: int) -> Path:
    root = Path(settings.upload_dir).resolve()
    directory = root / f"course_{int(course_id)}"
    _no_links(directory)
    if directory.resolve().parent != root or directory.resolve() == root:
        raise DeletionError("上传目录位置异常，已停止删除。")
    return directory


def _document_files(settings: Settings, doc: dict) -> list[Path]:
    directory = _course_dir(settings, int(doc["course_id"]))
    stored = Path(doc["file_path"])
    if stored.resolve().parent != directory.resolve():
        raise DeletionError("资料文件不在本课程的上传目录，已停止删除。")
    _no_links(stored)
    paths = [stored] if stored.exists() else []
    # 旧版本同名覆盖曾留下旧副本，只清理精确匹配的本课程文件，并保护其他记录。
    others = {Path(d["file_path"]).resolve() for d in db.list_documents(settings.db_path, doc["course_id"])
              if d["id"] != doc["id"]}
    pattern = re.compile(r"[0-9a-f]{8}_" + re.escape(doc["filename"]) + r"\Z")
    if directory.exists():
        for file in directory.iterdir():
            if file.is_file() and pattern.fullmatch(file.name) and file.resolve() not in others and file not in paths:
                paths.append(file)
    return paths


class _StagedFiles:
    def __init__(self, settings: Settings, paths: list[Path]):
        self.root = Path(settings.upload_dir).resolve() / ".deletions"
        self.root.mkdir(parents=True, exist_ok=True)
        _no_links(self.root)
        self.folder = Path(tempfile.mkdtemp(prefix="delete_", dir=self.root))
        self.moves: list[tuple[Path, Path]] = []
        try:
            for index, source in enumerate(paths):
                target = self.folder / f"{index}_{source.name}"
                if not target.resolve().is_relative_to(self.folder.resolve()):
                    raise DeletionError("暂存目录位置异常。")
                source.replace(target)
                self.moves.append((source, target))
        except Exception:
            self.rollback()
            raise

    def rollback(self) -> None:
        for original, staged in reversed(self.moves):
            if staged.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                staged.replace(original)
        self.moves.clear()
        self.purge()

    def purge(self) -> None:
        # Windows递归删除前验证最终绝对目标严格位于本次暂存目录下。
        final = self.folder.resolve()
        if final == self.root.resolve() or not final.is_relative_to(self.root.resolve()):
            raise DeletionError("清理目录位置异常。")
        _no_links(final)
        if final.exists():
            shutil.rmtree(final)


def _delete(settings: Settings, course_id: int, paths: list[Path], document_id: int | None) -> dict:
    index = CourseIndex(settings, course_id)
    try:
        backup = index.backup(document_id)
        staged = _StagedFiles(settings, paths)
    except Exception as exc:
        raise DeletionError("暂时无法准备删除，资料与记录未删除。请关闭占用文件后重试。") from exc
    try:
        if document_id is None:
            index.drop(strict=True)
            deleted = db.delete_course(settings.db_path, course_id)
        else:
            index.delete_document(document_id, strict=True)
            deleted = db.delete_document(settings.db_path, document_id, course_id)
        if not deleted:
            raise DeletionError("记录不存在或已被删除。")
    except Exception as exc:
        errors = []
        try:
            index.restore(backup)
        except Exception as rollback_error:
            errors.append(type(rollback_error).__name__)
        try:
            staged.rollback()
        except Exception as rollback_error:
            errors.append(type(rollback_error).__name__)
        if errors:
            log.error("删除回退未完全完成: %s", ",".join(errors))
            raise DeletionError("删除未完成，请保留现有文件并检查或重建课程索引。") from exc
        raise DeletionError("删除未完成，文件和索引已恢复，请重试。") from exc
    warnings = []
    try:
        staged.purge()
    except Exception:
        log.warning("记录已删除，文件暂存目录待清理: %s", staged.folder)
        warnings.append("记录与索引已删除，部分本地文件暂存待清理，请关闭文件占用后检查上传目录。")
    return {"warnings": warnings}


def delete_document(settings: Settings, course_id: int, document_id: int) -> dict:
    doc = db.get_document(settings.db_path, document_id)
    if not doc or int(doc["course_id"]) != int(course_id):
        raise DeletionError("当前课程中不存在这份资料。")
    paths = _document_files(settings, doc)
    result = _delete(settings, course_id, paths, document_id)
    return {"filename": doc["filename"], **result}


def delete_course(settings: Settings, course_id: int) -> dict:
    course = db.get_course(settings.db_path, course_id)
    if not course:
        raise DeletionError("这门课程不存在或已被删除。")
    directory = _course_dir(settings, course_id)
    # 所有记录都先检查位置，避免错误配置导致删除外部文件。
    for doc in db.list_documents(settings.db_path, course_id):
        _document_files(settings, doc)
    result = _delete(settings, course_id, [directory] if directory.exists() else [], None)
    return {"course_name": course["name"], **result}
