"""TEST_ONLY publication settings, never providers or Telegram network."""
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest

from laboratory.server import Laboratory,LocalServer,Handler
from test_core import NoTelegram

class PublicationHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent/'.tmp')
        self.provider_calls=[]
        self.app=Laboratory(self.temp.name,runner=lambda *args:self.provider_calls.append(args),telegram_factory=NoTelegram)
        self.server=LocalServer(('127.0.0.1',0),Handler);self.server.app=self.app
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.app.close();self.thread.join();self.temp.cleanup()

    def request(self,path,body=None,csrf=True):
        connection=HTTPConnection('127.0.0.1',self.server.server_port,timeout=4)
        headers={'Content-Type':'application/json'}
        if csrf:headers['X-Lab-Token']=self.app.csrf
        connection.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,headers)
        response=connection.getresponse();status=response.status;raw=response.read();connection.close()
        return status,json.loads(raw)

    def test_defaults_are_empty_and_approval_cannot_be_implied_by_a_schedule(self):
        status,data=self.request('/api/publication')
        self.assertEqual(status,200);self.assertFalse(data['enabled']);self.assertEqual(data['slots'],[])
        self.assertFalse(data['channel_configured']);self.assertEqual(data['items'],[])
        status,data=self.request('/api/publication/settings',{'enabled':True,'slots':[{'weekday':1,'time':'12:00'}]})
        self.assertEqual(status,200,data);self.assertTrue(data['enabled']);self.assertFalse(data['channel_configured'])
        self.app.publisher.tick()
        self.assertEqual(self.provider_calls,[]);self.assertEqual(self.app.store.counts()['runs'],0)

    def test_settings_require_csrf_and_do_not_connect_a_channel(self):
        before=self.app.publisher.status()
        self.assertEqual(self.request('/api/publication/settings',{'enabled':True},csrf=False)[0],403)
        self.assertEqual(self.request('/api/publication/settings',{'channel_id':'@TEST_ONLY_forbidden'})[0],400)
        self.assertEqual(self.app.publisher.status()['slots'],before['slots'])
        self.assertFalse(self.app.publisher.status()['channel_configured'])
        cancel_path='/api/publication/'+'A'*16+'/cancel'
        self.assertEqual(self.request(cancel_path,{},csrf=False)[0],403)
        self.assertEqual(self.request(cancel_path,{})[0],400)

    def test_malformed_schedules_are_rejected_without_change(self):
        for slot in [{'weekday':True,'time':'12:00'},{'weekday':7,'time':'12:00'},{'weekday':0,'time':'25:00'},{'weekday':0,'time':'12:00:00'}]:
            with self.subTest(slot=slot):
                status,_=self.request('/api/publication/settings',{'enabled':True,'slots':[slot]})
                self.assertEqual(status,400);self.assertEqual(self.app.publisher.status()['slots'],[])
                self.assertFalse(self.app.publisher.status()['enabled'])

    def test_publication_state_is_operational_and_private_assets_are_not_served(self):
        self.request('/api/publication/settings',{'enabled':True,'slots':[{'weekday':1,'time':'12:00'}]})
        backup=self.app.store.export()
        self.assertNotIn('settings',backup['tables'])
        self.assertFalse(any('publication' in key for key in backup['tables']))
        connection=HTTPConnection('127.0.0.1',self.server.server_port,timeout=4)
        connection.request('GET','/.lab-data/publications/manifest.json')
        response=connection.getresponse();self.assertEqual(response.status,404);response.read();connection.close()
        self.assertEqual(self.provider_calls,[])

if __name__=='__main__':unittest.main()
