"""界面配置的持久化、覆盖范围、密钥复用与失败保护。"""
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from config import model_settings as models
from config.settings import ConfigError, Settings


class TestModelSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.base = Settings(db_path=root/'course.db', chroma_path=root/'index', upload_dir=root/'uploads',
                             llm_base_url='https://old.example/v1', llm_api_key='synthetic-old-key', llm_model='old-model')

    def tearDown(self):
        self.tmp.cleanup()

    def configured(self):
        return models.candidate(self.base, provider='custom', base_url='https://new.example/v1/',
                                api_key='synthetic-new-key', model='selected-model', timeout=30)

    def test_save_reload_only_changes_model_fields(self):
        models.save(self.configured())
        loaded = models.apply(self.base)
        self.assertEqual((loaded.llm_base_url, loaded.llm_model, loaded.llm_api_key),
                         ('https://new.example/v1', 'selected-model', 'synthetic-new-key'))
        self.assertEqual(loaded.db_path, self.base.db_path)
        self.assertEqual(loaded.embedding_model, self.base.embedding_model)
        self.assertEqual(set(json.loads(models.config_path(self.base).read_text())), models.FIELDS)

    def test_same_endpoint_can_reuse_existing_key(self):
        settings = models.candidate(self.base, provider='custom', base_url=self.base.llm_base_url,
                                    api_key='', model='another-model')
        self.assertEqual(settings.llm_api_key, self.base.llm_api_key)

    def test_new_endpoint_requires_explicit_key(self):
        with self.assertRaises(ConfigError):
            models.candidate(self.base, provider='custom', base_url='https://new.example/v1', api_key='', model='model')

    def test_invalid_urls_rejected(self):
        for url in ['file:///tmp/data', 'https://user:password@example.com', 'https://host/?key=abc',
                    'https://host/#key', 'https://bad host/v1', 'https://host:bad', 'https://host/v1/chat/completions']:
            with self.subTest(url=url), self.assertRaises(ConfigError):
                models.candidate(self.base, provider='custom', base_url=url, api_key='test-key', model='model')

    def test_missing_model_rejected(self):
        with self.assertRaises(ConfigError):
            models.candidate(self.base, provider='custom', base_url=self.base.llm_base_url, api_key='', model=' ')

    def test_failed_atomic_save_keeps_existing_file(self):
        models.save(self.configured())
        before = models.config_path(self.base).read_bytes()
        with patch('config.model_settings.os.replace', side_effect=PermissionError), self.assertRaises(ConfigError):
            models.save(replace(self.configured(), llm_model='not-saved'))
        self.assertEqual(models.config_path(self.base).read_bytes(), before)
        self.assertEqual(list(self.base.db_path.parent.glob('.model_*.tmp')), [])

    def test_corrupt_file_falls_back_and_can_be_replaced(self):
        models.config_path(self.base).write_text('{broken')
        self.assertEqual(models.apply(self.base), self.base)
        models.save(self.configured())
        self.assertEqual(models.apply(self.base).llm_model, 'selected-model')

    def test_saved_config_takes_precedence_in_settings_load(self):
        models.save(self.configured())
        env = {'DB_PATH': str(self.base.db_path), 'LLM_MODEL':'environment-model',
               'LLM_API_KEY':'synthetic-environment-key', 'LLM_BASE_URL':'https://environment.example/v1'}
        with patch.dict(os.environ, env):
            loaded = Settings.load(env_file=self.base.db_path.parent/'missing.env')
        self.assertEqual(loaded.llm_model, 'selected-model')

    def test_unsafe_extra_fields_cannot_override_storage(self):
        models.save(self.configured())
        file = models.config_path(self.base)
        data = json.loads(file.read_text()); data['db_path'] = 'external.db'
        file.write_text(json.dumps(data))
        self.assertEqual(models.apply(self.base), self.base)
