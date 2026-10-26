"""TEST_ONLY alternating packages; mocked media and Telegram transport only."""
from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import patch

from laboratory.publication import Publisher, QUEUE_KEY
from laboratory.visual_skin import rotation_position
try:
    from . import test_publication as fixtures
except ImportError:
    import test_publication as fixtures


class VisualRotationTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.PublicationTests(methodName='runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.data['motion_story'] = {
            'version':'dataflow-v1', 'kind':'process',
            'nodes':[{'id':'a','label':'TEST_ONLY вход','lane':'technology'}], 'edges':[]}
        self.p = self.f.publisher
        for name,prefix in [('render_png',b'TEST_ONLY_PNG_'),('render_mp4',b'TEST_ONLY_MP4_')]:
            mock=patch('laboratory.presentation.'+name,
                       side_effect=lambda data,prefix=prefix:prefix+data['visual_skin']['id'].encode('ascii'))
            mock.start();self.addCleanup(mock.stop)
        self.f.connect()

    def item(self, entry):
        return next(row for row in self.p.status()['items'] if row['id']==entry['id'])

    def test_sequence_pins_one_style_for_both_media_and_refresh_is_read_only(self):
        before=self.f.store.get_setting(QUEUE_KEY,{})
        for _ in range(4):
            data=self.p.apply_visual_rotation(self.f.run['id'],deepcopy(self.f.data))
            self.assertEqual(rotation_position(data['visual_skin']),1)
        self.assertEqual(self.f.store.get_setting(QUEUE_KEY,{}),before)
        first=self.f.prepare()
        self.assertEqual(first['visual_skin']['id'],'dashboard')
        assets=self.p.assets(first['id'])
        self.assertTrue(all(value.endswith(b'dashboard') for value in assets.values()))
        self.assertEqual(self.f.prepare()['id'],first['id'])
        self.f.approve(first)
        duplicate=self.f.approve(first)
        self.assertEqual(rotation_position(duplicate['visual_skin']),1)
        second=self.f.prepare(self.f.complete('two'))
        self.assertEqual(rotation_position(second['visual_skin']),2)
        self.assertEqual(second['visual_skin']['id'],'blackboard')
        self.assertTrue(all(value.endswith(b'blackboard') for value in self.p.assets(second['id']).values()))
        self.f.approve(second)
        third=self.f.prepare(self.f.complete('three'))
        self.assertEqual(rotation_position(third['visual_skin']),3)
        pinned=self.p.apply_visual_rotation(self.f.run['id'],deepcopy(self.f.data))
        self.assertEqual(rotation_position(pinned['visual_skin']),1)
        first['visual_skin']['rotation']['position']=999
        self.assertEqual(rotation_position(self.item(duplicate)['visual_skin']),1)

    def test_two_previews_do_not_silently_restyle_second_owner_approval(self):
        first=self.f.prepare()
        other_run=self.f.complete('two')
        second=self.f.prepare(other_run)
        self.assertEqual(rotation_position(second['visual_skin']),1)
        frozen=self.p.assets(second['id'])
        self.f.approve(first)
        with self.assertRaisesRegex(ValueError,'/result'):
            self.f.approve(second)
        self.assertEqual(self.item(second)['status'],'blocked')
        self.assertEqual(self.p.assets(second['id']),frozen)
        fresh=self.f.prepare(other_run)
        self.assertNotEqual(second['id'],fresh['id'])
        self.assertEqual(rotation_position(fresh['visual_skin']),2)
        self.assertEqual(self.f.approve(fresh)['status'],'queued')
        self.assertEqual(self.f.bridge.calls,[])

    def test_cancelled_predecessor_revokes_suffix_without_rewriting_approved_files(self):
        first=self.f.prepare();self.f.approve(first)
        second_run=self.f.complete('two');second=self.f.prepare(second_run);self.f.approve(second)
        third=self.f.prepare(self.f.complete('three'));self.f.approve(third)
        frozen={entry['id']:self.p.assets(entry['id']) for entry in (first,second,third)}
        self.p.cancel(first['id'])
        self.assertEqual(self.item(first)['status'],'cancelled')
        for entry in (second,third):
            self.assertEqual(self.item(entry)['status'],'blocked')
            self.assertEqual(self.p.assets(entry['id']),frozen[entry['id']])
        replacement=self.f.prepare(second_run)
        self.assertEqual(rotation_position(replacement['visual_skin']),1)
        self.assertEqual(self.f.approve(replacement)['status'],'queued')
        self.assertEqual(self.f.bridge.calls,[])

    def test_restart_keeps_published_and_uncertain_anchors_without_extra_advance(self):
        first=self.f.prepare();self.f.approve(first)
        second_run=self.f.complete('two');second=self.f.prepare(second_run);self.f.approve(second)
        self.f.now+=timedelta(hours=1)
        self.p.tick()
        self.assertEqual(self.item(first)['status'],'published')
        self.p=Publisher(self.f.store,self.f.bridge,self.f.builder,clock=lambda:self.f.now)
        self.f.publisher=self.p
        self.assertEqual(self.f.prepare(second_run)['id'],second['id'])
        third=self.f.prepare(self.f.complete('three'))
        self.assertEqual(rotation_position(third['visual_skin']),3)
        # A durable interrupted send is an occupied position, never an implicit
        # cancelled post or a reason to retry its transport after restart.
        saved=self.f.store.get_setting(QUEUE_KEY)
        saved[second['id']]['state']='publishing'
        self.f.store.set_setting(QUEUE_KEY,saved)
        self.p=Publisher(self.f.store,self.f.bridge,self.f.builder,clock=lambda:self.f.now)
        self.f.publisher=self.p
        calls=len(self.f.bridge.calls)
        self.assertEqual(self.item(second)['status'],'publication_uncertain')
        data=self.p.apply_visual_rotation('TEST_ONLY_next_run',deepcopy(self.f.data))
        self.assertEqual(rotation_position(data['visual_skin']),3)
        self.assertEqual(len(self.f.bridge.calls),calls)

    def test_numeric_order_survives_reverse_ids_same_second_and_missed_slot(self):
        with patch('laboratory.publication.secrets.token_urlsafe',side_effect=[
                'zzzzzzzzzzzzzzzz','TEST_ONLY_TOKEN_1','aaaaaaaaaaaaaaaa','TEST_ONLY_TOKEN_2']):
            first=self.f.prepare();self.f.approve(first)
            second=self.f.prepare(self.f.complete('two'));self.f.approve(second)
        self.p.configure({'slots':[{'weekday':d,'time':'12:00'} for d in range(3)]})
        self.assertLess(self.item(first)['due_at'],self.item(second)['due_at'])
        self.f.now+=timedelta(hours=2)
        self.p.tick()
        self.assertEqual(self.item(first)['due_at'],'2026-10-20T09:00:00+00:00')
        self.assertEqual(self.item(second)['due_at'],'2026-10-21T09:00:00+00:00')
        self.assertEqual(self.f.bridge.calls,[])

    def test_failed_predecessor_validation_blocks_later_style_before_transport(self):
        first=self.f.prepare();self.f.approve(first)
        second=self.f.prepare(self.f.complete('two'));self.f.approve(second)
        frozen=self.p.assets(second['id'])
        tampered=deepcopy(self.f.store.get_setting(QUEUE_KEY)[first['id']])
        tampered['visual_skin']['rotation']['position']=2
        with self.assertRaisesRegex(ValueError,'Оформление'):
            self.p._validate(tampered,42,'TEST_ONLY_fingerprint')
        (self.f.store.data_dir/'publications'/first['id']/'card.png').write_bytes(b'TEST_ONLY_TAMPERED')
        self.f.now+=timedelta(hours=1)
        self.p.tick()
        self.assertEqual(self.item(first)['status'],'blocked')
        self.assertEqual(self.item(second)['status'],'blocked')
        self.assertEqual(self.p.assets(second['id']),frozen)
        self.assertEqual(self.f.bridge.calls,[])


if __name__=='__main__':unittest.main()
