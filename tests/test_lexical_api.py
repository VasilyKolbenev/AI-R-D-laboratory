"""TEST_ONLY route contract. No benchmark corpus, network, models or publication."""
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch
from laboratory.lexical_api import handle_get, handle_post, BASE, view


class LexicalApiTests(unittest.TestCase):
    def setUp(self):
        self.id='a'*64;self.hash='b'*64
        self.app=SimpleNamespace(store=object(),jobs={},experiment_jobs={},experiment_errors={},lock=threading.Lock())
        self.handler=SimpleNamespace(app=self.app,send=Mock())
        self.service=Mock();self.service.status.return_value={'plan_id':self.id,'plan_hash':self.hash,'status':'planned'}
        self.service.assets.get.return_value={'payload':{'scope':'TEST_ONLY lexical scope'}}
        self.patcher=patch('laboratory.lexical_api.LexicalBenchmark',return_value=self.service)
        self.patcher.start();self.addCleanup(self.patcher.stop)

    def body(self,**values):
        return {'plan_id':self.id,'plan_hash':self.hash,'consent':True,'command_id':'TEST_ONLY_command',**values}

    def test_get_only_projects_and_never_prepares_or_executes(self):
        self.assertTrue(handle_get(self.handler,BASE))
        self.assertTrue(handle_get(self.handler,BASE+'/'+self.id))
        self.assertFalse(handle_get(self.handler,BASE+'/../start'))
        self.service.prepare.assert_not_called();self.service.start.assert_not_called()

    def test_start_rejects_missing_consent_hash_and_extra_fields_before_worker(self):
        for body in [self.body(consent=False),self.body(plan_hash='c'*64),self.body(command_id='bad'),{**self.body(),'dataset_path':'TEST_ONLY_no_path'}]:
            with self.assertRaises(ValueError):handle_post(self.handler,BASE+'/start',body)
        self.assertEqual(self.app.experiment_jobs,{})
        self.service.start.assert_not_called()

    def test_existing_terminal_result_is_returned_not_run_again(self):
        self.service.status.return_value.update(status='completed')
        self.assertTrue(handle_post(self.handler,BASE+'/start',self.body()))
        self.service.start.assert_not_called();self.assertEqual(self.app.experiment_jobs,{})

    def test_interlock_with_model_and_other_experiment(self):
        for name in ['jobs','experiment_jobs']:
            getattr(self.app,name)['TEST_ONLY']=object()
            with self.assertRaises(ValueError):handle_post(self.handler,BASE+'/start',self.body())
            getattr(self.app,name).clear()
        self.service.start.assert_not_called()

    def test_only_explicit_start_builds_one_worker_with_exact_approved_values(self):
        targets=[]
        class FakeWorker:
            def __init__(self,target,daemon):targets.append(target)
            def start(self):pass
        with patch('laboratory.lexical_api.threading.Thread',FakeWorker):
            self.assertTrue(handle_post(self.handler,BASE+'/start',self.body()))
        self.assertEqual(len(targets),1);self.service.start.assert_not_called()
        self.assertEqual(view(self.app,self.id)['status'],'running')
        targets[0]()
        args=self.service.start.call_args.args
        self.assertEqual(args[:4],(self.id,self.hash,True,'TEST_ONLY_command'))
        self.assertEqual(self.app.experiment_jobs,{})

    def test_worker_error_has_no_automatic_repeat(self):
        targets=[]
        class FakeWorker:
            def __init__(self,target,daemon):targets.append(target)
            def start(self):pass
        self.service.start.side_effect=ValueError('TEST_ONLY drift')
        with patch('laboratory.lexical_api.threading.Thread',FakeWorker):handle_post(self.handler,BASE+'/start',self.body())
        targets[0]();self.service.start.assert_called_once()
        self.assertIn(self.id,self.app.experiment_errors)
        self.assertEqual(self.app.experiment_jobs,{})

    def test_prepare_forbids_remote_or_arbitrary_dataset_body(self):
        with self.assertRaises(ValueError):handle_post(self.handler,BASE+'/prepare',{'path':'C:/TEST_ONLY'})
        self.service.prepare.assert_not_called()


if __name__=='__main__':unittest.main()
