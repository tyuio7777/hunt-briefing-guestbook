import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = 'https://api.github.com/repos/tyuio7777/hunt-briefing-guestbook/issues';

function expirationTime(value) {
  const utc = Date.parse(value);
  if (!Number.isFinite(utc)) return Infinity;
  const local = new Date(utc + 9 * 3600000);
  const day = local.getUTCDate();
  local.setUTCDate(1);
  local.setUTCMonth(local.getUTCMonth() + 6);
  const lastDay = new Date(Date.UTC(local.getUTCFullYear(), local.getUTCMonth() + 1, 0)).getUTCDate();
  local.setUTCDate(Math.min(day, lastDay));
  return local.getTime() - 9 * 3600000;
}

export function shouldExpire(issue, now = Date.now()) {
  if (issue.pull_request || !/^Hunt 공유 일정 · [a-f0-9]{32}$/.test(issue.title) || typeof issue.body !== 'string') return false;
  let data;
  try { data = JSON.parse(issue.body); } catch { return false; }
  if (data?.kind !== 'hunt-shared-schedule-v1' || issue.title !== 'Hunt 공유 일정 · ' + data.item?.id) return false;
  return Math.min(expirationTime(issue.created_at), expirationTime(data.item.createdAt)) <= now;
}

async function api(url, patch) {
  const headers = { Authorization: 'Bearer ' + process.env.GITHUB_TOKEN, Accept: 'application/vnd.github+json',
    'User-Agent': 'Hunt-Schedule-Retention', 'Content-Type': 'application/json' };
  const response = await fetch(url, { headers, method: patch ? 'PATCH' : 'GET',
    body: patch ? JSON.stringify(patch) : undefined, redirect: 'error', signal: AbortSignal.timeout(30000) });
  if (!response.ok) throw Error('Issue retention request failed (' + response.status + ')');
  return response.json();
}

async function expire() {
  for (let page = 1; ; page++) {
    const list = await api(root + '?state=all&sort=created&direction=asc&per_page=100&page=' + page);
    for (const issue of list) {
      if (shouldExpire(issue)) await api(root + '/' + issue.number,
        { state: 'closed', body: '등록 후 6개월이 지나 공유 일정 암호문을 정리했습니다.' });
    }
    if (list.length < 100) return;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await expire();
