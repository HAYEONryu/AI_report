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
- **알려진 이슈:** 이 샌드박스에서는 실제 응답을 200으로 받았지만 파싱 결과가 0건이었습니다
  (`파싱된 이벤트 0건 — investing.com 마크업 구조 변경 가능성` → `status: failed`로 정상 폴백).
  investing.com의 실제 위젯 HTML 구조(class명 `theDay`, `eventRowId_`, `sentiment` 아이콘 등)를
  이 세션에서 끝까지 라이브 검증하지 못했습니다 (네트워크 타임아웃 반복).
  **실제 운영 전에 이 명령을 안정적인 네트워크에서 한 번 실행해서 이벤트가 몇 건이든 나오는지
  확인하세요.** 0건이 계속 나오면 `collectors/calendar.py`의 `_parse_events()` / `_importance_from_icons()`
  선택자를 실제 HTML에 맞게 고쳐야 합니다.
- 일반 `requests`/`curl`은 Cloudflare가 TLS 지문으로 403 차단하는 것을 확인했습니다 → `curl_cffi`(Chrome
  TLS 위장, JS 실행 없음)로 우회. GitHub Actions IP에서도 통할지는 `workflow_dispatch`로 별도 확인 필요.
- **부작용:** `data/cache/calendar_{월요일날짜}.json`

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
gh secret set ANTHROPIC_API_KEY --repo HAYEONryu/AI_report
gh secret set SMTP_USER --repo HAYEONryu/AI_report
gh secret set SMTP_APP_PASSWORD --repo HAYEONryu/AI_report
gh secret set MAIL_TO --repo HAYEONryu/AI_report        # hannau416@gmail.com
gh secret set ALERT_WEBHOOK_URL --repo HAYEONryu/AI_report
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

### 3.3 예상 실행 시간
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

## 4. 알려진 한계 (다음에 반드시 확인할 것)

1. **`collectors/calendar.py`의 실제 HTML 셀렉터 미검증.** 이 세션은 네트워크 제약으로 investing.com
   위젯의 실제 마크업을 끝까지 못 봤습니다. 파싱 0건이면 실패로 안전하게 처리되긴 하지만, 매일
   경제지표 섹션이 `failed`로 뜬다면 이 파일의 선택자를 실제 HTML 보고 고쳐야 합니다.
2. **`curl_cffi`가 GitHub Actions IP에서도 통하는지 미검증.** 로컬에서는 통했지만 Actions 러너
   IP 대역에 대한 Cloudflare 반응은 실제로 `workflow_dispatch`를 한 번 돌려봐야 압니다.
3. **`_press_from_link()`(news.py)는 언론사명이 아니라 도메인을 씁니다** (예: "연합뉴스" 대신
   "yna.co.kr"). 네이버 뉴스 API가 언론사명을 안 주기 때문입니다 — 리포트에 그대로 노출되니
   참고하세요.
