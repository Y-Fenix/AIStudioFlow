import json
import unittest
from server.core.notifications import card_for, result_summary


class ProductionNotificationTests(unittest.TestCase):
    def row(self):
        return {'id':4,'studio_id':'s','project_id':'p','node':'testing:1','task_id':'','event':'completed','payload':json.dumps({'studio':'Studio','project':'Game','department':'测试','node_title':'执行','origin':'production','production_run_id':'run1','summary':'18步骤中完成15步；委托审核，非人工质量验收'})}
    def test_production_card_uses_run_deep_link_and_delegated_title(self):
        card=card_for(self.row(),{'public_url':'https://studio.example'})
        title=card['header']['title']['content']
        self.assertIn('委托审核',title)
        self.assertNotIn('待审核',title)
        url=next(e for e in card['elements'] if e['tag']=='action')['actions'][0]['url']
        self.assertIn('view=production',url)
        self.assertIn('production_run=run1',url)
        self.assertNotIn('node=testing',url)
    def test_production_summary_has_accurate_progress_boundary(self):
        summary=result_summary('testing:1',{'production_summary':'完成15/18；实际静态检查，未代替客户端实测'},'production')
        self.assertEqual(summary,'完成15/18；实际静态检查，未代替客户端实测')
