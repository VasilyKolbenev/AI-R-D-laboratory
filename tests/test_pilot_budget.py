"""One explicit pilot can exceed the local cap, never escape its plan or retry."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import unittest
from laboratory.core import LabError,PILOT_BUDGET_KEY,Store

class PilotBudgetTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store=Store(Path(temp.name))
        source,_=self.store.add_source('TEST_ONLY AI code review research https://example.org/article')
        self.source=source['id']
        self.store.update_settings({'daily_run_limit':1})
        first=self.plan()
        self.store.approve(first['id'],first['plan_hash'],True,'TEST_ONLY-first-budget')
        self.store.finish(first['id'],{'status':'failed','error':'TEST_ONLY consumed one slot'})

    def plan(self):
        return self.store.create_plan({'source_ids':[self.source],'question':'TEST_ONLY applicability of AI code review','timeout_seconds':180})

    def test_allowance_is_one_matching_approval_and_does_not_raise_daily_cap(self):
        run=self.plan()
        with self.assertRaises(LabError):self.store.approve(run['id'],run['plan_hash'],True,'TEST_ONLY-blocked')
        grant=self.store.grant_pilot(run['id'],run['plan_hash'])
        self.assertEqual(grant['max_runs'],1)
        self.assertIsNotNone(self.store.pilot_allowance(run['id']))
        self.store.approve(run['id'],run['plan_hash'],True,'TEST_ONLY-pilot-one')
        self.assertFalse(self.store.approve(run['id'],run['plan_hash'],True,'TEST_ONLY-pilot-replay'))
        self.store.finish(run['id'],{'status':'outcome_unknown','error':'TEST_ONLY do not retry'})
        self.assertIsNone(self.store.pilot_allowance(run['id']))
        self.assertEqual(self.store.settings()['daily_run_limit'],1)
        other=self.plan()
        with self.assertRaises(LabError):self.store.approve(other['id'],other['plan_hash'],True,'TEST_ONLY-pilot-other')

    def test_changed_hash_or_expired_grant_cannot_authorize_a_run(self):
        run=self.plan();self.store.grant_pilot(run['id'],run['plan_hash'])
        changed=self.store.replan_context(run['id'],{'memory_options':{'enabled':False}})
        self.assertNotEqual(run['plan_hash'],changed['plan_hash'])
        with self.assertRaises(LabError):self.store.approve(changed['id'],changed['plan_hash'],True,'TEST_ONLY-changed')
        self.store.grant_pilot(changed['id'],changed['plan_hash'])
        saved=self.store.get_setting(PILOT_BUDGET_KEY)
        saved[run['id']]['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        self.store.set_setting(PILOT_BUDGET_KEY,saved)
        with self.assertRaises(LabError):self.store.approve(changed['id'],changed['plan_hash'],True,'TEST_ONLY-expired')

    def test_no_consent_or_longer_budget_is_permitted(self):
        run=self.plan();self.store.grant_pilot(run['id'],run['plan_hash'])
        with self.assertRaises(LabError):self.store.approve(run['id'],run['plan_hash'],False,'TEST_ONLY-no-consent')
        long=self.store.create_plan({'source_ids':[self.source],'question':'TEST_ONLY code review','timeout_seconds':240})
        with self.assertRaises(LabError):self.store.grant_pilot(long['id'],long['plan_hash'])
        self.assertEqual(self.store.run(run['id'])['status'],'planned')

if __name__=='__main__':unittest.main()
