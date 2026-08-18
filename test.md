# 테스트 가이드

이 프로젝트의 모든 모듈은 "collect → normalize → enrich(AI) → render → deliver" 각 단계가
독립적으로 실행 가능하도록 만들어져 있습니다 (SPEC.md §8 rule 7). 시크릿이 하나도 없어도
대부분의 모듈은 "정상적으로 실패"하는지까지 확인할 수 있습니다 — 그게 이 시스템의 핵심 설계
원칙(부분 실패 허용)이기 때문입니다.

## 0. 준비

```bash
pip install -r requirements.txt
cp .env.example .env   # 값 채우기 (아래 "시크릿 목록" 참고)
```

시크릿이 하나도 없어도 아래 1~2단계는 대부분 실행됩니다 — 각 모듈이 없는 시크릿에 대해
어떻게 반응하는지 보는 것 자체가 유효한 테스트입니다.

### 시크릿 목록과 없을 때의 동작

| 시크릿 | 없으면 | 영향받는 모듈 |
|---|---|---|
| `NAVER_CLIENT_ID` / `SECRET` | `news` 섹션 `status: failed` (즉시, 네트워크 호출 없이) | `collectors/news.py` |
| `ANTHROPIC_API_KEY` | AI 호출이 인증 에러로 실패 → `inventory`는 `failed`, `news`는 요약 없이 제목/링크만, `commentary`는 기본 문구로 대체 | `ai/*.py` |
| `SMTP_USER` / `SMTP_APP_PASSWORD` | `main.py`가 렌더링까지는 끝내고 발송 단계에서 실패, 종료 코드 1 | `deliver.py` |
| `ALERT_WEBHOOK_URL` | 경고 로그만 찍고 조용히 스킵 (알림 자체가 실패해도 파이프라인은 안 죽음) | `deliver.py` |

이 표는 실제로 이 세션에서 시크릿 없이 `python main.py --now`를 돌려서 확인한 결과입니다 (아래 4번 참고).

---

## 1. 모듈 단위 테스트 (시크릿 없이도 대부분 가능)

각 명령은 실제 네트워크를 호출합니다 (mock 아님). `data/`에 결과가 기록되니, 처음 실행해보는
것이라면 무엇이 어디에 쓰이는지 아래 "부작용" 항목을 먼저 읽어보세요.

### `schema.py` — 스키마 자체 검증
```bash
python schema.py
```
기대 출력: `schema self-check passed`. 실패하면 `schema.py`를 건드린 것이니 되돌리세요.

### `render.py` — 템플릿 렌더링
```bash
python render.py                              # data/mock_report.json 사용
python render.py data/mock_report_partial.json # stale/failed/null-change 분기 확인용
```
`data/reports/preview.html`이 생성됩니다. 브라우저로 열어서 눈으로 확인하세요.

### `collectors/prices.py` — 시세 (yfinance 1분봉 / Stooq 폴백)
```bash
python -m collectors.prices
```
- **부작용:** `data/history/prices.csv`에 오늘자 스냅샷을 append (같은 날 재실행해도 중복 안 쌓입니다 — 멱등 가드 있음)
- 이력이 없는 첫 실행: `prev_price: null`, `change: null` ("비교 불가")
- 이 세션에서 실제로 성공 확인함 (구리/WTI/USDKRW 3종 모두 `status: ok`)

### `collectors/calendar.py` — 경제지표 (investing.com)
```bash
python -m collectors.calendar
```
- **실제 HTML로 검증 완료.** 처음 작성한 버전은 두 가지가 틀렸었습니다:
  1. 날짜 구분자 `theDay` 클래스가 `<tr>`가 아니라 그 안의 `<td>`에 붙어있어서 날짜를 절대
     못 읽고 모든 이벤트를 건너뛰었음 (파싱 0건의 진짜 원인)
  2. 중요도 아이콘이 채워진 것도 빈 것도 둘 다 클래스에 `gray`가 붙어있고(`grayFullBullishIcon` /
     `grayEmptyBullishIcon`) `Full`/`Empty`로만 구분되는데, `gray` 유무로 필터링해서 정반대로 셌음
  실제 저장된 HTML(206KB)로 재검증해서 35개 이벤트가 정확한 중요도/날짜로 파싱되는 것 확인함.
- 일반 `requests`/`curl`은 Cloudflare가 TLS 지문으로 403 차단합니다 → `curl_cffi`(브라우저 TLS 위장,
  JS 실행 없음)로 우회 시도. **하지만 브라우저 지문 4종(chrome124/136/146, firefox147) 전부 GitHub
  Actions IP에서는 403이 났습니다** (로컬에서는 매번 200) — TLS 지문이 아니라 **GH Actions IP 대역
  자체가 평판 차단**된 것으로 보입니다. 그래서 프로덕션에서는 `cloudflare-worker/calendar-proxy.js`를
  통해 Cloudflare 자체 엣지에서 대신 가져오게 만들었습니다 (아래 "Cloudflare Worker 배포" 참고).
  `CALENDAR_PROXY_URL`이 설정 안 되어 있으면 로컬 개발용으로 기존 `curl_cffi` 직접 호출로 폴백합니다.
- **부작용:** `data/cache/calendar_{월요일날짜}.json`

### Cloudflare Worker 배포 (`CALENDAR_PROXY_URL`, GH Actions에서만 필요)

1. https://dash.cloudflare.com → **Workers & Pages** → **Create** → **Create Worker**
2. 아무 이름이나 지정하고 생성 (예: `calendar-proxy`)
3. 코드 편집기에서 기존 템플릿을 지우고 `cloudflare-worker/calendar-proxy.js` 내용을 그대로 붙여넣기
4. **Deploy** 클릭
5. 배포 후 나오는 URL (`https://calendar-proxy.<계정>.workers.dev` 형태) 복사
6. `gh secret set CALENDAR_PROXY_URL --repo HAYEONryu/AI_report` 로 등록 (아래 §3.1 참고)

무료 티어(하루 10만 요청)로 충분합니다. CLI(`wrangler`) 없이 대시보드만으로 끝납니다.

### `collectors/news.py` — 뉴스 (네이버 검색 API)
```bash
python -m collectors.news
```
- `NAVER_CLIENT_ID`/`SECRET` 없으면 네트워크 호출 없이 즉시 `status: failed` (이 세션에서 확인함)
- 있으면: 6개 쿼리 검색 → 중복/블랙리스트/3일 필터 → AI 배치 요약(1회 호출) → 상위 10건
- **부작용:** `data/cache/news_latest.json` (성공 시에만 갱신, 다음 실패 시 폴백용)

### `collectors/inventory.py` — 재고 (NH선물 PDF)
```bash
python -m collectors.inventory
```
- 이 세션에서 실제로 게시물 목록 파싱 → PDF 다운로드 → "LME Stock"/"COMEX" 페이지 찾기까지
  전부 성공 확인함. `ANTHROPIC_API_KEY` 없으면 그 다음 AI 구조화 단계에서만 실패 (`status: failed`,
  사유: "AI 추출/검증 실패").
- **부작용:** `data/cache/inventory_latest.json` (성공 시에만)

### `ai/*.py` — AI 레이어만 따로 테스트
`ANTHROPIC_API_KEY`가 있으면 파이썬 REPL에서 바로 호출 가능합니다:
```bash
python -c "from ai.commentary import write_commentary; import json; print(json.dumps(write_commentary(json.load(open('data/mock_report.json', encoding='utf-8'))['sections']), ensure_ascii=False, indent=2))"
```
`ai/extract.py`, `ai/summarize.py`도 같은 방식으로 mock 입력을 넣어 단독 테스트할 수 있습니다.

### `deliver.py` — 발송만 따로 테스트
```bash
python -c "
import json
from deliver import send_report
report = json.load(open('data/mock_report.json', encoding='utf-8'))
from render import render_report
send_report(report, render_report(report))
"
```
`SMTP_USER`/`SMTP_APP_PASSWORD`가 실제 Gmail 앱 비밀번호여야 진짜로 메일이 나갑니다 — 테스트
메일이 실제로 발송된다는 뜻이니 주의하세요.

---

## 2. 전체 파이프라인 로컬 테스트

```bash
python main.py --now
```
`--now`는 "KST 15:00까지 대기"를 건너뜁니다 (안 붙이면 목표 시각까지 실제로 sleep합니다 — 이미
지난 시각이면 즉시 진행하도록 만들어 뒀습니다).

이 세션에서 시크릿 전부 없이 실행한 결과:
```
prices:    ok
calendar:  failed (파싱 0건, 위 "알려진 이슈" 참고)
news:      failed (NAVER 시크릿 없음)
inventory: failed (ANTHROPIC 시크릿 없음)
commentary: 기본 문구로 대체
발송: SMTP_USER 없어서 실패 → 종료 코드 1
```
**핵심 확인 포인트:** 위 상황에서도 프로세스가 죽지 않고 끝까지 실행되어
`data/reports/{날짜}.json`을 남겼습니다 — SPEC.md §8 rule 1("부분 실패 허용")이 실제로 동작한다는
뜻입니다. 시크릿을 채운 뒤 다시 돌리면 각 섹션이 하나씩 `ok`로 바뀌는 걸 확인하세요.

종료 코드: 렌더링/발송이 모두 성공하면 `0`, 발송까지 실패하면 `1` (CI에서 실패로 잡힘).

---

## 3. GitHub Actions에서 테스트

Repo: `HAYEONryu/AI_report` (private).

### 3.1 Secrets 등록 (최초 1회)
```bash
gh secret set NAVER_CLIENT_ID --repo HAYEONryu/AI_report
gh secret set NAVER_CLIENT_SECRET --repo HAYEONryu/AI_report
gh secret set OPENAI_API_KEY --repo HAYEONryu/AI_report
gh secret set SMTP_USER --repo HAYEONryu/AI_report
gh secret set SMTP_APP_PASSWORD --repo HAYEONryu/AI_report
gh secret set MAIL_TO --repo HAYEONryu/AI_report        # hannau416@gmail.com
gh secret set ALERT_WEBHOOK_URL --repo HAYEONryu/AI_report
gh secret set CALENDAR_PROXY_URL --repo HAYEONryu/AI_report   # Cloudflare Worker 배포 후 (위 참고)
```
(각 명령을 실행하면 값을 입력하라는 프롬프트가 뜹니다.)

### 3.2 수동 실행 (16시든 아무 때든)
```bash
# 오전 캐시부터 채우고 싶다면 먼저:
gh workflow run morning-collect.yml --repo HAYEONryu/AI_report

# 본 리포트 — skip_sleep 기본값 true라 즉시 실행됩니다
gh workflow run daily-report.yml --repo HAYEONryu/AI_report

# 진행상황 실시간 확인
gh run watch --repo HAYEONryu/AI_report
```
GitHub 웹 UI로도 가능합니다: **Actions 탭 → 워크플로우 선택 → "Run workflow"**.
`daily-report.yml`은 수동 실행 시 "즉시 실행 (KST 15:00 대기 건너뛰기)" 체크박스가 기본 체크되어
있어 몇 시에 눌러도 바로 실행됩니다. 체크를 해제하면 실제 cron과 동일하게 15:00까지 대기합니다.

### 3.3 Self-hosted runner 설정 (`daily-report.yml` 전용, 필수)

`mail.hoban.co.kr`이 사내망 전용이라 GitHub 소유의 클라우드 러너(`ubuntu-latest`)에서는
DNS 조회조차 안 됩니다 (이 세션의 로컬 환경에서도 동일하게 실패 — 코드 문제가 아니라 네트워크
경계 문제). 그래서 `daily-report.yml`은 `runs-on: [self-hosted, Windows]`로 바꿔뒀습니다.
`morning-collect.yml`은 SMTP를 안 쓰므로 그대로 `ubuntu-latest`입니다.

**중요:** 러너는 반드시 `mail.hoban.co.kr`에 실제로 접속되는 사내망 PC(회사 와이파이/VPN 연결된
PC)에 설치해야 합니다. 이 대화가 실행되는 샌드박스는 그 네트워크 밖이라 여기서 설치해도 의미가
없습니다.

1. 사내망에 연결된 Windows PC에서 PowerShell을 관리자 권한으로 열기
2. **GitHub 웹 UI**로 가서 정확한 최신 버전 명령을 받는 걸 권장: repo → **Settings → Actions →
   Runners → New self-hosted runner → Windows** 선택 → 나오는 명령을 그대로 복사/붙여넣기
   (버전 번호가 자동으로 최신으로 채워져서 안전합니다)
3. 등록 시 토큰을 물어보면 아래 값 사용 가능 (발급 시각 기준 1시간 유효 — 만료됐으면 3번 URL에서
   새 러너 추가 시 새 토큰이 자동으로 나옵니다):
   ```
   AKQ7JJHLHPCVRUSSHN4PRDLKQP6RE
   ```
4. `config.cmd` 실행 중 프롬프트는 전부 Enter(기본값)로 넘어가도 됩니다
5. **포그라운드로 잠깐 테스트:** `./run.cmd` 실행 후 창을 열어둔 채로 워크플로우 수동 실행해서
   확인
6. **재부팅/로그아웃에도 계속 떠 있게 하려면 Windows 서비스로 설치:**
   ```powershell
   ./svc.cmd install
   ./svc.cmd start
   ```
7. 스케줄된 cron(평일 KST 14:40)에도 매번 켜져 있어야 실제 자동 발송이 됩니다 — 이 PC가
   그 시간에 항상 켜져 있고 네트워크에 연결되어 있는지 운영 관점에서 확인 필요합니다
   (SPEC.md의 "사람 개입 0" 전제와 트레이드오프되는 지점 — 사용자가 명시적으로 선택함)

### 3.4 예상 실행 시간
| 구간 | 시간 |
|---|---|
| Job 기동 + `pip install` | 30~60초 |
| 시세 (yfinance) | 5~15초 |
| 경제지표/뉴스/재고 (캐시 히트 시) | 1초 미만 |
| 경제지표/뉴스/재고 (캐시 없어 재수집 시) | 10~30초 |
| AI 3콜 | 10~20초 |
| 렌더링 + SMTP | 2~5초 |
| **합계 (평일, 오전 캐시 정상)** | **약 1~2분** |
| **합계 (오전 캐시 없음/재시도)** | **약 3~5분** |

---

## 4. 알려진 한계

1. **`_press_from_link()`(news.py)는 언론사명이 아니라 도메인을 씁니다** (예: "연합뉴스" 대신
   "yna.co.kr"). 네이버 뉴스 API가 언론사명을 안 주기 때문입니다 — 리포트에 그대로 노출되니
   참고하세요.
2. **GitHub Secrets가 등록 안 되어 있으면 env var가 "없음"이 아니라 빈 문자열("")이 됩니다.**
   `${{ secrets.SMTP_USER }}` 같은 식으로 워크플로우에 박아두면, 시크릿을 등록 안 해도
   `os.environ["SMTP_USER"]`가 `KeyError`를 내는 대신 빈 문자열을 돌려줍니다 — 실제로
   `daily-report.yml`을 SMTP 시크릿 없이 돌렸을 때 Gmail이 "빈 아이디/비번"으로 인증 시도하는 걸
   확인했습니다 (535 에러). 코드 버그는 아니고 GitHub Actions의 기본 동작이니 참고만 하세요.

## 5. 실제로 검증된 것 (2026-08-18 세션 기준)

- `collectors/prices.py`: 로컬에서 yfinance 1분봉 3종 전부 `status: ok`로 실측
- `collectors/inventory.py`: NH선물 게시물 파싱 → PDF 다운로드 → "LME Stock"/"COMEX" 페이지
  찾기까지 로컬에서 전부 성공 (AI 키 없어 구조화만 실패)
- `collectors/news.py`: GitHub Actions에서 네이버 검색 실제 성공, AI 요약만 키 없어 실패 →
  제목/링크만으로 우아하게 폴백
- `collectors/calendar.py`: 로컬 재검증으로 이벤트 35건 정상 파싱 확인 (§1 참고)
- `python main.py --now`: 시크릿 하나도 없이 로컬/Actions 양쪽에서 전체 파이프라인이 안 죽고
  끝까지 실행되어 `data/reports/{날짜}.json`을 남기는 것 확인 (SPEC.md §8 rule 1 실증)
