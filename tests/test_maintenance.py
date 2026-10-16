import copy
import hashlib
import json
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import patch
import unittest
from test_publisher import pub, issue, build, NOW

REPO = 'tyuio7777/hunt-briefing-guestbook'

class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def seed(self, items):
        with patch.object(pub, 'api_issues', return_value=items):
            rows, sync, full = pub.reconcile_issues(self.root, REPO, 'test', NOW)
        pub.save_issue_cache(self.root, rows, sync)
        return rows, sync
    def test_more_than_5000_paginated(self):
        items = [issue(i, uid=i) for i in range(1, 6202)]
        def page(repo, token, suffix):
            import urllib.parse
            n = int(urllib.parse.parse_qs(suffix[1:])['page'][0])
            return items[(n-1)*100:n*100]
        with patch.object(pub, 'api_get', side_effect=page) as api:
            result = pub.api_issues(REPO, 'test')
        self.assertEqual(len(result), 6201); self.assertEqual(api.call_count, 63)
        feed, state = build(result)
        self.assertEqual(len(feed['entries']), 500); self.assertEqual(len(feed['receipts']), 2000)
        self.assertEqual(len(state['history']), 6201)
    def test_incremental_fetch_uses_overlap_and_keeps_unchanged(self):
        rows, before = self.seed([issue(), issue(2)])
        edited = issue(text='고친 글'); edited['updated_at'] = pub.iso(NOW + pub.dt.timedelta(minutes=1))
        with patch.object(pub, 'api_issues', return_value=[edited]) as api:
            result, sync, full = pub.reconcile_issues(self.root, REPO, 'test', NOW + pub.dt.timedelta(minutes=2))
        self.assertFalse(full); self.assertEqual(api.call_args.args[2], pub.stamp(before['watermark'])-pub.dt.timedelta(minutes=5))
        self.assertEqual(len(result), 2); self.assertEqual(result['2'], rows['2'])
        first, state = build(rows.values()); second, _ = build(result.values(), state=state, now=NOW+pub.dt.timedelta(minutes=2))
        self.assertEqual(first['entries'][-1]['first_published_at'], second['entries'][-1]['first_published_at'])
    def test_no_change_preserves_checkpoint_and_public_version(self):
        rows, before = self.seed([issue()])
        with patch.object(pub, 'api_issues', return_value=[]):
            result, sync, full = pub.reconcile_issues(self.root, REPO, 'test', NOW+pub.dt.timedelta(hours=1))
        self.assertEqual(rows, result); self.assertEqual(sync, before); self.assertFalse(full)
        feed, _ = build(rows.values());pub.publish_version(self.root, feed)
        first = (self.root/'data/guestbook-version.json').read_bytes()
        pub.publish_version(self.root, feed)
        self.assertEqual(first, (self.root/'data/guestbook-version.json').read_bytes())
    def test_weekly_reconciliation(self):
        self.seed([issue()])
        with patch.object(pub, 'api_issues', return_value=[issue()]) as api:
            _, _, full = pub.reconcile_issues(self.root, REPO, 'test', NOW+pub.dt.timedelta(days=7))
        self.assertTrue(full); self.assertIsNone(api.call_args.args[2])
    def test_deleted_issue_confirmed_but_history_retained(self):
        rows, _ = self.seed([issue()]);_, state = build(rows.values())
        with patch.object(pub, 'api_issues', return_value=[]), patch.object(pub, 'api_get', side_effect=urllib.error.HTTPError('x',404,'',{},None)):
            result, _, _ = pub.reconcile_issues(self.root, REPO, 'test', NOW, force_full=True)
        feed, after = build(result.values(), state=state)
        self.assertEqual(feed['entries'], []);self.assertEqual(after, state)
    def test_pagination_shift_does_not_remove_existing_issue(self):
        self.seed([issue()])
        with patch.object(pub, 'api_issues', return_value=[]), patch.object(pub, 'api_get', return_value=issue()):
            result, _, _ = pub.reconcile_issues(self.root, REPO, 'test', NOW, force_full=True)
        self.assertIn('1',result)
    def test_network_failure_no_cache_writes(self):
        self.seed([issue()]); before = {p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*.json')}
        with patch.object(pub, 'api_issues', side_effect=OSError('offline')):
            with self.assertRaises(OSError): pub.reconcile_issues(self.root, REPO, 'test', NOW, force_full=True)
        self.assertEqual(before, {p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*.json')})
    def test_missing_cache_triggers_rebuild(self):
        self.seed([issue()]); next((self.root/'state/issues').glob('*.json')).unlink()
        with patch.object(pub, 'api_issues', return_value=[issue()]):
            result, _, full = pub.reconcile_issues(self.root, REPO, 'test', NOW)
        self.assertTrue(full);self.assertEqual(len(result),1)
    def test_repeated_api_page_aborts(self):
        with patch.object(pub,'api_get', return_value=[issue(i) for i in range(1,101)]):
            with self.assertRaises(ValueError): pub.api_issues(REPO,'test')
    def test_future_watermark_does_not_advance(self):
        self.seed([]); value=issue();value['updated_at']=pub.iso(NOW+pub.dt.timedelta(days=1))
        before=(self.root/'state/sync.json').read_bytes()
        with patch.object(pub,'api_issues',return_value=[value]):
            with self.assertRaises(ValueError): pub.reconcile_issues(self.root,REPO,'test',NOW)
        self.assertEqual(before,(self.root/'state/sync.json').read_bytes())
    def test_compact_cache_has_no_unneeded_api_fields(self):
        source={**issue(), 'comments':123,'html_url':'https://example.org','labels':[{'name':'x'}]}
        result=pub.compact_issue(source)
        self.assertNotIn('comments', result);self.assertNotIn('html_url',result)
        self.assertEqual(build([source])[0],build([result])[0])
    def test_oversized_body_keeps_rejection_receipt(self):
        value=issue(text='한'*10000)
        compact=pub.compact_issue(value)
        self.assertLess(len(compact['body']),100)
        self.assertEqual(build([compact])[0]['receipts'][0]['status'],'rejected')
    def test_version_hash_matches_legacy_and_immutable_body(self):
        feed,_=build([issue()]);pub.publish_version(self.root,feed)
        meta=json.loads((self.root/'data/guestbook-version.json').read_text())
        raw=(self.root/'data/guestbook.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),meta['revision']);self.assertEqual(len(raw),meta['size_bytes'])
        self.assertEqual(raw,(self.root/f"data/snapshots/{meta['revision']}.json").read_bytes())
    def test_snapshot_rotation_is_bounded_and_current_kept(self):
        feed,_=build([issue()])
        for i in range(15):
            feed['generated_at']=pub.iso(NOW+pub.dt.timedelta(seconds=i));pub.publish_version(self.root,feed)
        files=list((self.root/'data/snapshots').glob('*.json'))
        meta=json.loads((self.root/'data/guestbook-version.json').read_text())
        self.assertEqual(len(files),8);self.assertTrue((self.root/f"data/snapshots/{meta['revision']}.json").exists())
    def test_storage_report_stable_without_changes(self):
        rows,_=self.seed([issue()]);feed,state=build(rows.values());pub.publish_version(self.root,feed)
        pub.storage_status(self.root,rows,state['history']); before=(self.root/'data/storage-status.json').read_bytes()
        pub.storage_status(self.root,rows,state['history']);self.assertEqual(before,(self.root/'data/storage-status.json').read_bytes())

if __name__ == '__main__': unittest.main()
