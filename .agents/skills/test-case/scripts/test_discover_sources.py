"""Run with python3 -B scripts/test_discover_sources.py; no CLI/network access."""
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

from discover_sources import discover

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='test-case-sources-')
        self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def put(self,name,text):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8');return path
    def test_selectable_files_keep_paths_and_dedupe_urls(self):
        self.put('文档/需求/链接.md','[通知](https://demo.feishu.cn/docx/Notify)\nhttps://demo.feishu.cn/docx/Notify\nhttps://demo.feishu.cn/wiki/Climb#share-one')
        self.put('docs/链接.md','https://demo.larksuite.com/docx/Other')
        result=discover(self.root)
        self.assertEqual({r['path'] for r in result['link_files']},{'文档/需求/链接.md','docs/链接.md'})
        row=next(r for r in result['link_files'] if r['path'].startswith('文档'))
        self.assertEqual(row['link_count'],2)
        self.assertEqual(len(row['links'][0]['locations']),2)
    def test_word_relationships_and_excel_formula(self):
        word=self.root/'活动需求.docx'
        with zipfile.ZipFile(word,'w') as archive:
            archive.writestr('word/document.xml','<document><p><r><t>https://x.feishu.cn/wiki/World</t></r></p></document>')
            archive.writestr('word/_rels/document.xml.rels','<Relationships><Relationship Target="https://x.feishu.cn/docx/Reward?a=1&amp;b=2"/></Relationships>')
        with zipfile.ZipFile(self.root/'测试.xlsx','w') as archive:
            archive.writestr('xl/worksheets/sheet1.xml','<worksheet><f>HYPERLINK("https://x.larksuite.com/sheets/Sheet", "奖励表")</f></worksheet>')
        rows=discover(self.root)['link_files']
        self.assertEqual(sum(r['link_count'] for r in rows),3)
        self.assertIn('https://x.feishu.cn/docx/Reward?a=1&b=2',{v['url'] for r in rows for v in r['links']})
    def test_shortcut_anchor_and_deceptive_host(self):
        self.put('需求.url','[InternetShortcut]\nURL=https://x.feishu.cn/docx/Notify#share-first')
        (self.root/'需求.webloc').write_bytes(plistlib.dumps({'URL':'https://www.doubao.com/wiki/Valid'}))
        self.put('错误.md','https://x.feishu.cn.evil.invalid/docx/No\nhttps://example.com/wiki/No\nhttps://x.feishu.cn/docx/Notify#share-second')
        urls={v['url'] for r in discover(self.root)['link_files'] for v in r['links']}
        self.assertEqual(len(urls),3)
        self.assertTrue(any(u.endswith('#share-first') for u in urls))
        self.assertTrue(any(u.endswith('#share-second') for u in urls))
        self.assertFalse(any('evil' in u for u in urls))
    def test_exclusions_ignored_target_and_outside_symlink(self):
        self.put('QA/results/old/链接.md','https://x.feishu.cn/docx/Old')
        self.put('Library/需求.md','https://x.feishu.cn/docx/Cache')
        self.put('.ignore','private/\n')
        self.put('private/需求.md','https://x.feishu.cn/docx/Private')
        self.assertEqual(discover(self.root)['link_files'],[])
        rows=discover(self.root,['private'],True)['link_files']
        self.assertEqual(len(rows),1)
        with tempfile.TemporaryDirectory() as other:
            outside=Path(other)/'outside.md';outside.write_text('https://x.feishu.cn/docx/Outside')
            (self.root/'需求外链.md').symlink_to(outside)
            self.assertEqual(discover(self.root)['link_files'],[])
            with self.assertRaises(ValueError):discover(self.root,[other])
    def test_incomplete_formats_and_large_files_are_visible(self):
        self.put('需求.pdf','not a real pdf')
        self.put('损坏需求.docx','broken zip')
        self.put('需求.md','a'*40)
        result=discover(self.root,max_bytes=20)
        self.assertEqual({r['path'] for r in result['uninspected']},{'需求.pdf','损坏需求.docx','需求.md'})
        self.assertEqual(len(result['local_documents']),3)
    def test_cli_json_and_no_persistent_output(self):
        self.put('需求.md','https://x.feishu.cn/base/Table')
        before=set(self.root.iterdir())
        script=Path(__file__).with_name('discover_sources.py')
        run=subprocess.run([sys.executable,'-B',str(script),'--project',str(self.root)],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(json.loads(run.stdout)['link_files'][0]['link_count'],1)
        self.assertEqual(before,set(self.root.iterdir()))

if __name__=='__main__':unittest.main()
