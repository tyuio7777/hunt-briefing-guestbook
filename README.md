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

Issues를 새로 쓰거나 수정·닫기·삭제하면 갱신합니다. 평소에는 변경된 Issues만 API로 조회하고, 필요한 필드만 저장한 캐시를 이용해 작성 제한·중복·숨김 정책을 다시 검증합니다.
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
5,000개 고정 중단 제한을 제거했습니다. API를 페이지별로 끝까지 읽으며, 첫 적용·수동 실행·삭제/이전 이벤트와 주 1회 전체 대조 때 누락을 복구합니다. 조회 도중 실패하면 기존 공개 목록과 동기화 지점을 유지합니다.

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


## v45 데이터 관리

- 변경 조회는 마지막 갱신 시각보다 5분 전부터 겹쳐 읽어 경계 시각 누락을 줄입니다. 전체 대조 시 누락 항목은 개별 조회로 실제 삭제/이전을 확인합니다.
- `state/issues/`에는 번호 1,000개 단위로 조회 캐시를 나눠 저장합니다. 사용자 프로필·댓글·HTML 같은 불필요한 API 필드는 저장하지 않습니다.
- 기존 `data/publication-state.json`의 최초 게시·등록 식별 이력은 보존합니다. 자동으로 사용자 Issues를 닫거나 지우지 않습니다.
- 앱 공개 목록은 최신 500개, 처리 결과는 2,000개를 유지합니다. 과거 글은 원본 Issues에서 보존됩니다.
- `data/guestbook-version.json`에는 SHA-256과 바이트 크기를 게시합니다. v45 앱은 10초마다 작은 버전 정보만 확인하고 변경된 경우에만 `data/snapshots/{해시}.json`을 읽습니다.
- 검증된 스냅샷은 최신 8개만 유지합니다. 기존 `data/guestbook.json`도 계속 갱신하여 v41~v44 앱과 호환됩니다. 페이지 최초 진입/수동 새로고침도 서버 버전을 확인합니다.
- 공지 조회, GitHub 인증, 글 작성·수정, 퀘스트, 10초 조회 주기와 화면 비활성 시 중단은 그대로입니다.
- `data/storage-status.json`: 생성 파일 100 MiB 이상 또는 조회 캐시 20,000개 이상이면 Actions 경고를 출력합니다.
- `tools/check_storage.py`: 주 1회 GitHub 저장소 크기 추정치를 확인하며 256 MiB 이상이면 Actions 경고를 출력합니다. `data/repository-size.json`에서 마지막 확인값을 볼 수 있습니다. 조회 실패는 게시를 막지 않습니다.
- 위 경고는 운영용이며 앱 푸시가 아닙니다. 월간 비용을 만드는 서비스·유료 runner·LFS·artifact는 추가하지 않습니다.
- Git 이력은 재작성하지 않습니다. 사용자 글과 최소 게시 이력은 계속 쌓이므로 무제한 운영을 보장하지 않으며, 경고가 나오면 저장소 분할 또는 별도 보관 절차를 검토합니다.

검증: `python3 -m unittest discover -s tests -v`

## v47 댓글과 실제 수정 시각

- 앱 방명록 카드의 본문/댓글 아이콘은 같은 상세 화면을 엽니다. 원글 전체, 댓글, 작성란 순서입니다.
- 원본 댓글은 해당 Issue의 Comments입니다. 다른 글로 이동하거나 공통 브리핑 ID로 합치지 않습니다.
- 앱 댓글의 구조는 `schema_version`, `kind: hunt-briefing-comment`, `submission_id`(32자리 UUID), `nickname`, `profile_id`, `body`입니다. 숫자 작성자 ID는 GitHub 응답에서만 가져옵니다.
- 별명은 2~16자, 댓글은 앞뒤 공백 제거 후 1~500 Unicode 문자입니다. 일반 GitHub 문장·봇·잘못된 형식·허용되지 않은 관리자 프로필은 앱 댓글 수에 포함하지 않습니다.
- 댓글에는 원글의 하루 3개 등록 제한을 적용하지 않습니다. 같은 원글·작성자·submission_id를 중복 게시하지 않습니다. GitHub 자체 API/스팸 제한은 그대로입니다.
- 이용자는 본인 댓글을 수정하거나 삭제할 수 있습니다. 앱에서 삭제 확인을 받고 작성자 및 현재 본문 개정 값을 재검사합니다. 원글 작성자는 다른 사람 댓글의 수정/삭제 권한을 받지 않습니다.
- `issue_comment`의 created/edited/deleted 이벤트를 추가했습니다. PR 댓글 이벤트는 실행하지 않습니다. 변경 댓글 증분 조회와 해당 원글의 전체 댓글 재대조를 병행하며, 삭제 후보는 개별 조회 후 제거합니다. 주 1회 전체 대조로 누락 이벤트도 복구합니다.
- 공개 목록은 기존 최근 500개 원글에 연결된 댓글입니다. 오래된 글이 앱 목록에서 빠져도 원본 댓글을 삭제하지 않습니다.
- `data/comments-version.json` → `data/comments/snapshots/{해시}.json` → `data/comments/blobs/{해시}.json` 순서로 인덱스·글별 목록·50개 단위 페이지를 읽습니다. 크기·SHA-256이 일치한 데이터만 표시합니다. `data/comments-index.json`은 운영 확인용 현재 인덱스입니다.
- 인덱스는 최신 8개 스냅샷과 이들이 참조하는 파일만 유지합니다. 이전 버전의 참조가 모두 없어지면 해당 파일을 정리합니다. API 재조회용 캐시는 `state/comments/{Issue번호}.json`, 동기화 지점은 `state/comments-sync.json`입니다.
- 게시 데이터가 같으면 공개 버전을 갱신하지 않습니다. 생성 용량 경고에는 댓글 파일도 포함됩니다. Git 이력과 GitHub 원본은 자동 삭제/재작성하지 않습니다.
- 댓글 숨김: `config/moderation.json`에 `hidden_comment_ids` 숫자 배열을 추가하세요. 예: `"hidden_comment_ids": [1234567890]`. 기존 정책 항목과 다른 ID는 보존하세요. `blocked_author_ids`는 원글과 댓글에 함께 적용됩니다.
- 닫힘/숨김/비공개 원글의 댓글은 앱에서 게시하거나 새로 작성하지 않습니다. 잠긴 원글의 공개 댓글은 읽을 수 있지만 등록·수정은 막습니다. 이 정책은 GitHub 웹의 권한을 바꾸지 않습니다. GitHub 웹에서도 작성 차단이 필요하면 운영자가 Lock conversation을 사용합니다.
- 원글과 댓글의 `edited_at`은 GraphQL `lastEditedAt`으로 확인합니다. 원글의 `updated_at`도 실제 본문 편집 시각(편집 전에는 생성 시각)으로 게시합니다. 댓글 추가로 Issue.updated_at이 바뀌어도 원글이 편집된 것처럼 표시하지 않습니다. `body_revision`은 실제 GitHub JSON 본문의 SHA-256으로 편집 충돌 검사에 사용합니다.
- 앱의 댓글 전송 전 처리 기록은 계정·원글별로 보관합니다. 연결이 끊기면 먼저 해당 작성자와 submission_id/개정 값을 조회하며, 자동 재전송하지 않습니다. GitHub API 자체의 exactly-once를 보장하는 기능은 아닙니다.
- 기존 GitHub App·Device Flow·Issues 읽기/쓰기와 Actions 권한을 재사용합니다. 새 비밀키, 사용자 collaborator 권한, 관리 서버, 유료 서비스는 추가하지 않았습니다. 기존 공지·브리핑·알림·동향 수집과 예약은 변경하지 않습니다.

검증 명령은 위와 동일합니다. 실제 이용자 토큰/Android 기기에서의 조작 검증은 별도로 필요하며, 배포 확인을 위해 운영 방명록에 테스트 댓글을 쓰지 않았습니다.
