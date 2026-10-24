# Develog → GitHub Markdown Backup

디벨로그 공개 게시글을 GitHub에 Markdown 파일로 보관하는 비공식 자동 동기화 프로젝트입니다. **배포판에는 특정 사용자의 아이디가 설정되어 있지 않습니다.**

## 시작하기

1. 저장소 루트의 `config.json`에서 빈 문자열을 **자신의 디벨로그 아이디**로 변경합니다. 예: `{"develog_handle": "my_username"}` (`@` 제외).
2. `Settings → Actions → General → Workflow permissions`에서 `Read and write permissions`를 활성화합니다.
3. 포크한 저장소라면 `Actions`에서 워크플로가 비활성화되어 있지 않은지 확인하고 필요할 때 활성화합니다. `Actions → Sync Develog Posts → Run workflow`로 수동 실행한 뒤 `posts/`를 확인합니다.

아이디를 입력하지 않으면 안전을 위해 작업이 오류로 종료됩니다. `config.json`은 공개되어도 되는 사용자 이름만 저장하며, 비밀번호나 토큰을 넣지 마세요. 선택적으로 실행 환경변수 `DEVELOG_HANDLE`로 아이디를 덮어쓸 수도 있습니다. 이미 다른 계정의 `posts.json`이 있는 저장소에서는 계정을 변경하지 마세요. 계정별로 별도의 저장소를 사용해야 합니다.

## 동작 방식

- GitHub Actions가 **매일 23:50(한국 시간, UTC 14:50)**에 공개 프로필의 게시글을 확인하도록 예약됩니다. GitHub의 예약 실행은 지연되거나 누락될 수 있으며, `Run workflow`로 수동 실행할 수 있습니다.
- 새 글은 `posts/글 제목(최초 발행 날짜).md`로 저장하고, 수정된 글은 같은 파일을 갱신합니다. 제목을 변경해도 기존 파일명은 유지합니다.
- 글이 **정상 수집 3회 연속** 목록에서 누락되면 `archive/`로 옮기며, 재공개되면 `posts/`로 복원합니다. 매일 정상 실행된다면 첫 누락 확인 후 **약 2일 뒤 세 번째 실행 시** 이동하며, 지연·누락으로 더 오래 걸릴 수 있습니다.
- 글 목록이 **0개**이거나 게시글 수집 실패가 있다면 잘못된 삭제 판단을 피하기 위해 보관 처리를 중단합니다. 따라서 마지막 글 삭제는 자동 보관되지 않을 수 있습니다.
- `posts.json`에는 글별 파일명, 상태, 누락 횟수가 기록됩니다. 내용이 바뀌지 않으면 커밋하지 않습니다.

## 주의사항

- **로그인 없이 읽을 수 있는 공개 글만** 수집하며, 비공개 글과 임시저장 글은 포함되지 않습니다.
- HTML을 Markdown으로 변환하므로 복잡한 서식, 페이지 UI 요소 등이 일부 남거나 달라질 수 있습니다. 이미지 파일은 백업하지 않고 URL만 보관합니다.
- 사이트 HTML 구조가 변경되면 수집 코드 수정이 필요할 수 있습니다. `posts.json`을 임의로 변경하지 마세요.
- 이 프로젝트는 현재 **한 저장소당 한 디벨로그 계정**을 지원합니다.

## 로컬 실행 및 테스트

Python 3.12 기준으로 저장소 루트에서 실행합니다.

```bash
python -m pip install -r requirements.txt
python scripts/sync_develog.py
python -m unittest discover -s tests -v
```

실행 전 `config.json`에 자신의 계정을 설정해야 합니다. 로컬 동기화도 `posts/`, `archive/`, `posts.json`을 변경하지만 **GitHub에 자동으로 push하지는 않습니다**. 실제 백업을 보존하려면 테스트를 별도 복사본에서 진행하세요.

## 파일 구조

```text
config.json                    # 계정 설정 (필수)
.github/workflows/sync.yml     # 예약 및 수동 실행
scripts/sync_develog.py        # 수집과 동기화
posts/                         # 공개된 글
archive/                       # 삭제 확인 후 보관한 글
posts.json                     # 자동 생성되는 상태 기록
```

## 참고 자료

- [GitHub Actions 예약 실행](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule)
- [Velog와 GitHub 연동하기](https://velog.io/@dev_ssj/velog%EC%99%80-gitHub-%EC%97%B0%EB%8F%99%ED%95%98%EA%B8%B0)
