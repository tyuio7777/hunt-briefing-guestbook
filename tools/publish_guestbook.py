#!/usr/bin/env python3
"""Read GitHub Issues as untrusted data, publish a validated read-only JSON snapshot.
No external packages, eval, shell interpolation, user-selected file paths or network destinations.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

UTC = dt.timezone.utc
KST = dt.timezone(dt.timedelta(hours=9))
KIND = 'hunt-briefing-guestbook'
FULL_RECONCILE_DAYS = 7
SNAPSHOT_LIMIT = 8
BRIEFING_ROOT = 'https://raw.githubusercontent.com/tyuio7777/hunt-briefing-feed/main/feed/'

def stamp(value):
    if not isinstance(value, str):
        raise ValueError('invalid timestamp')
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamp requires offset')
    return result.astimezone(UTC)

def iso(value):
    return value.astimezone(UTC).isoformat(timespec='seconds').replace('+00:00', 'Z')

def author_code(value):
    if type(value) is not int or value <= 0:
        raise ValueError('invalid identity')
    out = ''
    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    while value:
        value, digit = divmod(value, 36)
        out = alphabet[digit] + out
    return '#' + out.rjust(6, '0')

def clean(value, minimum, maximum, multiline=False):
    if not isinstance(value, str):
        raise ValueError('글과 별명을 확인해 주세요.')
    value = unicodedata.normalize('NFC', value.replace('\r\n', '\n').replace('\r', '\n')).strip()
    if not minimum <= len(value) <= maximum:
        raise ValueError('별명은 2~16자, 글은 2~500자로 입력해 주세요.')
    if any(unicodedata.category(ch) in ('Cf', 'Cs') or
           (unicodedata.category(ch) == 'Cc' and not (multiline and ch == '\n')) for ch in value):
        raise ValueError('표시할 수 없는 문자를 제거해 주세요.')
    return value

def valid_briefing_id(value):
    return isinstance(value, str) and len(value) <= 100 and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', value) is not None

def canonical_reference(issue):
    if not isinstance(issue, dict) or not valid_briefing_id(issue.get('id')):
        raise ValueError('Invalid operator briefing id')
    url = issue.get('html_url')
    if (not isinstance(url, str) or len(url) > 500 or not url.startswith(BRIEFING_ROOT) or
            not re.fullmatch(r'(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.html', url[len(BRIEFING_ROOT):])):
        raise ValueError('Invalid operator briefing URL')
    return {'issue_id': issue['id'], 'title': clean(issue.get('title'), 1, 300),
            'html_url': url, 'published_at': iso(stamp(issue['published_at']))}

def build_briefing_catalog(index, latest):
    if not isinstance(index, dict) or not isinstance(index.get('issues'), list) or not isinstance(latest, dict):
        raise ValueError('Invalid operator briefing catalog')
    catalog = {}
    for issue in index['issues'] + ([latest['issue']] if latest.get('issue') else []):
        reference = canonical_reference(issue)
        catalog[reference['issue_id']] = reference
    return catalog

def load_briefing_catalog():
    documents = []
    for filename in ('index.json', 'latest.json'):
        request = urllib.request.Request(BRIEFING_ROOT + filename, headers={
            'Accept': 'application/json', 'Cache-Control': 'no-cache', 'User-Agent': 'HuntBriefing-Guestbook-Publisher'})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError('Operator briefing catalog too large')
        documents.append(json.loads(raw))
    return build_briefing_catalog(*documents)

def needs_briefing_catalog(issues):
    for issue in issues:
        try:
            data = json.loads(issue.get('body') or '')
            if isinstance(data, dict) and valid_briefing_id(data.get('briefing_id')):
                return True
        except (ValueError, TypeError):
            pass
    return False

def resolve_reference(data, previous, catalog):
    old = (previous or {}).get('briefing_reference')
    # Missing in v41 means preserve; explicit null in v42 means detach.
    if 'briefing_id' not in data:
        reference = old
    elif data['briefing_id'] is None:
        return None
    else:
        reference = catalog.get(data['briefing_id'])
        if reference is None and old and old.get('issue_id') == data['briefing_id']:
            reference = old  # Keep historical references when the index is archived.
        if reference is None:
            raise ValueError('참조한 브리핑을 확인하지 못했습니다. 최신 목록에서 다시 선택해 주세요.')
    if reference is None:
        return None
    # Validate even persisted operator history before publishing it again.
    return canonical_reference({**reference, 'id': reference['issue_id']})

def parse_submission(issue, profiles, admins):
    body = issue.get('body') or ''
    if not isinstance(body, str) or len(body.encode('utf-8')) > 8192:
        raise ValueError('방명록 형식을 확인해 주세요.')
    data = json.loads(body)
    required = {'schema_version', 'kind', 'submission_id', 'nickname', 'profile_id', 'body'}
    if not isinstance(data, dict) or not required <= set(data) or set(data) - required - {'briefing_id'}:
        raise ValueError('방명록 형식을 확인해 주세요.')
    if data['schema_version'] != '1.0' or data['kind'] != KIND or not isinstance(data['submission_id'], str) or not re.fullmatch('[0-9a-fA-F]{32}', data['submission_id']):
        raise ValueError('방명록 등록 정보를 확인해 주세요.')
    if data.get('briefing_id') is not None and not valid_briefing_id(data['briefing_id']):
        raise ValueError('참조한 브리핑 정보를 확인해 주세요.')
    uid = issue['user']['id']  # NEVER trust an author id supplied in the Issue body.
    author_code(uid)
    profile = data['profile_id']
    if not isinstance(profile, str) or profile not in profiles or (profiles[profile]['admin_only'] and uid not in admins):
        raise ValueError('선택할 수 없는 프로필입니다.')
    return {**data, 'submission_id': data['submission_id'].lower(),
            'nickname': clean(data['nickname'], 2, 16), 'body': clean(data['body'], 2, 500, True)}

def build_snapshot(issues, policy, profiles, state, now, catalog=None):
    """Whole-repository reconciliation tolerates coalesced/cancelled pending workflow runs."""
    catalog = catalog or {}
    admins = set(policy['administrator_ids'])
    hidden = set(policy.get('hidden_issue_numbers', []))
    blocked = set(policy.get('blocked_author_ids', []))
    daily_limit = policy.get('daily_post_limit', 3)
    if not admins or not 1 <= daily_limit <= 20:
        raise ValueError('Invalid operator policy')
    history = dict(state.get('history', {}))
    entries, receipts = [], []
    days, nonces, bodies = {}, set(), set()
    ordered = sorted((i for i in issues if 'pull_request' not in i), key=lambda i: (stamp(i['created_at']), i['number']))
    for issue in ordered:
        number, uid = issue['number'], issue['user']['id']
        if type(number) is not int or number <= 0 or type(uid) is not int or uid <= 0:
            raise ValueError('Invalid GitHub identity')
        receipt = {'issue_number': number, 'author_id': uid, 'submission_id': '', 'status': 'rejected', 'reason': ''}
        try:
            raw = json.loads(issue.get('body') or '')
            if isinstance(raw, dict) and isinstance(raw.get('submission_id'), str) and re.fullmatch('[0-9a-fA-F]{32}', raw['submission_id']):
                receipt['submission_id'] = raw['submission_id'].lower()
            data = parse_submission(issue, profiles, admins)
            created, updated = stamp(issue['created_at']), stamp(issue['updated_at'])
            if updated < created or created > now:
                raise ValueError('글 작성 시간을 확인하지 못했습니다.')
            identity = (uid, data['submission_id'])
            if identity in nonces:
                raise ValueError('이미 처리한 방명록입니다.')
            nonces.add(identity)
            previous = history.get(str(number))
            # A submission id is immutable once first accepted; changing it cannot manufacture a new quest event.
            if previous and (previous['author_id'] != uid or previous['submission_id'] != data['submission_id']):
                raise ValueError('기존 글의 등록 정보는 변경할 수 없습니다.')
            reference = resolve_reference(data, previous, catalog)
            day_key = (uid, created.astimezone(KST).date().isoformat())
            body_key = (day_key, hashlib.sha256(' '.join(data['body'].split()).casefold().encode()).hexdigest())
            if not previous and days.get(day_key, 0) >= daily_limit:
                raise ValueError('오늘 남길 수 있는 방명록 수를 초과했습니다.')
            if body_key in bodies:
                raise ValueError('같은 내용의 방명록이 이미 있습니다.')
            # Accepted posts keep their first publication time through edits, closures and moderation.
            if not previous:
                previous = {'author_id': uid, 'submission_id': data['submission_id'], 'first_published_at': iso(now), 'created_at': iso(created)}
            previous = dict(previous)
            previous['briefing_reference'] = reference
            if uid in blocked or number in hidden:
                receipt.update(status='hidden', reason='운영 기준에 따라 숨김 처리된 글입니다.')
            elif issue.get('state') != 'open':
                receipt.update(status='closed', reason='닫힌 방명록입니다.')
            else:
                history[str(number)] = previous
                entries.append({'issue_number': number, 'author_id': uid, 'author_code': author_code(uid),
                                'nickname': data['nickname'], 'profile_id': data['profile_id'], 'body': data['body'],
                                'submission_id': data['submission_id'], 'created_at': iso(created), 'updated_at': iso(updated),
                                'first_published_at': previous['first_published_at'], 'briefing_reference': reference})
                receipt.update(status='published', reason='')
            days[day_key] = days.get(day_key, 0) + 1
            bodies.add(body_key)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            # Show controlled local validation messages, never arbitrary GitHub input or stack traces.
            try:
                parse_submission(issue, profiles, admins)
            except (ValueError, TypeError, KeyError) as error:
                safe = str(error)
                receipt['reason'] = safe if any('\uac00' <= ch <= '\ud7a3' for ch in safe) and len(safe) <= 200 else '방명록 형식을 확인해 주세요.'
            else:
                receipt['reason'] = '중복 등록, 작성 한도 또는 변경된 등록 정보를 확인해 주세요.'
        if receipt['submission_id']:
            receipts.append(receipt)
    entries.sort(key=lambda e: (e['created_at'], e['issue_number']), reverse=True)
    receipts.sort(key=lambda e: e['issue_number'], reverse=True)
    return {'schema_version': '1.0', 'generated_at': iso(now), 'entries': entries[:500], 'receipts': receipts[:2000]}, {'schema_version': '1.0', 'history': history}

def api_get(repository, token, suffix):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid repository')
    url = f'https://api.github.com/repos/{repository}/issues{suffix}'
    request = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                                                'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'HuntBriefing-Guestbook-Publisher'})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError('API response too large')
    return json.loads(raw)

def api_issues(repository, token, since=None):
    # The repository issue endpoint has no search API's 1,000-result cap.
    # Never truncate a successful feed at a fixed repository-wide issue count.
    values, page = {}, 1
    while True:
        query = {'state': 'all', 'per_page': 100, 'page': page, 'sort': 'created', 'direction': 'asc'}
        if since is not None:
            query['since'] = iso(since)
        batch = api_get(repository, token, '?' + urllib.parse.urlencode(query))
        if not isinstance(batch, list):
            raise ValueError('API response is not a list')
        before = len(values)
        for item in batch:
            if not isinstance(item, dict) or type(item.get('number')) is not int or item['number'] <= 0:
                raise ValueError('Invalid API issue')
            values[item['number']] = item
        if len(batch) < 100:
            return list(values.values())
        if len(values) == before:
            raise ValueError('Pagination did not advance; public data was not changed')
        page += 1

def compact_issue(item):
    """Cache only fields required for validation, no profiles/comments/HTML payloads."""
    number, uid = item['number'], item['user']['id']
    if type(number) is not int or number <= 0 or type(uid) is not int or uid <= 0:
        raise ValueError('Invalid GitHub identity')
    stamp(item['created_at']); stamp(item['updated_at'])
    body = item.get('body') or ''
    if not isinstance(body, str) or len(body.encode('utf-8')) > 8192:
        try:
            raw = json.loads(body)
            nonce = raw.get('submission_id') if isinstance(raw, dict) else None
            body = json.dumps({'submission_id': nonce}) if isinstance(nonce, str) and re.fullmatch('[0-9a-fA-F]{32}', nonce) else '{}'
        except (ValueError, TypeError):
            body = '{}'
    return {'number': number, 'user': {'id': uid}, 'body': body, 'created_at': item['created_at'],
            'updated_at': item['updated_at'], 'state': item['state']}

def load_issue_cache(root):
    result = {}
    for path in sorted((root / 'state/issues').glob('*.json')):
        doc = json.loads(path.read_text(encoding='utf-8'))
        for key, item in doc['issues'].items():
            if key != str(item['number']) or key in result:
                raise ValueError('Invalid cached issue identity')
            result[key] = compact_issue(item)
    return result

def reconcile_issues(root, repository, token, now, force_full=False):
    """Read everything before writing. An incomplete API read cannot remove old posts."""
    sync_path = root / 'state/sync.json'
    old = json.loads(sync_path.read_text()) if sync_path.exists() else {}
    cached = load_issue_cache(root)
    full = (force_full or not old.get('last_full_at') or old.get('issue_count') != len(cached)
            or now - stamp(old['last_full_at']) >= dt.timedelta(days=FULL_RECONCILE_DAYS))
    since = None if full else stamp(old['watermark']) - dt.timedelta(minutes=5)
    downloaded = api_issues(repository, token, since)
    records = {} if full else dict(cached)
    for item in downloaded:
        if 'pull_request' not in item:
            value = compact_issue(item)
            if stamp(value['updated_at']) > now + dt.timedelta(minutes=5):
                raise ValueError('Future API watermark')
            records[str(value['number'])] = value
    if full:
        # Pagination may shift during deletions. Confirm absence individually before removing a cached row.
        for key in cached.keys() - records.keys():
            try:
                item = api_get(repository, token, '/' + key)
            except urllib.error.HTTPError as error:
                if error.code not in (404, 410): raise
                continue
            if item.get('repository_url', f'https://api.github.com/repos/{repository}') != f'https://api.github.com/repos/{repository}':
                continue  # transferred out of this repository
            if 'pull_request' not in item:
                records[key] = compact_issue(item)
    watermark = max([stamp(old['watermark']) if old.get('watermark') else now]
                    + [min(stamp(i['updated_at']), now) for i in downloaded])
    sync = {'schema_version': '1.0', 'watermark': iso(watermark), 'last_full_at': iso(now) if full else old['last_full_at'],
            'issue_count': len(records)}
    return records, sync, full

def save_issue_cache(root, records, sync):
    buckets = {}
    for key, value in records.items():
        bucket = f'{int(key) // 1000:08d}.json'
        buckets.setdefault(bucket, {})[key] = value
    folder = root / 'state/issues'
    for bucket, rows in buckets.items():
        write_json(folder / bucket, {'schema_version': '1.0', 'issues': dict(sorted(rows.items(), key=lambda x: int(x[0])))})
    for path in folder.glob('*.json'):
        if path.name not in buckets: path.unlink()
    write_json(root / 'state/sync.json', sync)

def publish_version(root, feed):
    # The content address lets clients detect a change with a tiny anonymous read.
    text = json.dumps(feed, ensure_ascii=False, indent=2) + '\n'
    data = text.encode('utf-8')
    if len(data) > 4 * 1024 * 1024:
        raise ValueError('Public snapshot exceeds the app limit')
    revision = hashlib.sha256(data).hexdigest()
    folder = root / 'data/snapshots'
    write_json(folder / (revision + '.json'), feed)
    write_json(root / 'data/guestbook.json', feed)  # v41-v44 remain compatible
    write_json(root / 'data/guestbook-version.json', {'schema_version': '1.0', 'revision': revision,
        'size_bytes': len(data), 'generated_at': feed['generated_at']})
    snapshots = sorted(folder.glob('*.json'),
        key=lambda p: (stamp(json.loads(p.read_text(encoding='utf-8'))['generated_at']), p.name), reverse=True)
    previous = [p for p in snapshots if p.name != revision + '.json'][:SNAPSHOT_LIMIT - 1]
    keep = {revision + '.json'} | {p.name for p in previous}
    for path in snapshots:
        if path.name not in keep: path.unlink()

def storage_status(root, records, history):
    size = sum(p.stat().st_size for folder in ('data', 'state') for p in (root / folder).rglob('*')
               if p.is_file() and p.name != 'storage-status.json')
    warnings = []
    if len(records) >= 20000: warnings.append('Issue cache has at least 20000 records; review publication duration.')
    if size >= 100 * 1024 * 1024: warnings.append('Generated working files exceed 100 MiB; review storage.')
    for warning in warnings: print('::warning::' + warning)
    write_json(root / 'data/storage-status.json', {'schema_version': '1.0', 'cached_issues': len(records),
        'publication_history': len(history), 'generated_bytes': size, 'warnings': warnings})

def write_json(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding='utf-8') == text: return
    temp = path.with_suffix('.tmp')
    temp.write_text(text, encoding='utf-8'); temp.replace(path)

def main():
    root = Path(__file__).resolve().parents[1]
    policy = json.loads((root / 'config/moderation.json').read_text(encoding='utf-8'))
    profiles = {p['id']: p for p in json.loads((root / 'config/profiles.json').read_text(encoding='utf-8'))['profiles']}
    state_path = root / 'data/publication-state.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'history': {}}
    now = dt.datetime.now(UTC)
    event = {}
    if os.environ.get('GITHUB_EVENT_PATH'):
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
    records, sync, full = reconcile_issues(root, os.environ['GITHUB_REPOSITORY'], os.environ['GH_TOKEN'], now,
        force_full=event.get('action') in ('deleted', 'transferred') or os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch')
    issues = list(records.values())
    # A network failure aborts before writing: never reject good attachments because a feed is temporarily unavailable.
    catalog = load_briefing_catalog() if needs_briefing_catalog(issues) else {}
    feed, new_state = build_snapshot(issues, policy, profiles, state, now, catalog)
    target = root / 'data/guestbook.json'
    old = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
    if old.get('entries') == feed['entries'] and old.get('receipts') == feed['receipts']:
        feed['generated_at'] = old.get('generated_at', feed['generated_at'])
    publish_version(root, feed)
    write_json(state_path, new_state)
    save_issue_cache(root, records, sync)
    storage_status(root, records, new_state['history'])
    print(f"Published {len(feed['entries'])} guestbook entries; mode={'full' if full else 'incremental'}; cached={len(records)}")

if __name__ == '__main__':
    main()
