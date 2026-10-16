import copy
import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
from test_publisher import issue, build as posts, POLICY, PROFILES, NOW, path as publisher_path

sys.path.insert(0, str(publisher_path.parent))
import guestbook_comments as c
REPO = 'tyuio7777/hunt-briefing-guestbook'

def comment(cid=1, number=1, uid=7, **changes):
    data = {'schema_version':'1.0','kind':c.KIND,'submission_id':f'{cid:032x}', 'nickname':'방문자','profile_id':'rabbit','body':f'댓글 {cid}'}
    data.update(changes)
    return {'id':cid,'node_id':f'IC_{cid}','issue_number':number,'user':{'id':uid,'type':'User'},'body':json.dumps(data),
            'created_at':'2026-10-16T00:10:00Z','updated_at':'2026-10-16T00:10:00Z','body_edited_at':None,
            'issue_url':f'https://api.github.com/repos/{REPO}/issues/{number}'}

def build(rows, parents=None, policy=None, now=NOW):
    parents=parents or [issue()]
    feed,_=posts(parents,policy=policy)
    return c.build(feed,{str(r['id']):r for r in rows},{str(i['number']):i for i in parents},policy or POLICY,PROFILES,now)

def thread(index,blobs,n=0):return blobs[index['threads'][n]['revision']]
def values(index,blobs,n=0):return [r for ref in thread(index,blobs,n)['pages'] for r in blobs[ref['revision']]['comments']]

class CommentPublisherTests(unittest.TestCase):
    def test_normal_one_character_and_identity(self):
        index,blobs=build([comment(body='안')]);v=values(index,blobs)[0]
        self.assertEqual(v['author_code'],'#000007');self.assertEqual(v['body'],'안');self.assertIsNone(v['edited_at'])
    def test_parent_and_comment_edits_are_independent(self):
        parent=issue();parent['updated_at']='2026-10-16T03:00:00Z'
        feed,_=posts([parent]);self.assertIsNone(feed['entries'][0]['edited_at']);self.assertEqual(feed['entries'][0]['updated_at'],parent['created_at'])
        item=comment();item['updated_at']='2026-10-16T03:00:00Z';item['body_edited_at']=item['updated_at']
        index,blobs=build([item]);self.assertEqual(values(index,blobs)[0]['edited_at'],item['updated_at'])
        parent['body_edited_at']='2026-10-16T02:00:00Z';feed,_=posts([parent]);self.assertEqual(feed['entries'][0]['edited_at'],parent['body_edited_at'])
    def test_comment_other_metadata_is_not_an_edit(self):
        item=comment();item['updated_at']='2026-10-16T03:00:00Z';index,blobs=build([item]);v=values(index,blobs)[0]
        self.assertIsNone(v['edited_at']);self.assertEqual(v['updated_at'],v['created_at'])
    def test_threads_are_isolated(self):
        index,blobs=build([comment(1,1),comment(2,2)], [issue(1),issue(2)])
        for n,head in enumerate(index['threads']):self.assertEqual([x['issue_number'] for x in values(index,blobs,n)],[head['issue_number']])
    def test_order_and_page_boundary(self):
        index,blobs=build([comment(i) for i in range(121,0,-1)]);t=thread(index,blobs)
        self.assertEqual([p['count'] for p in t['pages']],[50,50,21]);self.assertEqual([x['comment_id'] for x in values(index,blobs)],list(range(1,122)))
        for ref in t['pages']:
            raw=json.dumps(blobs[ref['revision']],ensure_ascii=False,indent=2)+'\n'
            self.assertEqual(c.digest(raw),ref['revision']);self.assertEqual(len(raw.encode()),ref['size_bytes'])
    def test_non_monotonic_created_order_has_safe_id_ranges(self):
        a,b=comment(100),comment(1);a['created_at']=a['updated_at']='2026-10-16T00:01:00Z'
        index,blobs=build([a,b]);ref=thread(index,blobs)['pages'][0]
        self.assertEqual((ref['min_id'],ref['max_id']),(1,100));self.assertEqual((ref['first_id'],ref['last_id']),(100,1))
    def test_forged_author_admin_avatar_and_control_rejected(self):
        for kwargs in ({'author_id':20161415},{'profile_id':'admin_crowned_computer'},{'body':'\u202e위장'},{'nickname':'한\n글'}):
            self.assertEqual(build([comment(**kwargs)])[0]['threads'][0]['count'],0)
    def test_plain_bot_and_invalid_lengths_not_counted(self):
        items=[comment(1,body=''),comment(2,body='가'*501),comment(3)]
        items[-1]['body']='일반 GitHub 댓글';bot=comment(4);bot['user']['type']='Bot';items.append(bot)
        self.assertEqual(build(items)[0]['threads'][0]['count'],0)
    def test_duplicate_nonce_same_author_parent_only(self):
        items=[comment(1),comment(2,submission_id=f'{1:032x}'),comment(3,uid=8,submission_id=f'{1:032x}'),comment(4,2,submission_id=f'{1:032x}')]
        index,blobs=build(items,[issue(1),issue(2)])
        self.assertEqual(sum(x['count'] for x in index['threads']),3)
    def test_hidden_blocked_and_closed_parent(self):
        policy={**POLICY,'hidden_comment_ids':[1],'blocked_author_ids':[8]}
        index,blobs=build([comment(1),comment(2,uid=8),comment(3)],policy=policy)
        self.assertEqual(index['threads'][0]['count'],1);self.assertEqual(len(thread(index,blobs)['receipts']),2)
        parent=issue();parent['state']='closed';self.assertEqual(build([comment()],parents=[parent])[0]['threads'],[])
    def test_locked_parent_readable_not_writable(self):
        parent=issue();parent['locked']=True;index,blobs=build([comment()],parents=[parent])
        self.assertFalse(index['threads'][0]['writable']);self.assertEqual(index['threads'][0]['count'],1)
    def test_wrong_repository_invalid_ids(self):
        item=comment();item['issue_url']='https://api.github.com/repos/evil/other/issues/1'
        with self.assertRaises(ValueError):c.compact(item,REPO)
    def test_deleted_comment_removed_without_touching_parent(self):
        one,_=build([comment()]);zero,_=build([])
        self.assertEqual(one['threads'][0]['count'],1);self.assertEqual(zero['threads'][0]['count'],0)
    def test_eight_snapshots_and_referenced_blobs_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for i in range(14):
                index,blobs=build([comment(body=f'변경 {i}')],now=NOW+dt.timedelta(minutes=i))
                c.save(root,{}, {}, index,blobs)
            self.assertEqual(len(list((root/'data/comments/snapshots').glob('*.json'))),8)
            self.assertEqual(len(list((root/'data/comments/blobs').glob('*.json'))),16)
            ver=json.loads((root/'data/comments-version.json').read_text());raw=(root/'data/comments-index.json').read_text()
            self.assertEqual(ver['revision'],c.digest(raw));self.assertEqual(ver['size_bytes'],len(raw.encode()))
    def test_unchanged_does_not_republish(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);index,blobs=build([comment()]);c.save(root,{}, {},index,blobs)
            before=(root/'data/comments-version.json').read_bytes()
            index,blobs=build([comment()],now=NOW+dt.timedelta(hours=1));c.save(root,{}, {},index,blobs)
            self.assertEqual((root/'data/comments-version.json').read_bytes(),before)

class EditTimestampTests(unittest.TestCase):
    def test_unchanged_body_reuses_actual_stamp(self):
        old=comment();new=comment();new['updated_at']='2026-10-16T03:00:00Z'
        with patch.object(c.urllib.request,'urlopen',side_effect=AssertionError('unnecessary request')):
            c.enrich_edits({'1':new},{'1':old},'unused','IssueComment')
        self.assertIsNone(new['body_edited_at'])
    def test_actual_timestamp_and_racing_body(self):
        item=comment();item.pop('body_edited_at');node={'id':item['node_id'],'body':item['body'],'lastEditedAt':'2026-10-16T01:00:00Z'}
        with patch.object(c.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps({'data':{'nodes':[node]}}).encode())):
            c.enrich_edits({'1':item},{},'unused','IssueComment')
        self.assertEqual(item['body_edited_at'],node['lastEditedAt']);node['body']='racing edit'
        with patch.object(c.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps({'data':{'nodes':[node]}}).encode())):
            with self.assertRaises(ValueError):c.enrich_edits({'1':item},{},'unused','IssueComment')
    def test_graphql_error_aborts(self):
        with patch.object(c.urllib.request,'urlopen',return_value=io.BytesIO(b'{"errors":[{"message":"unavailable"}]}')):
            with self.assertRaises(ValueError):c.enrich_edits({'1':comment()},{},'unused','IssueComment')
    def test_invalid_large_body_not_downloaded_again(self):
        item=comment();item['body']='{}'
        with patch.object(c.urllib.request,'urlopen',side_effect=AssertionError('bad body')):
            c.enrich_edits({'1':item},{},'unused','IssueComment')

class CommentReconcileTests(unittest.TestCase):
    def seed(self,root):
        c.p.write_json(root/'state/comments/1.json',{'comments':[comment()]})
        c.p.write_json(root/'state/comments-sync.json',{'watermark':c.p.iso(NOW),'last_full_at':c.p.iso(NOW)})
    def test_incremental_overlap_keeps_existing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.seed(root)
            with patch.object(c.p,'api_get',return_value=[]) as get:
                rows,sync=c.reconcile(root,REPO,'unused',NOW+dt.timedelta(hours=1))
            self.assertEqual(len(rows),1);self.assertIn('since=',get.call_args.args[2])
    def test_weekly_missing_is_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.seed(root)
            def get(repo,token,url):
                if url=='/comments/1':raise urllib.error.HTTPError(url,404,'deleted',{},None)
                return []
            with patch.object(c.p,'api_get',side_effect=get):rows,sync=c.reconcile(root,REPO,'unused',NOW+dt.timedelta(days=8))
            self.assertEqual(rows,{})
    def test_deleted_event_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.seed(root)
            def get(repo,token,url):
                if url=='/comments/1':raise urllib.error.HTTPError(url,410,'deleted',{},None)
                return []
            with patch.object(c.p,'api_get',side_effect=get):rows,_=c.reconcile(root,REPO,'unused',NOW,event={'action':'deleted','comment':{'id':1}})
            self.assertEqual(rows,{})
    def test_affected_thread_reconciles_coalesced_deletions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.seed(root)
            c.p.write_json(root/'state/comments/1.json',{'comments':[comment(1),comment(2),comment(3)]})
            def get(repo,token,url):
                if url.startswith('/1/comments?'):return [comment(3)]
                if url in ('/comments/1','/comments/2'):raise urllib.error.HTTPError(url,404,'deleted',{},None)
                return []
            with patch.object(c.p,'api_get',side_effect=get):
                rows,_=c.reconcile(root,REPO,'unused',NOW,event={'action':'deleted','issue':{'number':1},'comment':{'id':2}})
            self.assertEqual(set(rows),{'3'})
    def test_failed_confirmation_preserves_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.seed(root);before=(root/'state/comments/1.json').read_bytes()
            with patch.object(c.p,'api_get',side_effect=TimeoutError()):
                with self.assertRaises(TimeoutError):c.reconcile(root,REPO,'unused',NOW)
            self.assertEqual((root/'state/comments/1.json').read_bytes(),before)
    def test_repeated_page_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(c.p,'api_get',return_value=[comment(i) for i in range(1,101)]):
                with self.assertRaises(ValueError):c.reconcile(Path(folder),REPO,'unused',NOW)

if __name__=='__main__':unittest.main()
