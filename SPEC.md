# 일일 원자재 리포트 자동화 시스템 — 구현 지시서

> 이 문서를 Claude Code에 그대로 전달하세요.
> 프로젝트 루트에 `SPEC.md`로 저장해두면 이후 세션에서도 컨텍스트로 재사용할 수 있습니다.

> **2026-08-18 구현 중 실제로 바뀐 확정 사항 (원본 문서는 아래 그대로 보존, 최신 상태는 test.md 참고):**
> - **AI: Anthropic → OpenAI로 전환.** 사용자가 명시적으로 요청. `ai/client.py`는 OpenAI SDK +
>   `response_format={"type":"json_object"}` 사용. 모델: 추출/요약 `gpt-4o-mini`, 코멘터리 `gpt-4o`.
>   시크릿명도 `ANTHROPIC_API_KEY` → `OPENAI_API_KEY`로 바뀜.
> - **발송: Gmail → 회사 메일 서버(`mail.hoban.co.kr:587`, STARTTLS)로 전환.** 메커니즘은 동일(SMTP+STARTTLS).
> - **calendar.py는 GitHub Actions IP에서 Cloudflare에 통째로 막혀** `cloudflare-worker/calendar-proxy.js`
>   (무료 티어) 경유로 우회. 로컬 개발은 기존 curl_cffi 직접 호출로 폴백.

---

## 0. 역할 및 목표

당신은 이 프로젝트의 구현 담당 엔지니어입니다.
**매일 KST 16:00에 사람이 읽기 좋은 원자재 시황 리포트가 이메일로 도착해 있는 시스템**을 구축합니다.
사람의 개입은 0이어야 하고, **AI API 토큰 외에는 어떤 비용도 발생하면 안 됩니다.**

이 문서의 기술 스택과 데이터 소스는 **이미 검토를 마친 확정 사항**입니다.
임의로 다른 소스나 라이브러리로 대체하지 마세요. 변경이 필요하다고 판단되면 코드를 쓰기 전에 먼저 질문하세요.

---

## 1. 수집 요건 (고정)

| # | 항목 | 상세 |
|---|---|---|
| 1 | **시세** | 구리 선물 / WTI 원유 / USD-KRW 환율의 **KST 15:00 기준 시점 가격**과 전일 대비 변동 |
| 2 | **경제지표** | investing.com 경제 캘린더 기준, **미국·중국**의 이번 주 주요 지표 일정/결과 (**중요도 중간 이상**) |
| 3 | **뉴스** | 구리 관련 **최근 3일 이내** 뉴스 **최대 10건** — 제목·링크·**한글 2문장 요약** |
| 4 | **재고** | NH선물 리서치 일일금속시황 PDF에서 **LME Stocks / COMEX 재고** 추출 (전일재고·현재재고·변동량) |

---

## 2. 확정된 기술 결정

### 2.1 데이터 소스

| 항목 | 주 소스 | 폴백 | 비고 |
|---|---|---|---|
| 시세 | `yfinance` — `HG=F`(구리), `CL=F`(WTI), `KRW=X`(환율) | Stooq CSV | Alpha Vantage / API-Ninjas 사용 금지 (아래 참조) |
| 경제지표 | **investing.com 공식 위젯** (`sslecal2.investing.com`) | 직전 성공 캐시 | 일반 API 경로는 Cloudflare 403. 위젯만 사용 |
| 뉴스 | 네이버 검색 API(뉴스) | 직전 성공 캐시 | |
| 재고 | `futures.co.kr` 일일금속시황 PDF | 직전 성공 캐시 | |

**금지 소스와 이유 (재검토 불필요):**
- **Alpha Vantage `COPPER`** — 선물이 아닌 월간 글로벌 가격 지수. 15시 스냅샷 불가
- **API-Ninjas Commodity Price** — 무료 티어는 품목 주간 로테이션(구리/WTI 미보장) + 상업적 이용 금지 + 15분 지연
- **investing.com 일반 API 엔드포인트** — Cloudflare V2로 403

### 2.2 인프라

- **런타임:** Python 3.11
- **스케줄링:** GitHub Actions (Private Repo, 무료 티어)
- **상태 저장:** 리포지토리 내 `data/` 디렉터리에 커밋 (별도 DB 없음)
- **발송:** Gmail SMTP + 앱 비밀번호, HTML 메일
- **AI:** Anthropic API

### 2.3 의존성

```
yfinance
requests
beautifulsoup4
lxml
pandas
pdfplumber
jinja2
tenacity
anthropic
```

Playwright/Selenium은 **원칙적으로 사용하지 않습니다.** (§4.4 참조)

---

## 3. 데이터 계약 — 가장 먼저 확정할 것

**코드를 쓰기 전에 이 스키마부터 확정하고, 이후 모든 모듈이 이 계약을 지키게 하세요.**
수집기를 교체해도 템플릿과 AI 프롬프트가 깨지지 않게 하기 위한 장치입니다.

```jsonc
{
  "report_date": "2026-08-18",              // KST 기준 리포트 일자
  "generated_at": "2026-08-18T16:00:00+09:00",

  "sections": {
    "prices": {
      "status": "ok",                        // ok | stale | failed
      "source": "yfinance",
      "as_of": "2026-08-18T15:00:00+09:00",
      "items": [
        {
          "key": "copper",
          "label": "구리 선물 (COMEX HG)",
          "price": 4.5215,
          "unit": "USD/lb",
          "prev_price": 4.5780,
          "prev_basis": "2026-08-17T15:00:00+09:00",  // 전일 동시각
          "change": -0.0565,
          "change_pct": -1.234
        }
        // wti, usdkrw 동일 구조
      ]
    },

    "calendar": {
      "status": "ok",
      "week_start": "2026-08-17",
      "week_end": "2026-08-21",
      "events": [
        {
          "date": "2026-08-20",
          "time_kst": "21:30",
          "country": "US",                   // US | CN
          "importance": 3,                   // 2=중간, 3=높음
          "name": "근원 소비자물가지수 (MoM)",
          "actual": null,                    // 미발표 시 null
          "forecast": "0.3%",
          "previous": "0.2%",
          "is_released": false
        }
      ]
    },

    "news": {
      "status": "ok",
      "items": [
        {
          "title": "…",
          "link": "https://…",
          "published_at": "2026-08-17T09:12:00+09:00",
          "press": "연합뉴스",
          "summary": "두 문장으로 된 한글 요약.",
          "relevance": 5                     // 1-5, AI 판정
        }
      ]
    },

    "inventory": {
      "status": "ok",
      "source_date": "2026-08-18",           // PDF 기준일 (필수 표기)
      "source_url": "https://…",
      "lme": [
        { "metal": "Copper", "prev": 123450, "current": 124200, "change": 750, "unit": "톤" }
      ],
      "comex": [
        { "metal": "Copper", "prev": 45120, "current": 44980, "change": -140, "unit": "숏톤" }
      ]
    }
  },

  "commentary": {
    "headline": "구리, 달러 강세에 사흘째 약세",
    "body": ["문장1", "문장2", "문장3"],
    "implication": "전선 원가 관점 시사점 한 줄"
  },

  "errors": [
    { "section": "inventory", "reason": "PDF 미게시", "fallback": "2026-08-15 캐시 사용" }
  ]
}
```

**`status` 값의 의미 — 반드시 이대로 구현하세요.**
- `ok` — 당일 수집 성공
- `stale` — 수집 실패, 캐시로 대체. 리포트에 **회색 처리 + 기준일자 명시**
- `failed` — 수집 실패, 캐시도 없음. 리포트에 **"수집 실패" 문구 + 사유**

---

## 4. 모듈별 구현 스펙

### 4.1 시세 (`collectors/prices.py`)

**핵심 요구사항: "KST 15:00 기준"은 종가가 아니라 스냅샷입니다.**
KST 15:00은 UTC 06:00이며 COMEX 전자장이 거래 중인 시각입니다. 일봉 API로는 이 값을 만들 수 없습니다.

구현:
1. `yf.Ticker(symbol).history(period="7d", interval="1m")`로 1분봉 조회
2. KST 15:00:00에 **가장 가까운(15:00 이하 마지막) 봉의 종가**를 스냅샷으로 채택
3. 스냅샷을 `data/history/prices.csv`에 **append** (컬럼: `date, key, price, captured_at`)
4. **전일 대비 = 전일 15:00 스냅샷 대비**로 계산. CSV에서 직전 영업일 값을 조회
5. 이력에 전일 값이 없으면(최초 실행/휴장) `prev_price: null`, `change: null`로 두고 리포트에 "비교 불가" 표기

**주의사항**
- `yfinance`의 `previousClose`(뉴욕 정규장 마감 기준)를 **절대 사용하지 마세요.** 15시 스냅샷과 기준이 달라 숫자가 어긋납니다.
- 1분봉은 약 7일치까지 소급 조회됩니다. 잡이 하루 실패해도 다음 날 복구 가능하도록 **누락일 백필 함수**를 넣으세요.
- 단위 명시 필수: 구리 `USD/lb`, WTI `USD/bbl`, 환율 `KRW`
- 폴백: Stooq CSV (`https://stooq.com/q/d/l/?s=hg.f&i=d` 등). 일봉만 나오므로 `status: "stale"` + "전일 종가 기준(대체)" 표기

### 4.2 경제지표 (`collectors/calendar.py`)

**소스 URL은 반드시 아래 절차로 확보하세요. 파라미터를 추측해서 조립하지 마세요.**

1. `investing.com/webmaster-tools/economic-calendar`에서 **미국+중국 / 중요도 중·상 / 이번 주 / 서울 시간대**로 설정
2. 생성된 iframe의 `src` URL을 상수로 하드코딩 (`config.py`)

파싱:
- 응답은 순수 HTML 테이블. **JS 렌더링 불필요 → Playwright 사용 금지**
- `User-Agent`, `Referer` 헤더를 일반 브라우저처럼 설정
- **행 구조 주의:** 날짜 구분행과 이벤트행이 섞여 나옵니다. 날짜행을 만나면 현재 날짜 변수를 갱신하고, 이후 이벤트행에 그 날짜를 적용하며 순회하세요.
- **중요도는 텍스트가 아니라 아이콘(`<i>` 태그) 개수 / class name**으로 판정합니다. 2개 이상만 채택.

**캐시 전략 (중요):**
이번 주 일정은 매일 바뀌지 않습니다.
- **월요일 오전 잡에서 주간 일정 전체를 1회 수집** → `data/cache/calendar_{week_start}.json`
- 평일에는 같은 파일을 다시 수집해 **`actual`(실제치)만 갱신**. 수집 실패 시 기존 캐시 그대로 사용
- 이 구조로 실패 표면이 크게 줄어듭니다

### 4.3 뉴스 (`collectors/news.py`)

네이버 검색 API(뉴스) 사용. `X-Naver-Client-Id` / `X-Naver-Client-Secret` 헤더.

**"구리" 단일 검색은 절대 금지 — 경기도 구리시 뉴스가 절반 이상 섞입니다.**

1. **멀티 쿼리 수집** (각 `sort=date`, `display=30`):
   `전기동`, `구리 가격`, `LME 구리`, `구리 선물`, `비철금속`, `동가격`
2. `link` 기준 **중복 제거**
3. `pubDate` 파싱 → **최근 3일 이내**만 유지
4. **지역명 블랙리스트 1차 필터:** 제목에 `구리시`, `구리역`, `구리도매시장`, `남양주` 포함 시 제외
5. HTML 태그(`<b>`) 및 HTML 엔티티(`&quot;` 등) 제거
6. 남은 **20~30건을 AI에 통째로 넘겨** 관련성 점수 + 요약을 한 번에 받음 (§5.2)
7. AI가 매긴 `relevance` 상위 **10건**만 최종 채택

**주의:** 네이버 뉴스 API는 본문을 주지 않습니다(`description` 100자 내외). 원문 크롤링은 사이트마다 DOM이 달라 불안정하므로 **하지 마세요.** 제목+description만으로 2문장 요약을 생성합니다.

### 4.4 재고 PDF (`collectors/inventory.py`)

**대상:** `https://www.futures.co.kr/content/Getcontent.do?content=3000031` (NH선물 일일금속시황)

**구현 전 필수 확인 (10분 스파이크):**
1. `requests.get()` 응답 HTML에 게시물 목록이 그대로 들어있는지 확인
2. 들어있으면 → **`requests` + BeautifulSoup으로 구현. Playwright 사용 금지**
3. 첨부파일 링크도 보통 `fileDown.do?fileId=...` 형태 GET이므로 `requests`로 직접 다운로드
4. 만약 JS 렌더링이 필수라고 판단되면, **코드를 쓰기 전에 근거와 함께 보고**하세요

**게시물 선택 로직:**
- 날짜를 하드코딩하지 마세요. "어제 게시물"도 아닙니다.
- **최신 게시물의 게시일자를 파싱** → 오늘자가 있으면 오늘자, 없으면 가장 최근 것
- 채택한 게시물의 **기준일자를 `source_date`에 반드시 기록**하고 리포트에 노출

**PDF 파싱 — 규칙 기반 파싱 금지:**
- `pdfplumber`로 "LME Stocks" / "COMEX 재고" 항목이 있는 **페이지의 텍스트만 추출**
- 좌표·정규식 기반 표 파싱은 하지 마세요. 리포트 레이아웃이 바뀌는 순간 **조용히 틀린 숫자**를 뱉습니다
- 추출한 텍스트를 **AI에 넘겨 고정 JSON 스키마로 구조화** (§5.1)
- 반환 JSON을 **코드로 검증**: 모든 값이 숫자형인가 / `change == current - prev`가 일치하는가 / 금속 항목이 비어있지 않은가
- 검증 실패 시 → `status: "failed"` + errors에 사유 기록 (틀린 값을 통과시키지 말 것)

---

## 5. AI 레이어 (`ai/`)

**원칙: AI는 "비정형 → 정형" 변환과 "문장 생성"에만 씁니다.**

### 5.1 PDF 표 추출 — `extract_inventory()`
- 모델: `claude-haiku-4-5-20251001`
- 입력: PDF 해당 페이지 텍스트 (~1,500 토큰)
- 시스템 프롬프트 요지:
  > 원자재 리포트 텍스트에서 LME Stocks와 COMEX 재고 수치를 추출한다. 지정된 JSON 스키마로만 응답하고 마크다운 코드펜스나 설명은 붙이지 않는다. 텍스트에 없는 값은 절대 추측하지 말고 null로 둔다.
- 출력: `sections.inventory` 스키마

### 5.2 뉴스 배치 요약 — `summarize_news()`
- 모델: `claude-haiku-4-5-20251001`
- **반드시 전체 기사를 1회 호출로 처리.** 기사당 1회 호출 금지
- 입력: 후보 20~30건의 `{title, description, press, published_at}` 배열
- 시스템 프롬프트 요지:
  > 구리/전기동 시황 관련성을 1~5로 평가하고, 관련 기사에 한해 한국어 2문장 요약을 작성한다. 경기도 구리시 등 지명 '구리'와 무관한 기사는 relevance 1로 매긴다. JSON 배열로만 응답한다.
- 출력: `[{index, relevance, summary}]` → 코드에서 원본과 병합 후 상위 10건 선별

### 5.3 데일리 코멘터리 — `write_commentary()`
- 모델: `claude-sonnet-5`
- 입력: 완성된 `sections` 전체 (시세·지표·뉴스·재고)
- 시스템 프롬프트 요지:
  > 전선/케이블 제조사 실무자를 위한 원자재 브리핑을 작성한다. headline 1줄, body 3~5문장, implication(원가 관점 시사점) 1줄. 주어진 데이터에 없는 수치나 사건은 절대 언급하지 않는다. 숫자는 입력값을 그대로 인용한다.
- 출력: `commentary` 스키마

### AI를 쓰면 안 되는 곳 (엄수)

| 항목 | 이유 |
|---|---|
| 변동률·증감 계산 | LLM은 산수를 틀립니다. **전부 Python으로** |
| HTML 렌더링 | Jinja2 고정 템플릿. 매일 AI 생성 금지 |
| 이상치 탐지 | 규칙 기반 (전일 대비 ±20% 초과 시 플래그) |
| 스케줄 분기·조건문 | 코드 |

**모든 AI 호출은 `try/except`로 감싸고, 실패해도 파이프라인이 계속 진행되어야 합니다.**
- 5.1 실패 → 재고 섹션 `failed`
- 5.2 실패 → 요약 없이 제목+링크만 노출
- 5.3 실패 → 코멘터리 섹션 생략

응답 파싱 시 ` ```json ` 코드펜스를 제거한 뒤 `json.loads`, 실패하면 1회 재시도.

---

## 6. 렌더링 & 발송

### 6.1 렌더링 (`render.py`)
- **Jinja2 단일 HTML 템플릿** (`templates/report.html.j2`)
- 인라인 CSS만 사용 (메일 클라이언트는 `<style>` 블록·외부 CSS를 자주 무시)
- 테이블 레이아웃 기반. Flexbox/Grid는 Outlook에서 깨집니다
- 상승=빨강, 하락=파랑 (한국 관례)
- `status`가 `stale`인 섹션은 회색조 + "N월 N일 기준 (갱신 실패)" 배지
- `status`가 `failed`인 섹션은 "수집 실패 — {사유}" 문구만 노출하고 섹션 자체는 유지
- 순서: **코멘터리 → 시세 → 재고 → 경제지표 → 뉴스** (결론 먼저)

### 6.2 발송 (`deliver.py`)
- Gmail SMTP (`smtp.gmail.com:587`, STARTTLS) + 앱 비밀번호
- 제목: `[일일 원자재] 8/18 구리 -1.2% / WTI +0.4% / USDKRW 1,382.50`
- 본문 HTML + `report.json`을 첨부

### 6.3 실패 알림 — 별도 채널
**가장 위험한 시나리오는 "메일이 안 온 걸 아무도 모르는 것"입니다.**
- Slack 또는 Teams Incoming Webhook으로 **성공/실패 양쪽 모두** 1줄 알림
- 리포트 메일 채널과 반드시 분리 (메일 발송 자체가 실패하면 메일로는 알릴 수 없음)

---

## 7. 스케줄링 (`.github/workflows/`)

**GitHub Actions cron은 정시에 실행되지 않습니다.** 부하에 따라 5~30분 지연이 흔합니다.
따라서 여유를 두고 트리거한 뒤 **스크립트 내부에서 목표 시각까지 대기**하세요.

### 7.1 `morning-collect.yml` — 선수집

```yaml
on:
  schedule:
    - cron: '30 0 * * 1-5'   # UTC 00:30 = KST 09:30
  workflow_dispatch:
```

- 재고 PDF, 경제지표, 뉴스 수집 → `data/cache/`에 저장 후 **커밋**
- **분리 이유:** PDF는 오전에 이미 게시됩니다. 오전에 받아두면 실패해도 재시도할 시간이 5시간 이상 확보됩니다. 무거운 크롤링이 16시 발송을 막지 못하게 하는 것이 목적입니다.

### 7.2 `daily-report.yml` — 조립·발송

```yaml
on:
  schedule:
    - cron: '40 5 * * 1-5'   # UTC 05:40 = KST 14:40
  workflow_dispatch:
```

실행 순서:
1. 스크립트 시작 → **KST 15:00:00까지 `sleep`** (Job 최대 6시간이므로 대기 비용 없음)
2. 시세 스냅샷 수집
3. `data/cache/`에서 오전 수집분 로드 (없으면 이 시점에 재시도)
4. 뉴스 최신화
5. AI 레이어 실행
6. 렌더링 → 발송
7. `data/` 커밋

목표: **15:00 스냅샷 → 16:00 발송**. 실제 파이프라인은 3~5분이면 끝나므로 여유는 충분합니다.

### 7.3 기타
- Private Repo 무료 티어 월 2,000분 이내에 충분히 들어갑니다
- `data/`를 매일 커밋하면 60일 무커밋 시 cron 자동 비활성화 문제도 함께 해결됩니다
- 커밋은 `github-actions[bot]` 명의, 메시지는 `chore: data {date}`

### 7.4 Secrets

```
NAVER_CLIENT_ID
NAVER_CLIENT_SECRET
ANTHROPIC_API_KEY
SMTP_USER
SMTP_APP_PASSWORD
MAIL_TO
ALERT_WEBHOOK_URL
```

---

## 8. 코딩 규칙 (엄수)

1. **부분 실패 허용 (최우선 원칙)**
   4개 수집기는 완전히 독립적으로 실행합니다. 하나가 실패해도 **예외를 위로 던지지 말고** 해당 섹션의 `status`를 낮추고 `errors`에 기록한 뒤 나머지를 계속 진행하세요.
   목표는 "완벽한 리포트"가 아니라 **"16시에 도착하는 리포트"**입니다. 전체 미발송이 최악의 결과입니다.

2. **캐시 폴백**
   모든 수집기의 성공 결과를 `data/cache/{section}_{date}.json`에 저장. 실패 시 가장 최근 성공값을 로드하고 `status: "stale"` 처리.

3. **재시도**
   모든 네트워크 호출에 `tenacity` 데코레이터 — 3회, 지수 백오프, 최대 30초.

4. **타임존**
   내부 연산은 **전부 UTC(`datetime.now(timezone.utc)`)**, 표시 시점에만 `ZoneInfo("Asia/Seoul")`로 변환. Actions 러너는 UTC입니다. **naive datetime 사용 금지.**

5. **휴장일**
   한국·미국 공휴일 및 주말 처리. "전일 대비"는 **직전 스냅샷 존재일** 기준(금→월 자동 처리). 하드코딩된 `-1 day` 금지.

6. **로깅**
   각 단계 시작/종료/소요시간을 구조화 로그로. 최종 `report.json`을 `data/reports/{date}.json`에 커밋해 사후 추적 가능하게 할 것.

7. **모듈 경계**
   `collect → normalize → enrich(AI) → render → deliver` 각 단계는 **파일로 중간 산출물을 남기고**, 단독 실행 가능해야 합니다. `python -m collectors.inventory` 만으로 테스트되어야 합니다.

8. **하드코딩 금지**
   URL·심볼·검색어·수신자는 전부 `config.py`에 상수로 분리.

9. **AI 응답 신뢰 금지**
   모든 AI 반환 JSON은 스키마 검증을 통과해야 합니다. 검증 실패는 성공이 아닙니다.

---

## 9. 산출물 구조

```
.
├── .github/workflows/
│   ├── morning-collect.yml
│   └── daily-report.yml
├── collectors/
│   ├── prices.py
│   ├── calendar.py
│   ├── news.py
│   └── inventory.py
├── ai/
│   ├── client.py          # Anthropic 클라이언트 + JSON 파싱 유틸
│   ├── extract.py         # 5.1
│   ├── summarize.py       # 5.2
│   └── commentary.py      # 5.3
├── templates/
│   └── report.html.j2
├── data/
│   ├── history/prices.csv
│   ├── cache/
│   └── reports/
├── config.py
├── schema.py              # 스키마 정의 + 검증
├── render.py
├── deliver.py
├── main.py                # 파이프라인 오케스트레이션
├── requirements.txt
├── .env.example
└── README.md              # 로컬 실행법 + Secrets 설정법
```

---

## 10. 작업 순서

**아래 순서를 지키세요. 역순으로 진행하지 마세요.**

### Step 0 — 리스크 검증 스파이크 (코드 작성 전 필수)
다음 3개를 각각 10줄 이내 스크립트로 확인하고 **결과를 보고**하세요:
1. `futures.co.kr` 게시물 목록이 `requests`만으로 파싱되는가?
2. investing.com 위젯 URL이 200을 반환하는가? (GitHub Actions IP에서도 확인)
3. `yfinance`로 `HG=F` 1분봉이 조회되는가?

**여기서 실패가 나오면 코드를 더 쓰지 말고 설계 변경을 논의합니다.**

### Step 1 — 스키마 + 템플릿
`schema.py` 확정 → **Mock 데이터로 `report.html.j2` 완성** → 렌더 결과를 눈으로 확인.
데이터가 없어도 최종 산출물 모양을 먼저 확정합니다.

### Step 2 — 수집기 4개
각각 독립 실행 가능하게. 각자 JSON을 뱉고 스키마 검증 통과.

### Step 3 — AI 레이어 3종
Mock 입력으로 각각 테스트.

### Step 4 — 오케스트레이션 + 폴백 + 알림
`main.py`에서 조립. 각 수집기를 일부러 실패시켜 **부분 실패 시에도 메일이 나가는지** 확인.

### Step 5 — Actions 배선
`workflow_dispatch`로 수동 실행 검증 후 cron 활성화.

---

## 11. 하지 말아야 할 것 (요약)

- ❌ Alpha Vantage / API-Ninjas로 시세 수집
- ❌ investing.com 일반 API 엔드포인트 호출
- ❌ 확인 없이 Playwright/Selenium 도입
- ❌ AI로 숫자 계산 또는 HTML 매일 생성
- ❌ 기사당 개별 AI 호출
- ❌ 수집 실패 시 전체 예외 발생 / 발송 중단
- ❌ naive datetime, 하드코딩된 날짜 오프셋
- ❌ 검증 없이 AI 반환값 신뢰
- ❌ 네이버에서 "구리" 단일 키워드 검색

---

## 12. 첫 응답에서 할 일

코드를 바로 쓰지 마세요. 먼저:
1. 이 지시서에서 **모호하거나 상충하는 부분**이 있으면 지적
2. **Step 0 스파이크**를 실행하고 결과 보고
3. 확인 후 Step 1부터 진행

준비되면 시작하세요.
재고데이터는 https://www.futures.co.kr/content/Getcontent.do?content=3000031 해당위치 게시물 활용
