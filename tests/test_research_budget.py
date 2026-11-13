"""TEST_ONLY rolling reservation tests, without providers, Telegram or network."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from laboratory.core import BudgetLimitError, Store
from laboratory.research_budget import notice, snapshot


class ResearchBudgetTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).parent / '.tmp'
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.source = self.store.add_source('TEST_ONLY AI comparison source')[0]
        self.at = datetime(2026, 10, 27, 11, 30, tzinfo=timezone.utc)

    def plan(self, calls=3):
        options = {'source_ids': [self.source['id']]}
        if calls == 3:
            options.update(research_mode='reviewed', timeout_seconds=240)
        return self.store.create_plan(options)

    def reserve(self, approved, calls=3, status='completed'):
        run = self.plan(calls)
        with self.store.connect() as db:
            db.execute('UPDATE runs SET approved_at=?,status=? WHERE id=?', (approved, status, run['id']))
        return run

    def budget(self, limit=6, required=3, at=None):
        with self.store.connect() as db:
            return snapshot(db, limit, required, at or self.at)

    def test_exact_24h_boundary_and_moscow_time(self):
        self.reserve('2026-10-26T13:19:19+00:00')
        self.reserve('2026-10-27T11:15:13+00:00')
        budget = self.budget()
        self.assertEqual((budget['used'], budget['available']), (6, 0))
        self.assertEqual(budget['next_eligible_at'], '2026-10-27T13:19:20+00:00')
        self.assertIn('27.10.2026 16:19:20 МСК', notice(budget))
        self.assertFalse(self.budget(at=datetime(2026, 10, 27, 13, 19, 19, tzinfo=timezone.utc))['can_start'])
        self.assertTrue(self.budget(at=datetime(2026, 10, 27, 13, 19, 20, tzinfo=timezone.utc))['can_start'])

    def test_waits_until_enough_weighted_reservations_expire(self):
        self.reserve('2026-10-26T12:00:00+00:00', calls=1)
        self.reserve('2026-10-26T13:00:00+00:00', calls=3)
        budget = self.budget(limit=4)
        self.assertEqual(budget['next_eligible_at'], '2026-10-27T13:00:01+00:00')
        self.assertEqual(self.budget(limit=4, required=1)['next_eligible_at'], '2026-10-27T12:00:01+00:00')

    def test_failed_unknown_and_cancelled_approvals_are_still_reserved(self):
        for status in ('failed', 'outcome_unknown', 'cancelled'):
            self.reserve('2026-10-27T10:00:00+00:00', calls=1, status=status)
        self.plan()  # A prepared but unapproved plan does not consume anything.
        self.assertEqual(self.budget(limit=3)['used'], 3)

    def test_plan_larger_than_limit_has_no_wait_time(self):
        budget = self.budget(limit=2)
        self.assertFalse(budget['can_start'])
        self.assertIsNone(budget['next_eligible_at'])
        self.assertIn('ожидание не освободит', notice(budget))
        self.assertNotIn('После освобождения', notice(budget))

    def test_refresh_preserves_reservation_and_rejected_approval_is_free(self):
        self.store.update_settings({'daily_run_limit': 3})
        self.reserve('2026-10-27T10:00:00+00:00')
        run = self.plan()
        refreshed = self.store.replan_context(run['id'], {'memory_options': {}})
        with patch('laboratory.core.datetime', wraps=datetime) as clock:
            clock.now.return_value = self.at
            before = self.store.budget_status(refreshed['plan'])
            with self.assertRaises(BudgetLimitError) as caught:
                self.store.approve(refreshed['id'], refreshed['plan_hash'], True, 'TEST_ONLY-budget-approve')
            self.assertEqual(caught.exception.budget, before)
            self.assertEqual(self.store.budget_status(refreshed['plan']), before)
        saved = self.store.run(refreshed['id'])
        self.assertEqual(saved['status'], 'planned')
        self.assertIsNone(saved['approved_at'])
        self.assertEqual(self.store.settings()['daily_run_limit'], 3)

    def test_ready_snapshot_does_not_promise_provider_quota(self):
        budget = self.budget()
        self.assertTrue(budget['can_start'])
        self.assertIsNone(budget['next_eligible_at'])
        self.assertIn('не остаток лимита провайдера', notice(budget))


if __name__ == '__main__':
    unittest.main()
