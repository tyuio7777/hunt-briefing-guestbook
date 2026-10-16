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

## 브리핑 참조 첨부 (v42)

브리핑 상단의 방명록 아이콘으로 해당 브리핑을 글에 첨부할 수 있습니다. 이 아이콘은 GitHub 계정 연동 중에 활성화됩니다.
앱은 Issue 본문에 `briefing_id`만 전송합니다. 제목·본문 주소·발행일은 운영자가 관리하는 기존 feed 저장소의 `feed/index.json` 및 `feed/latest.json`에서 확인한 값으로 게시합니다.
이용자가 임의의 제목이나 외부 주소를 첨부할 수 없습니다.

- 새 앱의 `briefing_id: null`: 참조 없음 또는 첨부 해제.
- 구버전 앱처럼 `briefing_id` 필드가 없는 수정: 기존 참조 유지.
- 공개 `data/guestbook.json`의 각 항목에 `briefing_reference`를 추가합니다. 참조가 없으면 `null`입니다.
- 참조가 있으면 `issue_id`, `title`, `html_url`, `published_at`을 포함합니다.
- 이미 게시한 참조는 이후 브리핑 목록에서 빠져도 유지합니다. 원본 HTML은 보관해 주세요.
- 기존 글의 참조를 편집하거나 해제해도 최초 게시 시각과 퀘스트 판정은 유지됩니다.

브리핑 자료를 일시적으로 조회하지 못하면 게시 작업을 중단하고 기존 공개 목록을 유지합니다. 연결 복구 후 수동 실행 또는 다음 갱신 작업에서 다시 처리합니다.
새 앱에서 첨부 제목을 누르면 앱 안의 브리핑 페이지가 열리고, 뒤로 가면 읽던 방명록 위치로 돌아옵니다.
