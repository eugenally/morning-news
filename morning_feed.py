"""
굿모닝 브리핑 - 아침 7시 증시/환율/코인 시세를 텔레그램으로 보내는 가벼운 스크립트.

의존성: 없음 (파이썬 표준 라이브러리만 사용)

사용법:
    python morning_feed.py            # 텔레그램으로 전송
    python morning_feed.py --dry-run  # 전송하지 않고 콘솔에만 출력 (테스트용)

설정:
    config.json  - 추적할 종목/환율/코인 목록
    .env         - TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (봇 토큰과 채팅 ID)
"""

import json
import sys
import os
import html
import unicodedata
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import ssl
from datetime import datetime

# 윈도우 콘솔(cp949)에서도 이모지/한글이 깨지지 않도록 UTF-8 강제
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def make_ssl_context():
    """SSL 인증서 검증용 컨텍스트.
    일부 윈도우 환경은 기본 인증서 저장소가 불완전해 검증에 실패하므로,
    certifi 번들이 있으면 그것을 우선 사용한다."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL_CONTEXT = make_ssl_context()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
UA = {"User-Agent": "Mozilla/5.0"}
WEEKDAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]


def load_env(path):
    """아주 단순한 .env 파서 (KEY=VALUE 한 줄씩)."""
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def fetch_quote(symbol):
    """Yahoo Finance 공개 API로 시세를 가져온다.

    반환: (현재가, 전일종가, 부가지표 dict)
    부가지표는 분석 입력용으로만 쓰이며 없을 수도 있다.
    """
    url = YAHOO_URL.format(urllib.parse.quote(symbol))
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=10, context=SSL_CONTEXT) as resp:
        data = json.load(resp)
    meta = data["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    extra = {
        "day_high": meta.get("regularMarketDayHigh"),
        "day_low": meta.get("regularMarketDayLow"),
        "w52_high": meta.get("fiftyTwoWeekHigh"),
        "w52_low": meta.get("fiftyTwoWeekLow"),
    }
    return price, prev, extra


GNEWS_URL = "https://news.google.com/rss/search?q={}&hl=ko&gl=KR&ceid=KR:ko"


def fetch_headlines(keyword, count=3):
    """Google 뉴스 RSS에서 키워드 헤드라인을 전체 제목으로 가져온다."""
    url = GNEWS_URL.format(urllib.parse.quote(keyword))
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=10, context=SSL_CONTEXT) as resp:
        root = ET.fromstring(resp.read())

    out = []
    seen = set()
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        # 끝의 " - 언론사" 꼬리표 제거 (같은 언론사가 두 번 붙어 오는 경우가 있어 반복 제거)
        if " - " in title:
            head, publisher = title.rsplit(" - ", 1)
            suffix = " - " + publisher
            while head.endswith(suffix):
                head = head[: -len(suffix)]
            title = head.strip()
        key = title[:8]  # 앞부분이 같은 중복 기사 제거
        if key in seen:
            continue
        seen.add(key)
        out.append(title)
        if len(out) >= count:
            break
    return out


def shorten(text, max_length):
    """표시용으로 길이를 줄이고 넘치면 … 를 붙인다."""
    return text if len(text) <= max_length else text[: max_length - 1] + "…"


def fmt_number(value, decimals):
    return f"{value:,.{decimals}f}"


def display_width(text):
    """한글/전각 문자를 2칸으로 계산한 표시 폭."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def pad_right(text, width):
    return text + " " * max(0, width - display_width(text))


def pad_left(text, width):
    return " " * max(0, width - display_width(text)) + text


def collect_market_data(config):
    """설정된 종목/환율/코인 시세를 한 번에 조회해 구조화된 형태로 돌려준다."""
    result = []
    for section in config["sections"]:
        items = []
        for item in section["items"]:
            row = {"name": item["name"], "symbol": item["symbol"],
                   "prefix": item.get("prefix", ""),
                   "decimals": item.get("decimals", 2)}
            try:
                price, prev, extra = fetch_quote(item["symbol"])
                row["price"] = price
                row["pct"] = (price - prev) / prev * 100 if (price and prev) else None
                row["extra"] = extra
            except Exception as e:
                row["price"] = None
                row["pct"] = None
                row["extra"] = {}
                row["error"] = type(e).__name__
            items.append(row)
        result.append({"title": section["title"], "emoji": section["emoji"],
                       "items": items})
    return result


def collect_topics(topics, count):
    """키워드 목록으로 헤드라인을 모은다."""
    out = []
    for topic in topics:
        label = topic.get("label", topic.get("keyword", ""))
        try:
            heads = fetch_headlines(topic["keyword"], count)
            out.append({"label": label, "headlines": heads})
        except Exception as e:
            out.append({"label": label, "headlines": [],
                        "error": type(e).__name__})
    return out


def collect_news(config):
    """브리핑에 표시할 키워드별 헤드라인을 모아 돌려준다."""
    news = config.get("news")
    if not news or not news.get("topics"):
        return []
    return collect_topics(news["topics"], news.get("count", 3))


def collect_context_news(config):
    """분석 입력 전용 시장 뉴스. 브리핑에는 표시하지 않는다."""
    analysis = config.get("analysis") or {}
    topics = analysis.get("news_topics")
    if not topics:
        return []
    return collect_topics(topics, analysis.get("news_count", 4))


def render_quote_row(row, name_w=10, price_w=12):
    if row["price"] is None:
        reason = row.get("error", "조회 실패")
        return f"{pad_right(row['name'], name_w)}{reason}"
    price_str = row["prefix"] + fmt_number(row["price"], row["decimals"])
    pct = row["pct"]
    if pct is None:
        change = ""
    else:
        arrow = "🔺" if pct > 0 else ("🔻" if pct < 0 else "▪️")
        sign = "+" if pct > 0 else ""
        change = f"{arrow}{sign}{pct:.2f}%"
    return f"{pad_right(row['name'], name_w)}{pad_left(price_str, price_w)}  {change}"


def build_message(config, market=None, news_data=None, issues=None):
    now = datetime.now()
    date_line = f"{now.month}월 {now.day}일 ({WEEKDAYS_KR[now.weekday()]}) {now:%H:%M}"

    lines = [f"☀️ <b>{config.get('title', '굿모닝 브리핑')}</b>",
             f"<i>{date_line}</i>", ""]

    if market is None:
        market = collect_market_data(config)
    if news_data is None:
        news_data = collect_news(config)

    for section in market:
        block = "\n".join(render_quote_row(row) for row in section["items"])
        lines.append(f"{section['emoji']} <b>{section['title']}</b>")
        lines.append(f"<pre>{block}</pre>")
        lines.append("")

    # AI 시장 분석 섹션 (선택)
    if issues:
        lines.append("🧠 <b>오늘의 시장 이슈 5</b>")
        lines.append("")
        for i, issue in enumerate(issues, 1):
            title = html.escape(issue.get("title", ""), quote=False)
            detail = html.escape(issue.get("detail", ""), quote=False)
            watch = html.escape(issue.get("watch", ""), quote=False)
            lines.append(f"<b>{i}. {title}</b>")
            if detail:
                lines.append(detail)
            if watch:
                lines.append(f"<i>👀 {watch}</i>")
            lines.append("")

    # 뉴스 브리핑 섹션 (선택)
    news_cfg = config.get("news") or {}
    if news_data:
        emoji = news_cfg.get("emoji", "📰")
        title = news_cfg.get("title", "뉴스 브리핑")
        max_length = news_cfg.get("max_length", 20)
        lines.append(f"{emoji} <b>{title}</b>")
        for topic in news_data:
            label = html.escape(topic["label"], quote=False)
            if topic.get("error"):
                lines.append(f"▪️ <b>{label}</b>  (오류: {topic['error']})")
            elif topic["headlines"]:
                lines.append(f"▪️ <b>{label}</b>")
                for h in topic["headlines"]:
                    short = html.escape(shorten(h, max_length), quote=False)
                    lines.append(f"  · {short}")
            else:
                lines.append(f"▪️ <b>{label}</b>  (기사 없음)")
        lines.append("")

    return "\n".join(lines).strip()


ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "이슈를 한 줄로 요약한 제목. 한국어 35자 이내.",
                    },
                    "detail": {
                        "type": "string",
                        "description": (
                            "무슨 일이 일어났는지 + 왜 그런지 + 무엇을 시사하는지를 "
                            "설명하는 2~3개 문장. 한국어 120~200자. "
                            "근거가 되는 구체적 수치를 반드시 포함."
                        ),
                    },
                    "watch": {
                        "type": "string",
                        "description": (
                            "이 이슈와 관련해 앞으로 지켜볼 지점 한 문장. 한국어 50자 이내."
                        ),
                    },
                },
                "required": ["title", "detail", "watch"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["issues"],
    "additionalProperties": False,
}

ANALYSIS_SYSTEM = """당신은 한국 투자자를 위한 아침 시장 브리핑을 쓰는 애널리스트입니다.
주어진 당일 시세와 뉴스만 근거로, 오늘 시장에서 주목할 이슈 5가지를 뽑습니다.

# 무엇을 이슈로 고를 것인가
단순히 "많이 올랐다/내렸다"를 나열하지 마세요. 다음을 우선합니다.
- 자산 간 연결: 환율과 증시, 원자재와 코인처럼 함께 움직이거나 반대로 움직인 조합
- 이례적인 움직임: 52주 고저 대비 위치, 당일 변동폭이 유난히 큰 자산
- 엇갈림: 같은 성격의 자산인데 방향이 다른 경우(예: 코스피는 하락, 코스닥은 상승)
- 시세와 뉴스가 맞물리는 지점: 헤드라인이 특정 자산 움직임을 설명하는 경우
- 조용하지만 누적되는 흐름: 폭은 작아도 방향이 일관된 자산

# 어떻게 쓸 것인가
- detail은 "무슨 일이 있었나 → 왜 그런가 → 무엇을 시사하나" 순서로 2~3문장.
- 반드시 구체적 수치를 인용하세요. "크게 올랐다"가 아니라 "2.04% 올라 3,900선"처럼 씁니다.
- 인과를 단정하지 마세요. 자료로 확인되지 않으면 "~로 보인다", "~와 맞물린다"로 씁니다.
- 5가지 이슈는 서로 다른 자산군이나 다른 주제를 다룹니다. 같은 이야기를 반복하지 마세요.

# 지켜야 할 선
- 주어진 자료에 없는 수치, 사건, 발언을 지어내지 마세요. 모르면 쓰지 않습니다.
- 뉴스 헤드라인은 제목뿐이며 본문을 보지 않았습니다. 제목이 말하는 것 이상으로 단정하지 마세요.
- 투자 권유·매매 조언(사라/팔아라, 목표가, 비중 조절)은 절대 쓰지 마세요.
  무슨 일이 있었고 무엇을 지켜볼지까지만 씁니다."""


def format_data_for_analysis(market, news_data, context_news=None):
    """수집한 데이터를 모델에 넘길 텍스트로 정리한다."""
    now = datetime.now()
    parts = [f"기준 시각: {now:%Y-%m-%d %H:%M} (한국시간)", "", "[당일 시세]"]
    for section in market:
        parts.append(f"# {section['title']}")
        for row in section["items"]:
            if row["price"] is None:
                continue
            d = row["decimals"]
            price = row["prefix"] + fmt_number(row["price"], d)
            pct = "N/A" if row["pct"] is None else f"{row['pct']:+.2f}%"
            line = f"- {row['name']}: {price} (전일대비 {pct}"

            extra = row.get("extra") or {}
            hi, lo = extra.get("day_high"), extra.get("day_low")
            if hi and lo and row["price"]:
                # 당일 변동폭과, 그 안에서 현재가가 어디에 있는지
                span = (hi - lo) / row["price"] * 100
                line += f", 당일 변동폭 {span:.2f}%"
            w_hi, w_lo = extra.get("w52_high"), extra.get("w52_low")
            if w_hi and w_lo and w_hi > w_lo and row["price"]:
                pos = (row["price"] - w_lo) / (w_hi - w_lo) * 100
                line += f", 52주 범위 내 위치 {pos:.0f}%"
            parts.append(line + ")")

    def add_news(header, data):
        if not data:
            return
        parts.append("")
        parts.append(header)
        for topic in data:
            if not topic["headlines"]:
                continue
            parts.append(f"# {topic['label']}")
            for h in topic["headlines"]:
                parts.append(f"- {h}")

    add_news("[시장 관련 뉴스 헤드라인]", context_news)
    add_news("[그 밖의 뉴스 헤드라인]", news_data)

    parts.append("")
    parts.append(
        "참고: '52주 범위 내 위치'는 0%가 52주 최저가, 100%가 52주 최고가입니다."
    )
    return "\n".join(parts)


def analyze_market(market, news_data, api_key, model="claude-opus-5",
                   context_news=None, effort="high"):
    """Claude로 당일 시장 변화를 해석해 핵심 이슈 5가지를 뽑는다."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=ANALYSIS_SYSTEM,
        output_config={
            "format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA},
            "effort": effort,
        },
        messages=[{
            "role": "user",
            "content": (
                f"{format_data_for_analysis(market, news_data, context_news)}\n\n"
                "위 자료를 바탕으로 오늘 주목할 이슈를 정확히 5가지 뽑아주세요. "
                "자산 간 연결과 이례적인 움직임을 먼저 찾아보고, "
                "각 이슈마다 근거가 되는 수치를 인용해 주세요."
            ),
        }],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("모델이 응답을 거부했습니다")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)["issues"][:5]


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=payload)
    with urllib.request.urlopen(req, timeout=15, context=SSL_CONTEXT) as resp:
        result = json.load(resp)
    if not result.get("ok"):
        raise RuntimeError(f"텔레그램 전송 실패: {result}")
    return result


def main():
    dry_run = "--dry-run" in sys.argv

    with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
        config = json.load(f)

    env = load_env(os.path.join(BASE_DIR, ".env"))

    def setting(key):
        return env.get(key) or os.environ.get(key)

    market = collect_market_data(config)
    news_data = collect_news(config)

    # AI 시장 분석 (API 키가 있을 때만; 실패해도 브리핑 자체는 계속 전송)
    issues = None
    analysis = config.get("analysis", {})
    api_key = setting("ANTHROPIC_API_KEY")
    if analysis.get("enabled", True) and api_key:
        try:
            issues = analyze_market(
                market, news_data, api_key,
                model=analysis.get("model", "claude-opus-5"),
                context_news=collect_context_news(config),
                effort=analysis.get("effort", "high"),
            )
        except Exception as e:
            print(f"[경고] 시장 분석 실패: {type(e).__name__}: {e}", file=sys.stderr)

    message = build_message(config, market, news_data, issues)

    if dry_run:
        # 콘솔 확인용: HTML 태그와 엔티티를 실제 표시와 같게 되돌려 출력
        import re
        plain = html.unescape(re.sub(r"</?(b|i|pre)>", "", message))
        print(plain)
        return

    token = setting("TELEGRAM_BOT_TOKEN")
    chat_id = setting("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        sys.exit("오류: .env에 TELEGRAM_BOT_TOKEN 과 TELEGRAM_CHAT_ID 를 설정하세요. "
                 "(먼저 --dry-run 으로 테스트해볼 수 있습니다)")

    send_telegram(token, chat_id, message)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 전송 완료")


if __name__ == "__main__":
    main()
