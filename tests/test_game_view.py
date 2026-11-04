import json
import re
import unittest
from game.view import build_config, build_html

class TestGameView(unittest.TestCase):
    def test_shop_configuration(self):
        prices = {item['id']: item['price'] for item in build_config(55)['shop']}
        self.assertEqual({key: prices[key] for key in ('shovel', 'shuffle', 'refresh')},
                         {'shovel': 20, 'shuffle': 15, 'refresh': 30})

    def test_course_name_cannot_close_script_and_roundtrips(self):
        name = '</script><script>alert(1)</script>'
        html = build_html(build_config(55, course_name=name))
        self.assertNotIn(name, html)
        payload = re.search(r'window.CM_CONFIG=(.*?);</script>', html, re.S).group(1)
        self.assertEqual(json.loads(payload)['courseName'], name)

    def test_chapter_configuration_and_assets(self):
        cfg = build_config(0)
        self.assertEqual((cfg['hp'], cfg['waves'], cfg['initialLayout']), (3, 12, 'edge'))
        self.assertEqual(cfg['beastCardsMax'], 2)
        self.assertEqual(cfg['cardMaxLevel'], 4)
        self.assertEqual(cfg['beastMaxStars'], 5)
        self.assertEqual(cfg['beastEatChance'], 0.55)
        self.assertEqual(len(cfg['enemiesPerWave']), cfg['waves'])
        html = build_html(cfg)
        for placeholder in ('__CSS__', '__JS__', '__CONFIG__', '__SCENE__'):
            self.assertNotIn(placeholder, html)
        self.assertIn('viewBox="0 0 600 260"', html)
