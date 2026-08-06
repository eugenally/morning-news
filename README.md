# ☀️ 굿모닝 브리핑

아침 7시에 **증시 · 환율 · 코인 시세 + 뉴스 + AI 시장 분석**을 텔레그램으로 자동 전송하는 가벼운 스크립트입니다.

기본 브리핑(시세·뉴스)은 파이썬 표준 라이브러리만으로 동작합니다.
AI 분석 섹션을 쓰려면 `pip install anthropic` 과 API 키가 추가로 필요합니다 (선택).

## 구성

| 파일 | 설명 |
|---|---|
| `morning_feed.py` | 메인 스크립트 (시세 조회 → 메시지 구성 → 텔레그램 전송) |
| `config.json` | 추적할 종목/환율/코인 목록 (자유롭게 수정) |
| `.env` | 텔레그램 봇 토큰·채팅 ID (직접 생성, git 제외됨) |
| `run_feed.bat` | 작업 스케줄러용 실행 래퍼 |

## 1단계 · 텔레그램 봇 만들기

1. 텔레그램에서 **@BotFather** 검색 → `/newbot` → 이름 정하면 **봇 토큰** 발급
2. 방금 만든 봇과 대화방을 열고 아무 메시지나 한 번 보냄
3. 브라우저에서 아래 주소를 열어 `chat.id` 숫자 확인:
   `https://api.telegram.org/bot<봇토큰>/getUpdates`

> 봇 토큰과 채팅 ID는 비밀번호처럼 취급하세요. `.env`에만 넣고 공유하지 마세요.

## 2단계 · 설정 파일 만들기

`.env.example`을 복사해 `.env`로 저장하고 값을 채웁니다:

```
TELEGRAM_BOT_TOKEN=발급받은_토큰
TELEGRAM_CHAT_ID=확인한_채팅ID
```

### AI 시장 분석 켜기 (선택)

당일 시세와 뉴스를 Claude가 해석해 **오늘의 시장 이슈 5가지**를 브리핑에 넣어줍니다.

```bash
pip install anthropic
```

[console.anthropic.com](https://console.anthropic.com)에서 API 키를 발급받아 `.env`에 추가:

```
ANTHROPIC_API_KEY=발급받은_API_키
```

- 키가 없거나 호출에 실패하면 이 섹션만 빠지고 나머지 브리핑은 정상 전송됩니다.
- 사용 모델은 `config.json`의 `analysis.model`에서 변경할 수 있습니다.
- 분석은 주어진 시세·뉴스만 근거로 사실과 해석을 전달하며, 투자 권유는 하지 않습니다.
  **투자 판단의 근거로 삼지 마세요.**

## 3단계 · 테스트

```bash
python morning_feed.py --dry-run   # 전송 없이 콘솔 출력만
python morning_feed.py             # 실제 텔레그램 전송
```

## 4단계 · 아침 7시 자동 실행 (윈도우 작업 스케줄러)

관리자 권한 PowerShell에서 한 줄로 등록:

```powershell
schtasks /create /tn "MorningFeed" /tr "C:\02Workspaces\newsfeed\run_feed.bat" /sc daily /st 07:00 /f
```

- 등록 확인: `schtasks /query /tn "MorningFeed"`
- 지금 바로 실행 테스트: `schtasks /run /tn "MorningFeed"`
- 삭제: `schtasks /delete /tn "MorningFeed" /f`

실행 로그는 `feed.log`에 쌓입니다.

## 종목 바꾸기

`config.json`에서 심볼을 추가/삭제하면 됩니다. 심볼은 [Yahoo Finance](https://finance.yahoo.com) 기준:

- 증시 지수: `^KS11`(코스피), `^KQ11`(코스닥), `^GSPC`(S&P500), `^IXIC`(나스닥), `^N225`(닛케이)
- 환율: `USDKRW=X`, `JPYKRW=X`, `EURKRW=X`
- 코인: `BTC-USD`, `ETH-USD`, `SOL-USD`, `XRP-USD`
- 개별 종목: `AAPL`, `TSLA`, `005930.KS`(삼성전자) 등
