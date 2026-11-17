import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PRODUCT_SkillSourcesTests(unittest.TestCase):
    def test_reverse_competitor_analysis_cites_adapted_game_studio_skill(self):
        skill = (ROOT / 'departments/product/skills/1.md').read_text(encoding='utf-8')
        manifest = json.loads((ROOT / 'departments/product/manifest.json').read_text(encoding='utf-8'))

        self.assertEqual(manifest['nodes'][1][0], '竞品拆解 / 反编译')
        self.assertIn('Claude-Code-Game-Studios', skill)
        self.assertIn('reverse-document/SKILL.md', skill)
        self.assertIn('MIT', skill)
        self.assertIn('不声称取得完整源码', skill)
        self.assertIn('不擅自提交、拉取或推送 Git', skill)


if __name__ == '__main__':
    unittest.main()
