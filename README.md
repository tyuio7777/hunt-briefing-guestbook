# Hunt Briefing 방명록

Hunt Briefing 앱의 방명록을 보관하는 공개 저장소입니다.
앱에서 GitHub 계정을 연동하면 본인의 별명과 프로필로 글을 남기고 수정할 수 있습니다.

## 운영 구조

- 원문: GitHub Issues. GitHub 계정 이름과 글은 공개됩니다.
- 앱에서 읽는 목록: `data/guestbook.json` (GitHub Actions 자동 생성).
- 게시 이력: `data/publication-state.json` (자동 생성).
- 프로필 목록: `config/profiles.json`.
- 운영자 숨김/차단: `config/moderation.json`.
- 공지사항: 기존 `tyuio7777/hunt-briefing-feed`의 `community/notices.json`.

Issues를 새로 쓰거나 수정·닫기·삭제하면 전체 목록을 검증하여 다시 게시합니다.
운영 설정 변경, 수동 실행, 매시간 보완 실행도 지원합니다.
자동 생성 JSON은 직접 편집하지 마세요.

## 운영자 설정

등록된 GitHub App은 `hunt-briefing-guestbook-tyuio7777`입니다.
Device Flow 활성화, Issues 읽기/쓰기와 Metadata 읽기 권한으로 등록했습니다.
2026-10-16에 이 저장소 하나에만 설치된 것을 확인하고 기존 feed 저장소의 `community/config.json`에서 `enabled`를 켰습니다.
공개 Client ID `Iv23li46XpZtN0HuHc1x`와 저장소 ID `1421659020`은 이미 입력했습니다.
계정 연동이 활성화되어 있습니다. 앱에서 각 이용자가 자신의 GitHub 계정으로 승인하면 글을 작성·수정할 수 있습니다.
앱에 운영자 토큰이나 Client Secret을 넣지 않습니다.
일반 이용자에게 이 저장소의 collaborator 권한을 부여하지 않습니다.

글 숨김은 `config/moderation.json`의 `hidden_issue_numbers`, 사용자 차단은
`blocked_author_ids`에 등록합니다. 관리자 숫자 ID는 `20161415`입니다.
사용자 직접 편집으로 운영자의 숨김 정책을 해제할 수 없습니다.

새 글은 한국 날짜 기준 계정당 하루 3개까지 게시하며, 같은 날 중복 글은 게시하지 않습니다.
앱에는 최근 500개 글을 제공하고 원문은 Issues에 보관합니다.
전체 Issues 수가 5,000개에 도달하기 전에 분할/보관 정책을 확장하세요.

표준 공개 GitHub Actions 러너와 공개 JSON을 사용하며 별도 서버를 운영하지 않습니다.
