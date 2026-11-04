from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config.settings import Settings
from database import db
from knowledge.embeddings import HashEmbedder
from knowledge.retriever import CourseIndex, RetrievalError, reset_clients
from services import deletion_service as svc
from services.document_service import handle_upload


class TestDeletion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.settings = Settings(db_path=self.root/'t.db', chroma_path=self.root/'chroma',
                                 upload_dir=self.root/'uploads', embedding_provider='hash',
                                 embedding_model='hash-test', embedding_dim=256)
        self.settings.ensure_dirs()
        db.init_db(self.settings.db_path)
        self.a = db.create_course(self.settings.db_path, '待删除课程')
        self.b = db.create_course(self.settings.db_path, '保留课程')
        self.first = handle_upload(self.settings, self.a, 'first.txt', '误导入的材料，准备删除。'.encode())['document_id']
        self.second = handle_upload(self.settings, self.a, 'other_first.txt', '应继续保留的资料。'.encode())['document_id']
        self.other = handle_upload(self.settings, self.b, 'keep.txt', '另一门课程的资料。'.encode())['document_id']
        self.first_path = Path(db.get_document(self.settings.db_path, self.first)['file_path'])
        self.qa = db.add_question(self.settings.db_path, self.a, question='测试题', question_type='single', options=[], answer='A')
        db.add_attempt(self.settings.db_path, self.qa, 'A', True)
        db.add_chat_message(self.settings.db_path, self.a, 'user', '历史提问')

    def tearDown(self):
        reset_clients()
        self.tmp.cleanup()

    def index(self, cid=None):
        return CourseIndex(self.settings, self.a if cid is None else cid)

    def assert_preserved(self):
        self.assertIsNotNone(db.get_document(self.settings.db_path, self.first))
        self.assertTrue(self.first_path.exists())
        self.assertEqual(self.index().count(), 2)

    def test_document_removes_files_record_and_retrieval_only(self):
        result = svc.delete_document(self.settings, self.a, self.first)
        self.assertEqual(result['warnings'], [])
        self.assertIsNone(db.get_document(self.settings.db_path, self.first))
        self.assertFalse(self.first_path.exists())
        self.assertEqual(self.index().count(), 1)
        hits = self.index().search('误导入', HashEmbedder(256), 5)
        self.assertTrue(all(h.document_id != self.first for h in hits))
        self.assertIsNotNone(db.get_question(self.settings.db_path, self.qa))
        self.assertEqual(len(db.list_attempts(self.settings.db_path, self.a)), 1)
        self.assertEqual(self.index(self.b).count(), 1)

    def test_document_cannot_be_deleted_from_wrong_course(self):
        with self.assertRaises(svc.DeletionError):
            svc.delete_document(self.settings, self.b, self.first)
        self.assert_preserved()

    def test_missing_file_can_still_remove_record_and_index(self):
        self.first_path.unlink()
        svc.delete_document(self.settings, self.a, self.first)
        self.assertIsNone(db.get_document(self.settings.db_path, self.first))
        self.assertEqual(self.index().count(), 1)

    def test_document_cleans_old_same_name_copies_without_suffix_collision(self):
        handle_upload(self.settings, self.a, 'first.txt', '更新后的资料'.encode())
        current_path = Path(db.get_document(self.settings.db_path, self.first)['file_path'])
        protected = Path(db.get_document(self.settings.db_path, self.second)['file_path'])
        svc.delete_document(self.settings, self.a, self.first)
        self.assertFalse(self.first_path.exists())
        self.assertFalse(current_path.exists())
        self.assertTrue(protected.exists())

    def test_vector_failure_restores_document_file_and_record(self):
        with patch.object(CourseIndex, 'delete_document', side_effect=RetrievalError('unavailable')):
            with self.assertRaises(svc.DeletionError):
                svc.delete_document(self.settings, self.a, self.first)
        self.assert_preserved()

    def test_sql_failure_restores_removed_vectors_and_file(self):
        with patch.object(db, 'delete_document', side_effect=RuntimeError('locked')):
            with self.assertRaises(svc.DeletionError):
                svc.delete_document(self.settings, self.a, self.first)
        self.assert_preserved()

    def test_file_staging_failure_does_not_delete_records_or_vectors(self):
        with patch.object(Path, 'replace', side_effect=PermissionError('file is open')):
            with self.assertRaises(svc.DeletionError):
                svc.delete_document(self.settings, self.a, self.first)
        self.assert_preserved()

    def test_external_file_path_is_never_deleted(self):
        outside = self.root / 'important.txt'
        outside.write_text('keep', encoding='utf-8')
        db.update_document_file(self.settings.db_path, self.first, 'first.txt', str(outside), 'txt')
        with self.assertRaises(svc.DeletionError):
            svc.delete_document(self.settings, self.a, self.first)
        self.assertTrue(outside.exists())
        self.assertIsNotNone(db.get_document(self.settings.db_path, self.first))
        self.assertEqual(self.index().count(), 2)

    def test_course_removes_every_related_record_and_upload_directory(self):
        folder = self.first_path.parent
        (folder / 'leftover.txt').write_text('old copy', encoding='utf-8')
        svc.delete_course(self.settings, self.a)
        self.assertIsNone(db.get_course(self.settings.db_path, self.a))
        self.assertEqual(db.list_documents(self.settings.db_path, self.a), [])
        self.assertIsNone(db.get_question(self.settings.db_path, self.qa))
        self.assertEqual(db.list_attempts(self.settings.db_path, self.a), [])
        with db.session(self.settings.db_path) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM chat_messages WHERE course_id=?', (self.a,)).fetchone()[0], 0)
        self.assertIsNone(self.index().backup())
        self.assertFalse(folder.exists())
        self.assertIsNotNone(db.get_course(self.settings.db_path, self.b))
        self.assertEqual(self.index(self.b).count(), 1)

    def test_course_index_failure_restores_directory(self):
        with patch.object(CourseIndex, 'drop', side_effect=RetrievalError('unavailable')):
            with self.assertRaises(svc.DeletionError):
                svc.delete_course(self.settings, self.a)
        self.assert_preserved()
        self.assertIsNotNone(db.get_question(self.settings.db_path, self.qa))

    def test_course_sql_failure_restores_collection(self):
        with patch.object(db, 'delete_course', side_effect=RuntimeError('locked')):
            with self.assertRaises(svc.DeletionError):
                svc.delete_course(self.settings, self.a)
        self.assert_preserved()

    def test_empty_course_can_be_deleted_without_existing_index(self):
        empty = db.create_course(self.settings.db_path, '空课程')
        self.assertEqual(svc.delete_course(self.settings, empty)['warnings'], [])
        self.assertIsNone(db.get_course(self.settings.db_path, empty))

    def test_failed_import_can_be_deleted(self):
        with self.assertRaises(Exception):
            handle_upload(self.settings, self.a, 'bad.pdf', b'invalid')
        failed = next(d for d in db.list_documents(self.settings.db_path, self.a) if d['status']=='failed')
        file = Path(failed['file_path'])
        svc.delete_document(self.settings, self.a, failed['id'])
        self.assertIsNone(db.get_document(self.settings.db_path, failed['id']))
        self.assertFalse(file.exists())

    def test_physical_cleanup_failure_is_reported_without_false_rollback(self):
        with patch.object(svc._StagedFiles, 'purge', side_effect=PermissionError('busy')):
            result = svc.delete_document(self.settings, self.a, self.first)
        self.assertTrue(result['warnings'])
        self.assertIsNone(db.get_document(self.settings.db_path, self.first))
        self.assertEqual(self.index().count(), 1)
