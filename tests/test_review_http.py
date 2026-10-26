"""Review API and backup integration; fixtures only, never a provider call."""
from http.client import HTTPConnection
import copy
import json
import tempfile
import threading
import unittest

from laboratory.core import Store
from laboratory.server import Handler, Laboratory, LocalServer
from test_core import NoTelegram


class ReviewHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=Laboratory(self.temp.name,runner=lambda *args: {},telegram_factory=NoTelegram)
        self.server=LocalServer(('127.0.0.1',0),Handler);self.server.app=self.app
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        source=self.app.store.add_source('TEST_ONLY: результаты поиска ИИ')[0]
        self.run=self.app.store.create_plan({'source_ids':[source['id']]})
        self.app.store.approve(self.run['id'],self.run['plan_hash'],True,'TEST_ONLY-review')
        self.app.store.finish(self.run['id'],{'status':'completed','text':'TEST_ONLY: исходный отчёт неизменен.','usage':{'input_tokens':10,'cached_input_tokens':4,'output_tokens':2}})

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.app.close();self.thread.join();self.temp.cleanup()

    def request(self,method,path,body=None,auth=True):
        connection=HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        headers={'X-Lab-Token':self.app.csrf} if auth else {}
        connection.request(method,path,json.dumps(body) if body is not None else None,headers)
        response=connection.getresponse();result=response.status,json.loads(response.read());connection.close()
        return result

    def body(self):
        body=self.app.store.review.schema()['template']
        body['evidence']=[{'id':'ev1','claim':'TEST_ONLY: исходный текст сохранён.','basis':'local_record','locator':'runs.output','source_url':'','excerpt':'TEST_ONLY','limitations':'Фикстура'}]
        body['decisions']=[{'id':'d1','target':'Проверка исходного текста','action':'Оставить оригинал неизменным','reason':'TEST_ONLY: редактура отдельной версией','evidence_ids':['ev1'],'conditions':'Нет новых научных измерений','next_step':'Проверить историю'}]
        for criterion in body['rubric'].values():criterion.update(score=1,note='TEST_ONLY: частично',evidence_ids=['ev1'])
        return body

    def test_review_save_stale_csrf_and_original_preservation(self):
        path='/api/runs/'+self.run['id']+'/review'
        self.assertEqual(self.request('GET','/api/review/schema')[0],200)
        self.assertIsNone(self.request('GET',path)[1]['current'])
        payload={'expected_version':0,'body':self.body()}
        self.assertEqual(self.request('POST',path,payload,False)[0],403)
        status,value=self.request('POST',path,payload)
        self.assertEqual(status,200);self.assertEqual(value['current']['version'],1)
        self.assertEqual(value['quality']['total'],5);self.assertFalse(value['quality']['publish_approved'])
        self.assertEqual(value['costs']['primary']['usage']['input_tokens'],10)
        self.assertIsNone(value['costs']['primary']['money_amount'])
        self.assertEqual(self.request('POST',path,payload)[0],400)
        self.assertEqual(self.app.store.run(self.run['id'])['output'],'TEST_ONLY: исходный отчёт неизменен.')
        self.assertFalse(self.app.jobs)

    def test_schema_five_roundtrip_and_corrupt_journal_atomic_rollback(self):
        self.app.store.review.save(self.run['id'],{'expected_version':0,'body':self.body()})
        backup=self.app.store.export();self.assertEqual(backup['schema_version'],7)
        with tempfile.TemporaryDirectory() as directory:
            destination=Store(directory);destination.restore(backup)
            self.assertEqual(destination.review.get(self.run['id'])['current']['body'],self.body())
            self.assertEqual(destination.run(self.run['id'])['plan_hash'],self.run['plan_hash'])
        bad=copy.deepcopy(backup)
        row=bad['tables']['research_review_revisions'][0]
        body=json.loads(row['body']);body['decisions'][0]['evidence_ids']=['absent'];row['body']=json.dumps(body)
        with tempfile.TemporaryDirectory() as directory:
            destination=Store(directory)
            with self.assertRaises(ValueError):destination.restore(bad)
            self.assertEqual(destination.counts(),{'sources':0,'runs':0,'knowledge':0})

    def test_schema_four_restores_without_reconstructing_a_journal(self):
        backup=self.app.store.export();backup['schema_version']=4
        backup['tables'].pop('agent_phases')
        backup['tables'].pop('research_assets')
        backup['tables'].pop('research_asset_claims')
        backup['tables'].pop('research_review_revisions')
        with tempfile.TemporaryDirectory() as directory:
            destination=Store(directory);destination.restore(backup)
            self.assertIsNone(destination.review.get(self.run['id'])['current'])
            self.assertEqual(destination.run(self.run['id'])['output'],'TEST_ONLY: исходный отчёт неизменен.')


if __name__=='__main__':unittest.main()
