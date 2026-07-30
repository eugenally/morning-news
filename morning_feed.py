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
    """Yahoo Finance 공개 API로 현재가와 전일 종가를 가져온다."""
    url = YAHOO_URL.format(urllib.parse.quote(symbol))
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=10, context=SSL_CONTEXT) as resp:
        data = json.load(resp)
    meta = data["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    return price, prev


GNEWS_URL = "https://news.google.com/rss/search?q={}&hl=ko&gl=KR&ceid=KR:ko"


def fetch_headlines(keyword, count=3, max_length=20):
    """Google 뉴스 RSS에서 키워드 헤드라인을 가져와 짧게 다듬는다."""
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
        # 끝의 " - 언론사" 꼬리표 제거
        if " - " in title:
            title = title.rsplit(" - ", 1)[0].strip()
        # 길면 max_length 이내로 자르고 … 표시
        if len(title) > max_length:
            title = title[: max_length - 1] + "…"
        key = title[:8]  # 앞부분이 같은 중복 기사 제거
        if key in seen:
            continue
        seen.add(key)
        out.append(title)
        if len(out) >= count:
            break
    return out


def fmt_number(value, decimals):
    return f"{value:,.{decimals}f}"


def display_width(text):
    """한글/전각 문자를 2칸으로 계산한 표시 폭."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def pad_right(text, width):
    return text + " " * max(0, width - display_width(text))


def pad_left(text, width):
    return " " * max(0, width - display_width(text)) + text


def build_message(config):
    now = datetime.now()
    date_line = f"{now.month}월 {now.day}일 ({WEEKDAYS_KR[now.weekday()]}) {now:%H:%M}"

    lines = [f"☀️ <b>{config.get('title', '굿모닝 브리핑')}</b>",
             f"<i>{date_line}</i>", ""]

    name_w = 10   # 종목명 열 폭 (표시 기준)
    price_w = 12  # 가격 열 폭
    for section in config["sections"]:
        rows = []
        for item in section["items"]:
            name = item["name"]
            try:
                price, prev = fetch_quote(item["symbol"])
                if price is None:
                    rows.append(f"{pad_right(name, name_w)}조회 실패")
                    continue
                prefix = item.get("prefix", "")
                price_str = prefix + fmt_number(price, item.get("decimals", 2))
                if prev:
                    diff = price - prev
                    pct = diff / prev * 100
                    arrow = "🔺" if diff > 0 else ("🔻" if diff < 0 else "▪️")
                    sign = "+" if diff > 0 else ""
                    change = f"{arrow}{sign}{pct:.2f}%"
                else:
                    change = ""
                rows.append(f"{pad_right(name, name_w)}{pad_left(price_str, price_w)}  {change}")
            except Exception as e:
                rows.append(f"{pad_right(name, name_w)}오류 ({type(e).__name__})")

        block = "\n".join(rows)
        lines.append(f"{section['emoji']} <b>{section['title']}</b>")
        lines.append(f"<pre>{block}</pre>")
        lines.append("")

    # 뉴스 브리핑 섹션 (선택)
    news = config.get("news")
    if news and news.get("topics"):
        count = news.get("count", 3)
        max_length = news.get("max_length", 20)
        lines.append(f"{news.get('emoji', '📰')} <b>{news.get('title', '뉴스 브리핑')}</b>")
        for topic in news["topics"]:
            label = topic.get("label", topic.get("keyword", ""))
            try:
                heads = fetch_headlines(topic["keyword"], count, max_length)
                if heads:
                    lines.append(f"▪️ <b>{html.escape(label, quote=False)}</b>")
                    for h in heads:
                        lines.append(f"  · {html.escape(h, quote=False)}")
                else:
                    lines.append(f"▪️ <b>{html.escape(label, quote=False)}</b>  (기사 없음)")
            except Exception as e:
                lines.append(f"▪️ <b>{html.escape(label, quote=False)}</b>  (오류: {type(e).__name__})")
        lines.append("")

    return "\n".join(lines).strip()


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

    message = build_message(config)

    if dry_run:
        # 콘솔 확인용: HTML 태그를 걷어내고 출력
        import re
        plain = re.sub(r"</?(b|i|pre)>", "", message)
        print(plain)
        return

    env = load_env(os.path.join(BASE_DIR, ".env"))
    token = env.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        sys.exit("오류: .env에 TELEGRAM_BOT_TOKEN 과 TELEGRAM_CHAT_ID 를 설정하세요. "
                 "(먼저 --dry-run 으로 테스트해볼 수 있습니다)")

    send_telegram(token, chat_id, message)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 전송 완료")


if __name__ == "__main__":
    main()
