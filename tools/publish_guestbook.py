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
import urllib.request

UTC = dt.timezone.utc
KST = dt.timezone(dt.timedelta(hours=9))
KIND = 'hunt-briefing-guestbook'
MAX_ISSUES = 5000
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

def api_issues(repository, token):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid repository')
    values = []
    for page in range(1, MAX_ISSUES // 100 + 2):
        url = f'https://api.github.com/repos/{repository}/issues?state=all&per_page=100&page={page}&sort=created&direction=asc'
        request = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                                                    'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'HuntBriefing-Guestbook-Publisher'})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('API response too large')
        batch = json.loads(raw)
        if not isinstance(batch, list):
            raise ValueError('API response is not a list')
        values.extend(batch)
        if len(values) > MAX_ISSUES:
            raise ValueError('Archive Issues before exceeding 5000; existing public data was not changed.')
        if len(batch) < 100:
            return values
    raise ValueError('Incomplete pagination; existing public data was not changed.')

def write_json(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(text, encoding='utf-8'); temp.replace(path)

def main():
    root = Path(__file__).resolve().parents[1]
    policy = json.loads((root / 'config/moderation.json').read_text(encoding='utf-8'))
    profiles = {p['id']: p for p in json.loads((root / 'config/profiles.json').read_text(encoding='utf-8'))['profiles']}
    state_path = root / 'data/publication-state.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'history': {}}
    issues = api_issues(os.environ['GITHUB_REPOSITORY'], os.environ['GH_TOKEN'])
    # A network failure aborts before writing: never reject good attachments because a feed is temporarily unavailable.
    catalog = load_briefing_catalog() if needs_briefing_catalog(issues) else {}
    feed, new_state = build_snapshot(issues, policy, profiles, state, dt.datetime.now(UTC), catalog)
    target = root / 'data/guestbook.json'
    old = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
    if old.get('entries') == feed['entries'] and old.get('receipts') == feed['receipts']:
        feed['generated_at'] = old.get('generated_at', feed['generated_at'])
    write_json(target, feed); write_json(state_path, new_state)
    print(f"Published {len(feed['entries'])} guestbook entries")

if __name__ == '__main__':
    main()
