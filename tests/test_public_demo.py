"""公开入口、访问控制、会话隔离及服务端额度测试。"""
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch, MagicMock
import streamlit as st
from streamlit.testing.v1 import AppTest
from config.settings import Settings, ConfigError
from config import model_settings
from database import db
from services import demo_service as demo
from services.llm_service import LLMService, LLMError

ROOT = Path(__file__).resolve().parent.parent

class PublicDemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self.settings = Settings(public_demo=True, db_path=root/'template.db',
            chroma_path=root/'chroma', upload_dir=root/'uploads',
            embedding_provider='hash', embedding_model='public-hash',
            llm_api_key='synthetic-demo-test', llm_model='test', llm_base_url='https://example.test/v1')
        self.settings.ensure_dirs()
        db.init_db(self.settings.db_path)
        self.cid = db.create_course(self.settings.db_path, '样例课程')
        st.cache_resource.clear()
        with demo._budget_lock:
            demo._requests.clear()
    def tearDown(self):
        st.cache_resource.clear()
        self.tmp.cleanup()
    def test_visitors_do_not_share_learning_database(self):
        first, second = demo.create_session(self.settings), demo.create_session(self.settings)
        self.assertNotEqual(first.db_path, second.db_path)
        db.create_course(first.db_path, 'first visitor only')
        self.assertEqual(len(db.list_courses(second.db_path)), 1)
        self.assertEqual(len(db.list_courses(self.settings.db_path)), 1)
        self.assertEqual(first.chroma_path, second.chroma_path)
    def test_public_model_config_cannot_be_saved_or_loaded(self):
        local = replace(self.settings, public_demo=False)
        model_settings.save(local)
        public = replace(self.settings, llm_model='environment-only')
        self.assertEqual(model_settings.apply(public).llm_model, 'environment-only')
        with self.assertRaises(ConfigError):
            model_settings.save(public)
    def test_rate_and_daily_budgets_expire(self):
        for _ in range(10): demo.reserve_request(now=1000)
        with self.assertRaises(LLMError): demo.reserve_request(now=1000)
        demo.reserve_request(now=1061)
        demo._requests.clear()
        for i in range(200): demo.reserve_request(now=2000 + i*61)
        with self.assertRaises(LLMError): demo.reserve_request(now=2000 + 200*61)
        demo.reserve_request(now=2000 + 86401)
    def test_llm_limit_prevents_http_and_caps_output(self):
        svc = LLMService(self.settings)
        svc._client = MagicMock()
        resp = MagicMock()
        resp.choices[0].message.content = 'test'
        svc._client.chat.completions.create.return_value = resp
        svc.chat([{'role':'user','content':'hello'}], max_tokens=9000)
        self.assertEqual(svc._client.chat.completions.create.call_args.kwargs['max_tokens'], 3000)
        svc._client.reset_mock()
        with patch.object(demo, 'reserve_request', side_effect=LLMError('limit')):
            with self.assertRaises(LLMError): svc.chat([{'role':'user','content':'hello'}])
        svc._client.chat.completions.create.assert_not_called()
    def test_public_entry_and_direct_settings_access(self):
        with patch.dict(os.environ, {'COURSEMATE_PUBLIC_DEMO':'true'}), patch('services.demo_service.prepare_template', return_value=self.settings):
            at = AppTest.from_file(str(ROOT/'streamlit_demo.py'), default_timeout=30).run()
            self.assertEqual(list(at.exception), [])
            self.assertTrue(next(b for b in at.button if b.label=='创建课程').disabled)
            self.assertFalse(any('删除课程' in b.label for b in at.button))
            self.assertEqual(len(at.json), 0)
            at.switch_page('pages/6_模型设置.py').run()
            self.assertEqual(list(at.exception), [])
            self.assertEqual(len(at.text_input), 0)
            at.switch_page('pages/1_课程知识库.py').run()
            self.assertEqual(list(at.exception), [])
            self.assertEqual(len(at.get('file_uploader')), 0)
            self.assertFalse(any(b.label in ('重建索引','确认删除资料') for b in at.button))

if __name__=='__main__': unittest.main()
