import copy
import json
import threading
import unittest
from unittest.mock import patch
from test_publisher import pub, issue, build, BRIEFING, CATALOG, NOW
from test_comments import c, comment, build as build_comments

class PublicationLatencyTests(unittest.TestCase):
    def test_existing_verified_reference_needs_no_remote_read(self):
        _, state=build([issue(briefing_id=BRIEFING['id'])],catalog=CATALOG)
        self.assertFalse(pub.needs_briefing_catalog([issue(briefing_id=BRIEFING['id'])],state))
        self.assertTrue(pub.needs_briefing_catalog([issue(briefing_id=BRIEFING['id'])]))
    def test_new_or_changed_reference_requires_catalog(self):
        _,state=build([issue(briefing_id=BRIEFING['id'])],catalog=CATALOG)
        self.assertTrue(pub.needs_briefing_catalog([issue(briefing_id='other')],state))
        self.assertTrue(pub.needs_briefing_catalog([issue(2,briefing_id=BRIEFING['id'])],state))
    def test_untrusted_reference_cache_cannot_bypass_validation(self):
        _,state=build([issue(briefing_id=BRIEFING['id'])],catalog=CATALOG)
        state['history']['1']['briefing_reference']['html_url']='https://evil.example/a.html'
        self.assertTrue(pub.needs_briefing_catalog([issue(briefing_id=BRIEFING['id'])],state))
        with self.assertRaises(ValueError):pub.resolve_reference({'briefing_id':BRIEFING['id']},state['history']['1'],{})
    def test_reused_history_still_applies_moderation(self):
        from test_publisher import POLICY
        _,state=build([issue(briefing_id=BRIEFING['id'])],catalog=CATALOG)
        feed,_=build([issue(briefing_id=BRIEFING['id'])],state,policy={**POLICY,'hidden_issue_numbers':[1]},catalog={})
        self.assertEqual(feed['entries'],[])
    def test_parallel_related_reads_join_before_return(self):
        barrier=threading.Barrier(3,timeout=2)
        def edits(*args):barrier.wait()
        def comments(*args):barrier.wait();return {'comments':1},{'sync':1}
        def catalog():barrier.wait();return CATALOG
        with patch.object(c,'enrich_edits',side_effect=edits),patch.object(c,'reconcile',side_effect=comments),patch.object(pub,'load_briefing_catalog',side_effect=catalog):
            rows,sync,refs=pub.collect_related(None,{'1':issue(briefing_id=BRIEFING['id'])},{},'repo','unused',NOW,False,{}, {},False)
        self.assertEqual((rows,sync,refs),({'comments':1},{'sync':1},CATALOG))
    def test_reference_free_requests_skip_catalog(self):
        with patch.object(c,'enrich_edits'),patch.object(c,'reconcile',return_value=({},{})),patch.object(pub,'load_briefing_catalog',side_effect=AssertionError('unexpected fetch')):
            self.assertEqual(pub.collect_related(None,{'1':issue()},{},'repo','unused',NOW,False,{}, {},False),({},{},{}))
    def test_read_failure_does_not_return_publishable_result(self):
        with patch.object(c,'enrich_edits'),patch.object(c,'reconcile',side_effect=OSError('network')):
            with self.assertRaises(OSError):pub.collect_related(None,{'1':issue()},{},'repo','unused',NOW,False,{}, {},False)
    def test_latest_comment_id_ignores_edits_and_hidden_rows(self):
        a=comment(10);first,_=build_comments([a]);a['body']=json.dumps({**json.loads(a['body']),'body':'수정'});second,_=build_comments([a])
        self.assertEqual(first['threads'][0]['latest_comment_id'],second['threads'][0]['latest_comment_id'])
        replaced,_=build_comments([comment(11)]);self.assertEqual(replaced['threads'][0]['count'],first['threads'][0]['count'])
        self.assertGreater(replaced['threads'][0]['latest_comment_id'],first['threads'][0]['latest_comment_id'])
        from test_publisher import POLICY
        hidden,_=build_comments([comment(10),comment(11)],policy={**POLICY,'hidden_comment_ids':[11]})
        self.assertEqual(hidden['threads'][0]['latest_comment_id'],10)
