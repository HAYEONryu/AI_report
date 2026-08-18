# 일일 원자재 리포트

매일 KST 15:50에 로컬 PC에서 실행되어, 구리/WTI/USD-KRW 시세(15:00 스냅샷) + 미국·중국 경제지표
+ 구리 관련 뉴스 + LME/COMEX 재고를 모아 AI로 코멘터리를 붙인 뒤 이메일로 발송합니다.

전체 설계는 [SPEC.md](SPEC.md), 실행/테스트 방법은 [test.md](test.md)를 참고하세요. 이 문서는 요약만 담습니다.

## 빠른 시작 (로컬)

```bash
pip install -r requirements.txt
cp .env.example .env   # 값 채우기 (아래 표 참고)
python main.py --now   # 15:00 대기 없이 즉시 실행
```

## 필요한 값 (`.env`)

| 변수 | 용도 |
|---|---|
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 뉴스 검색 |
| `OPENAI_API_KEY` | 재고 구조화 / 뉴스 요약 / 코멘터리 생성 |
| `SMTP_USER` / `SMTP_APP_PASSWORD` | 메일 발송 (`mail.ihoban.co.kr:587`) |
| `MAIL_TO` | 수신자 |
| `CALENDAR_PROXY_URL` | investing.com 프록시 (Cloudflare Worker, GH Actions 전용 — 로컬은 없어도 됨) |
| `ALERT_WEBHOOK_URL` | 선택. 성공/실패 알림 웹훅 |

## 자동 실행 방식

- **평일 15:50 KST**: Windows 작업 스케줄러(`AI_Report_Daily`) → `scripts/run_daily.ps1` →
  `python main.py --now` → 결과를 `data/`에 커밋·푸시. 메일 서버가 사내망 전용이라 이 PC가
  사내망/VPN에 연결된 상태여야 발송됩니다.
- **평일 09:30 KST**: GitHub Actions(`morning-collect.yml`)가 경제지표/뉴스/재고 캐시를 미리
  수집해 `data/cache/`에 커밋 — 오후 실행이 캐시를 재사용해 더 빠르고 안정적입니다.

## 구조

```
collectors/   시세·경제지표·뉴스·재고 수집기 (각각 python -m collectors.X로 단독 실행 가능)
ai/           OpenAI 호출 레이어 (추출/요약/코멘터리)
templates/    이메일 HTML 템플릿
main.py       전체 파이프라인 오케스트레이션
deliver.py    SMTP 발송 + 웹훅 알림
mailtest.py   SMTP 연결/인증만 따로 테스트
config.py     URL·모델명·수신자 등 상수
schema.py     리포트 JSON 스키마 + 검증
```

## 문제 해결

- 특정 모듈만 테스트하고 싶으면 `test.md` 참고
- 메일 인증 문제는 `python mailtest.py [아이디]`로 격리 테스트 (계정 잠금 방지를 위해 자동 재시도 없음)
