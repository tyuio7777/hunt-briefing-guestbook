import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'tools/publish_guestbook.py'
spec = importlib.util.spec_from_file_location('publisher', path)
pub = importlib.util.module_from_spec(spec); spec.loader.exec_module(pub)
POLICY = {'administrator_ids': [20161415], 'hidden_issue_numbers': [], 'blocked_author_ids': [], 'daily_post_limit': 3}
PROFILES = {p['id']: p for p in json.loads((path.parents[1] / 'config/profiles.json').read_text())['profiles']}
NOW = pub.stamp('2026-10-16T04:00:00Z')

def issue(number=1, uid=7, text=None, **changes):
    body = {'schema_version': '1.0', 'kind': pub.KIND, 'submission_id': f'{number:032x}', 'nickname': '방문자', 'profile_id': 'rabbit', 'body': text or f'반갑습니다 {number}'}
    body.update(changes)
    return {'number': number, 'user': {'id': uid}, 'body': json.dumps(body), 'created_at': '2026-10-16T00:00:00Z', 'updated_at': '2026-10-16T00:00:00Z', 'state': 'open'}

def build(items, state=None, policy=None, now=NOW, catalog=None):
    return pub.build_snapshot(items, policy or POLICY, PROFILES, state or {'history': {}}, now, catalog)

class PublisherTests(unittest.TestCase):
    def test_normal(self):
        feed, state = build([issue()]); self.assertEqual(len(feed['entries']), 1); self.assertEqual(feed['entries'][0]['author_code'], '#000007')
    def test_admin_restriction(self):
        self.assertEqual(build([issue(profile_id='admin_crowned_computer')])[0]['entries'], [])
        self.assertEqual(len(build([issue(uid=20161415, profile_id='admin_crowned_computer')])[0]['entries']), 1)
    def test_forged_identity(self):
        self.assertEqual(build([issue(author_id=20161415)])[0]['entries'], [])
    def test_profile_path_rejected(self):
        self.assertEqual(build([issue(profile_id='../../admin')])[0]['entries'], [])
    def test_script_remains_plain_data(self):
        text = "<script>alert(1)</script> $(touch /tmp/PWN) `whoami` ${{ secrets.TOKEN }}"
        self.assertEqual(build([issue(text=text)])[0]['entries'][0]['body'], text)
    def test_lengths_and_unicode(self):
        self.assertEqual(len(build([issue(text='한' * 500)])[0]['entries']), 1)
        self.assertEqual(build([issue(text='한' * 501)])[0]['entries'], [])
        self.assertEqual(build([issue(nickname='x\n관리자')])[0]['entries'], [])
        self.assertEqual(build([issue(text='반갑\u202e습니다')])[0]['entries'], [])
    def test_empty_and_null(self):
        for value in ['', None, 4]: self.assertEqual(build([issue(body=value)])[0]['entries'], [])
    def test_duplicate_nonce(self):
        feed, _ = build([issue(), issue(2, submission_id=f'{1:032x}')]); self.assertEqual(len(feed['entries']), 1)
    def test_duplicate_text(self):
        feed, _ = build([issue(text='동일  내용'), issue(2, text='동일 내용')]); self.assertEqual(len(feed['entries']), 1)
    def test_daily_limit(self):
        feed, _ = build([issue(i) for i in range(1, 5)]); self.assertEqual(len(feed['entries']), 3)
    def test_korea_day_boundary(self):
        items = [issue(i) for i in range(1, 5)]
        for item in items[:3]: item['created_at'] = item['updated_at'] = '2026-10-15T14:59:59Z'
        items[3]['created_at'] = items[3]['updated_at'] = '2026-10-15T15:00:00Z'
        self.assertEqual(len(build(items)[0]['entries']), 4)
    def test_edit_preserves_first_publication(self):
        first, state = build([issue()]); item = issue(text='바뀐 내용');item['updated_at'] = '2026-10-16T04:30:00Z'
        second, _ = build([item], state, now=NOW+dt.timedelta(hours=1))
        self.assertEqual(first['entries'][0]['first_published_at'], second['entries'][0]['first_published_at'])
    def test_submission_id_immutable(self):
        _, state = build([issue()]); self.assertEqual(build([issue(submission_id='a'*32)], state)[0]['entries'], [])
    def test_hidden_survives_author_edit_reopen(self):
        _, state = build([issue()]); policy = {**POLICY, 'hidden_issue_numbers': [1]}
        updated = issue(text='수정해서 복원 시도'); feed, state = build([updated], state, policy)
        self.assertEqual(feed['entries'], []); self.assertEqual(feed['receipts'][0]['status'], 'hidden')
        restored, _ = build([updated], state, POLICY); self.assertEqual(len(restored['entries']), 1)
    def test_blocked_author(self):
        self.assertEqual(build([issue()], policy={**POLICY, 'blocked_author_ids':[7]})[0]['entries'], [])
    def test_closed_deleted(self):
        item = issue();item['state']='closed'; self.assertEqual(build([item])[0]['receipts'][0]['status'], 'closed')
        self.assertEqual(build([])[0]['entries'], [])
    def test_rebuild_recovers_coalesced_events(self):
        _, state = build([issue()]);feed, _ = build([issue(), issue(2), issue(3)], state)
        self.assertEqual({e['issue_number'] for e in feed['entries']}, {1,2,3})
    def test_pull_requests_excluded(self):
        item=issue();item['pull_request']={};self.assertEqual(build([item])[0]['entries'], [])
    def test_null_and_malformed_issues(self):
        item=issue();item['body']='{"broken"';self.assertEqual(build([item])[0]['entries'], [])
    def test_fixed_id_code_unique(self):
        self.assertEqual(len({pub.author_code(i) for i in range(1,10000)}),9999)

BRIEFING = {'id': '2026-10-12', 'title': '공식 4건 · 커뮤니티 7건', 'published_at': '2026-10-12T09:00:00+09:00',
            'html_url': pub.BRIEFING_ROOT + '2026/10/2026-10-12.html'}
CATALOG = pub.build_briefing_catalog({'issues': [BRIEFING]}, {'issue': None})

class BriefingReferenceTests(unittest.TestCase):
    def test_attached_uses_operator_title_url(self):
        feed, _ = build([issue(briefing_id=BRIEFING['id'])], catalog=CATALOG)
        self.assertEqual(feed['entries'][0]['briefing_reference'], CATALOG[BRIEFING['id']])
    def test_unknown_briefing_rejected(self):
        feed, _ = build([issue(briefing_id='missing')], catalog=CATALOG)
        self.assertEqual(feed['entries'], []); self.assertEqual(feed['receipts'][0]['status'], 'rejected')
    def test_null_and_legacy_new_posts(self):
        for item in [issue(), issue(briefing_id=None)]:
            self.assertIsNone(build([item])[0]['entries'][0]['briefing_reference'])
    def test_invalid_id_types(self):
        for value in ['', 1, [], {}, '../x', 'https://evil', 'a'*101]:
            self.assertEqual(build([issue(briefing_id=value)])[0]['entries'], [])
    def test_forged_title_url_fields_rejected(self):
        for key in ['briefing_title', 'briefing_url', 'briefing_reference']:
            self.assertEqual(build([issue(briefing_id=BRIEFING['id'], **{key: 'https://evil'})], catalog=CATALOG)[0]['entries'], [])
    def test_v41_edit_preserves_attachment_and_first_publication(self):
        first, state = build([issue(briefing_id=BRIEFING['id'])], catalog=CATALOG)
        second, _ = build([issue(text='구버전에서 수정')], state=state, now=NOW+dt.timedelta(days=1))
        for key in ['briefing_reference', 'first_published_at']:
            self.assertEqual(first['entries'][0][key], second['entries'][0][key])
    def test_detach_explicit_null_is_durable(self):
        _, state = build([issue(briefing_id=BRIEFING['id'])], catalog=CATALOG)
        before=copy.deepcopy(state)
        feed, detached = build([issue(briefing_id=None)], state=state)
        self.assertIsNone(feed['entries'][0]['briefing_reference'])
        self.assertEqual(state,before) # no mutation of caller's persisted input
        self.assertIsNone(build([issue()], state=detached)[0]['entries'][0]['briefing_reference'])
    def test_archived_index_preserves_existing_id(self):
        _, state = build([issue(briefing_id=BRIEFING['id'])], catalog=CATALOG)
        feed, _ = build([issue(briefing_id=BRIEFING['id'])], state=state)
        self.assertEqual(feed['entries'][0]['briefing_reference'], CATALOG[BRIEFING['id']])
    def test_changed_id_needs_catalog(self):
        _, state = build([issue(briefing_id=BRIEFING['id'])], catalog=CATALOG)
        self.assertEqual(build([issue(briefing_id='other')],state=state)[0]['entries'], [])
    def test_latest_catalog_also_supported(self):
        catalog=pub.build_briefing_catalog({'issues': []},{'issue':BRIEFING})
        self.assertEqual(catalog,CATALOG)
    def test_unsafe_operator_urls_abort_catalog(self):
        for url in ['https://evil/x.html', pub.BRIEFING_ROOT+'../x.html', pub.BRIEFING_ROOT+'%2e%2e/x.html',
                    BRIEFING['html_url']+'?x=1', BRIEFING['html_url']+'#x', BRIEFING['html_url']+'\n']:
            with self.assertRaises(ValueError): pub.build_briefing_catalog({'issues':[{**BRIEFING,'html_url':url}]},{})
    def test_forged_history_url_rejected(self):
        _, state = build([issue(briefing_id=BRIEFING['id'])], catalog=CATALOG)
        state['history']['1']['briefing_reference']['html_url']='https://evil/x.html'
        self.assertEqual(build([issue()],state=state)[0]['entries'], [])
    def test_legacy_posts_need_no_catalog_network(self):
        self.assertFalse(pub.needs_briefing_catalog([issue(),issue(briefing_id=None)]))
        self.assertTrue(pub.needs_briefing_catalog([issue(briefing_id=BRIEFING['id'])]))

if __name__ == '__main__': unittest.main(verbosity=2)
