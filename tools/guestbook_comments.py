"""Validated, paged public comments. GitHub is the source; callers commit only after success."""
import datetime as dt
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import publish_guestbook as p

KIND = 'hunt-briefing-comment'
PAGE_SIZE = 50

def digest(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()

def enrich_edits(records, cached, token, kind="Issue"):
    """Issue.updated_at also changes for comments. Read actual content edit timestamps."""
    pending = []
    for key, item in records.items():
        old = cached.get(key)
        if item.get('body_truncated') or item.get('pull_request') is not None or item.get('body') == '{}':
            item['body_edited_at'] = None
            continue
        if old and old['body'] == item['body'] and 'body_edited_at' in old:
            item['body_edited_at'] = old['body_edited_at']
        elif item.get('node_id'):
            pending.append(item)
        else:
            # API records must supply a node id; old caches are refetched during migration.
            raise ValueError('Issue node id missing; run full reconciliation')
    for start in range(0, len(pending), 50):
        batch = pending[start:start+50]
        payload = {'query': 'query($ids:[ID!]!){nodes(ids:$ids){... on '+kind+'{id body lastEditedAt}}}',
                   'variables': {'ids': [i['node_id'] for i in batch]}}
        req = urllib.request.Request('https://api.github.com/graphql', data=json.dumps(payload).encode(), headers={
            'Authorization': 'Bearer '+token, 'Content-Type': 'application/json', 'User-Agent': 'HuntBriefing-Guestbook'})
        with urllib.request.urlopen(req, timeout=30) as res: raw = res.read(2*1024*1024+1)
        if len(raw)>2*1024*1024: raise ValueError('GraphQL result too large')
        doc=json.loads(raw)
        if doc.get('errors'): raise ValueError('Could not verify actual edit timestamps')
        nodes=doc['data']['nodes']
        if len(nodes)!=len(batch): raise ValueError('Incomplete edit timestamps')
        for item,node in zip(batch,nodes):
            # A racing edit cannot attach a timestamp to the wrong body snapshot.
            if not node or node['id']!=item['node_id']: raise ValueError('Issue changed during reconciliation')
            if item.get('body_truncated'):
                item['body_edited_at']=None
                continue
            if (node.get('body') or '')!=item['body']: raise ValueError('Issue changed during reconciliation')
            value=node['lastEditedAt']
            if value is not None: p.stamp(value)
            item['body_edited_at']=value

def compact(item, repository):
    match=re.fullmatch(re.escape('https://api.github.com/repos/'+repository+'/issues/')+r'([1-9][0-9]*)',item.get('issue_url',''))
    if not match or type(item.get('id')) is not int or item['id']<=0: raise ValueError('Invalid comment identity')
    uid=item['user']['id'];p.author_code(uid)
    p.stamp(item['created_at']);p.stamp(item['updated_at'])
    body=item.get('body') or ''
    if not isinstance(body,str) or len(body.encode())>8192: body='{}'
    return {'id':item['id'],'issue_number':int(match[1]),'user':{'id':uid,'type':item['user'].get('type','User')},
            **({'node_id':item['node_id']} if item.get('node_id') else {}),
            **({'body_edited_at':item['body_edited_at']} if 'body_edited_at' in item else {}),
            'body':body,'created_at':item['created_at'],'updated_at':item['updated_at'],'issue_url':item['issue_url']}

def reconcile(root, repository, token, now, force_full=False, event=None):
    folder=root/'state/comments'
    cached={}
    for path in folder.glob('*.json'):
        for value in json.loads(path.read_text())['comments']:
            item=compact(value,repository)
            if str(item['id']) in cached: raise ValueError('Duplicate cached comment')
            cached[str(item['id'])]=item
    path=root/'state/comments-sync.json'
    old=json.loads(path.read_text()) if path.exists() else {}
    full=force_full or any('node_id' not in x for x in cached.values()) or not old.get('last_full_at') or now-p.stamp(old['last_full_at'])>=dt.timedelta(days=7)
    query={'per_page':100,'sort':'updated','direction':'asc'}
    if not full: query['since']=p.iso(p.stamp(old['watermark'])-dt.timedelta(minutes=5))
    rows={} if full else dict(cached);downloaded={};page=1
    while True:
        batch=p.api_get(repository,token,'/comments?'+urllib.parse.urlencode({**query,'page':page}))
        if not isinstance(batch,list):raise ValueError('Invalid comment response')
        before=len(downloaded)
        for raw in batch:
            item=compact(raw,repository)
            if p.stamp(item['updated_at'])>now+dt.timedelta(minutes=5):raise ValueError('Future comment timestamp')
            downloaded[str(item['id'])]=item
        if len(batch)<100:break
        if len(downloaded)==before:raise ValueError('Comment pagination did not advance')
        page+=1
    rows.update(downloaded)
    missing=set(cached)-set(rows) if full else set()
    # Re-read the affected thread: queued events can merge several edits/deletions.
    number=(event or {}).get('issue',{}).get('number')
    if not full and type(number) is int and number>0 and (event or {}).get('comment'):
        current={};page=1
        while True:
            batch=p.api_get(repository,token,f'/{number}/comments?per_page=100&page={page}')
            if not isinstance(batch,list):raise ValueError('Invalid thread response')
            before=len(current)
            for raw in batch:
                item=compact(raw,repository)
                if item['issue_number']!=number:raise ValueError('Wrong comment thread')
                current[str(item['id'])]=item
            if len(batch)<100:break
            if before==len(current):raise ValueError('Thread pagination did not advance')
            page+=1
        missing.update(key for key,item in rows.items() if item['issue_number']==number and key not in current)
        rows.update(current)
    if event and event.get('action')=='deleted' and event.get('comment'):
        missing.add(str(event['comment']['id']))
    for key in missing:
        if not re.fullmatch(r'[1-9][0-9]*',key):raise ValueError('Invalid deleted comment id')
        try:item=compact(p.api_get(repository,token,'/comments/'+key),repository)
        except urllib.error.HTTPError as ex:
            if ex.code not in (404,410):raise
            rows.pop(key,None);continue
        rows[key]=item
    watermark=max([p.stamp(old['watermark']) if old.get('watermark') else now]+[min(p.stamp(i['updated_at']),now) for i in downloaded.values()])
    enrich_edits(rows,cached,token,'IssueComment')
    return rows,{'schema_version':'1.0','watermark':p.iso(watermark),'last_full_at':p.iso(now) if full else old['last_full_at']}

def parse(item,profiles,admins):
    data=json.loads(item['body'])
    required={'schema_version','kind','submission_id','nickname','profile_id','body'}
    if not isinstance(data,dict) or set(data)!=required or data['schema_version']!='1.0' or data['kind']!=KIND:
        raise ValueError('댓글 형식을 확인해 주세요.')
    if not isinstance(data['submission_id'],str) or not re.fullmatch('[0-9a-fA-F]{32}',data['submission_id']):raise ValueError('Invalid nonce')
    if item['user'].get('type')=='Bot':raise ValueError('Bot comment')
    profile=data['profile_id']
    if not isinstance(profile,str) or profile not in profiles or (profiles[profile]['admin_only'] and item['user']['id'] not in admins):raise ValueError('Invalid profile')
    return {**data,'submission_id':data['submission_id'].lower(),'nickname':p.clean(data['nickname'],2,16),'body':p.clean(data['body'],1,500,True)}

def build(feed,records,issues,policy,profiles,now):
    """No user paths/URLs. All public references are SHA-256 content addresses."""
    blobs={};heads=[];blocked=set(policy.get('blocked_author_ids',[]));hidden=set(policy.get('hidden_comment_ids',[]))
    def blob(value):
        raw=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
        if len(raw.encode())>4*1024*1024:raise ValueError('Comments document too large')
        revision=digest(raw);blobs[revision]=value
        return {'revision':revision,'size_bytes':len(raw.encode())}
    grouped={}
    for item in records.values():grouped.setdefault(item['issue_number'],[]).append(item)
    for entry in feed['entries']:
        number=entry['issue_number'];values=[];receipts=[];nonces=set()
        for raw in sorted(grouped.get(number,[]),key=lambda x:(p.stamp(x['created_at']),x['id'])):
            try:
                data=parse(raw,profiles,set(policy['administrator_ids']));uid=raw['user']['id']
                created,updated=p.stamp(raw['created_at']),p.stamp(raw['updated_at'])
                if created>now or updated<created:raise ValueError('Invalid timestamp')
                identity=(uid,data['submission_id'])
                if identity in nonces:continue
                nonces.add(identity)
                if uid in blocked or raw['id'] in hidden:
                    receipts.append({'comment_id':raw['id'],'author_id':uid,'submission_id':data['submission_id'],'status':'hidden'});continue
                values.append({'comment_id':raw['id'],'issue_number':number,'author_id':uid,'author_code':p.author_code(uid),
                    'nickname':data['nickname'],'profile_id':data['profile_id'],'body':data['body'],'submission_id':data['submission_id'],
                    'created_at':p.iso(created),'updated_at':raw.get('body_edited_at') or p.iso(created),'edited_at':raw.get('body_edited_at'),
                    'body_revision':digest(raw['body'])})
            except (ValueError,TypeError,KeyError):
                continue
        pages=[]
        for start in range(0,len(values),PAGE_SIZE):
            part=values[start:start+PAGE_SIZE]
            pages.append({**blob({'schema_version':'1.0','issue_number':number,'comments':part}),
                          'count':len(part),'first_id':part[0]['comment_id'],'last_id':part[-1]['comment_id'],'min_id':min(x['comment_id'] for x in part),'max_id':max(x['comment_id'] for x in part)})
        thread={'schema_version':'1.0','issue_number':number,'count':len(values),'pages':pages,'receipts':receipts[-200:]}
        heads.append({'issue_number':number,'count':len(values),'writable':not issues[str(number)].get('locked',False),**blob(thread)})
    return {'schema_version':'1.0','generated_at':p.iso(now),'threads':heads},blobs

def save(root,rows,sync,index,blobs):
    # Caller commits the entire worktree atomically; any failure leaves the published Git tree unchanged.
    target=root/'data/comments-index.json';old=json.loads(target.read_text()) if target.exists() else {}
    if old.get('threads')==index['threads']:index['generated_at']=old['generated_at']
    raw=json.dumps(index,ensure_ascii=False,indent=2)+'\n';revision=digest(raw)
    if len(raw.encode())>4*1024*1024:raise ValueError('Comments index too large')
    for key,value in blobs.items():p.write_json(root/'data/comments/blobs'/f'{key}.json',value)
    p.write_json(root/'data/comments/snapshots'/f'{revision}.json',index)
    p.write_json(target,index)
    p.write_json(root/'data/comments-version.json',{'schema_version':'1.0','revision':revision,'size_bytes':len(raw.encode()),'generated_at':index['generated_at']})
    snapshots=sorted((root/'data/comments/snapshots').glob('*.json'),key=lambda path:(p.stamp(json.loads(path.read_text())['generated_at']),path.name),reverse=True)
    keep=[root/'data/comments/snapshots'/f'{revision}.json']+[x for x in snapshots if x.stem!=revision][:7]
    used=set()
    for path in keep:
        for head in json.loads(path.read_text())['threads']:
            used.add(head['revision'])
            manifest=json.loads((root/'data/comments/blobs'/f"{head['revision']}.json").read_text())
            used.update(x['revision'] for x in manifest['pages'])
    for path in snapshots:
        if path not in keep:path.unlink()
    for path in (root/'data/comments/blobs').glob('*.json'):
        if path.stem not in used:path.unlink()
    grouped={}
    for item in rows.values():grouped.setdefault(str(item['issue_number']),[]).append(item)
    for number,items in grouped.items():p.write_json(root/'state/comments'/f'{number}.json',{'comments':sorted(items,key=lambda x:x['id'])})
    for path in (root/'state/comments').glob('*.json'):
        if path.stem not in grouped:path.unlink()
    p.write_json(root/'state/comments-sync.json',sync)
