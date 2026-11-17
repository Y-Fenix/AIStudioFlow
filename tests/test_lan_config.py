import tempfile
import unittest
from pathlib import Path
from server.store import Store
from server.core.auth import Authentication

class LanConfigTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.auth=Authentication(Store(Path(self.temp.name)/'lan.sqlite'))
 def test_lan_http_requires_explicit_password_mode_opt_in(self):
  base={'mode':'password','public_url':'http://192.168.1.50:8766','registration_open':True}
  with self.assertRaises(ValueError):self.auth.save(base)
  value=self.auth.save({**base,'allow_lan_http':True})
  self.assertTrue(value['allow_lan_http']);self.assertEqual(value['public_url'],base['public_url'])
  for url in ['http://8.8.8.8:8766','http://studio.example.com','http://169.254.1.1']:
   with self.subTest(url=url),self.assertRaises(ValueError):self.auth.save({**base,'public_url':url,'allow_lan_http':True})
  with self.assertRaises(ValueError):self.auth.save({**base,'mode':'local','allow_lan_http':True})
