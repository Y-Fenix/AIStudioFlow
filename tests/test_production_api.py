import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from server.app import create_server
from server.core.integrations import AdapterRegistry


class ProductionApiTests(unittest.TestCase):
    def test_authenticated_project_routes_and_delegation_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            registry=AdapterRegistry()
            class Adapter:
                def execute(self,context):return {'deliverable':'HTTP fixture only'}
            for department in ('product','design','development'):registry.register(department,Adapter())
            server=create_server(port=0,database=Path(temp)/'db.sqlite',local_development=True,registry=registry)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base='http://127.0.0.1:'+str(server.server_address[1])
            def call(path,value=None):
                request=Request(base+path,data=json.dumps(value).encode() if value is not None else None,headers={'Content-Type':'application/json'})
                with urlopen(request,timeout=10) as response:return json.load(response)
            try:
                studio=call('/api/studios')['items'][0]['id']
                project=call('/api/studios/'+studio+'/projects',{'name':'API production'})['id']
                path=f'/api/studios/{studio}/projects/{project}/production-runs'
                listing=call(path)
                self.assertEqual(listing['runs'],[])
                self.assertTrue(listing['can_create'])
                with self.assertRaises(HTTPError) as invalid:call(path,{'brief':'missing delegation'})
                self.assertEqual(invalid.exception.code,400)
                invalid.exception.close()
                value={'brief':'memory match game','delegation':True,'request_id':'api-once'}
                run=call(path,value)
                self.assertEqual(call(path,value)['id'],run['id'])
                call(path+'/'+run['id'],{'action':'pause'})
                self.assertEqual(call(path+'/'+run['id'])['status'],'paused')
                self.assertIn('resume',call(path+'/'+run['id'])['allowed_actions'])
                self.assertEqual(call(path+'/'+run['id'],{'action':'cancel'})['status'],'cancelled')
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)
