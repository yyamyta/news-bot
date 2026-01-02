import os
import time
import requests
import feedparser
from urllib.parse import quote_plus
from datetime import datetime, timezone

# =========================
# 1) フィルタ（求職者向けに絞り込み）
#    (転職系) AND (施工管理/設備管理系) を必須にする
# =========================
MUST_CAREER = [
    "転職", "求人", "採用", "中途", "人材紹介", "キャリア"
]

MUST_ROLE = [
    "施工管理", "現場監督", "設備管理", "施設管理", "ビルメン",
    "設備保全", "FM", "ファシリティ"
]

# あると“求職者向け価値”が高いので上位に並べる（必須ではない）
PRIORITY = [
    "年収", "給与", "賃上げ",
    "残業", "休日", "週休2日", "有給",
    "働き方改革", "労働時間",
    "未経験", "経験者", "資格",
]

MAX_ARTICLES_TO_SEND = 10
REQUEST_TIMEOUT = 20

# =========================
# 2) 取得元（指定5サイト）
#    - RSSがあるものは直RSS
#    - RSSが安定しない/提供されない可能性があるものはGoogleニュースRSSでサイト縛り
# =========================
def google_news_rss_url(query: str) -> str:
    # 日本向け設定（hl/gl/ceid）
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ja&gl=JP&ceid=JP:ja"

SOURCES = [
    # 直RSS（安定）
    ("ITmedia NEWS", "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml"),
    ("東洋経済オンライン", "https://toyokeizai.net/list/feed/header"),

    # GoogleニュースRSS（サイト縛り）
    ("日経クロステック", google_news_rss_url("site:xtech.nikkei.com")),
    ("ダイヤモンド・オンライン", google_news_rss_url("site:diamond.jp")),
    ("NewsPicks", google_news_rss_url("site:newspicks.com")),
]

# =========================
# 3) LINE送信（既存のSecretsを使う）
# =========================
LINE_TOKEN = os.getenv("LINE_CHANNEL_TOKEN")
LINE_TO = os.getenv("LINE_TO_USER_ID")

if not (LINE_TOKEN and LINE_TO):
    raise RuntimeError("Secrets不足: LINE_CHANNEL_TOKEN / LINE_TO_USER_ID を確認してください。")

def push_line(text: str) -> None:
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}",
    }
    body = {"to": LINE_TO, "messages": [{"type": "text", "text": text}]}
    r = requests.post(url, json=body, headers=headers, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

# =========================
# 4) ユーティリティ
# =========================
def norm(s: str) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ").strip()
    while "  " in s:
        s = s.replace("  ", " ")
    return s

def any_hit(words, text: str) -> bool:
    return any(w in text for w in words)

def count_hit(words, text: str) -> int:
    return sum(1 for w in words if w in text)

def get_published_dt(entry) -> datetime:
    # feedparserは published_parsed / updated_parsed があれば使える
    t = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not t:
        # 日付不明はかなり古い扱いにする
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return datetime(*t[:6], tzinfo=timezone.utc)

def split_for_line(message: str, limit: int = 4500):
    # LINEの文字数制限回避用（安全側で4500）
    chunks = []
    buf = ""
    for line in message.split("\n"):
        # 1行が長すぎる場合は切る
        while len(line) > limit:
            head, line = line[:limit], line[limit:]
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(head)
        if len(buf) + len(line) + 1 > limit:
            chunks.append(buf)
            buf = line
        else:
            buf = (buf + "\n" + line) if buf else line
    if buf:
        chunks.append(buf)
    return chunks

# =========================
# 5) メイン
# =========================
def main():
    items = []
    seen_urls = set()

    for source_name, feed_url in SOURCES:
        feed = feedparser.parse(feed_url)

        for entry in feed.entries[:50]:
            title = norm(entry.get("title", ""))
            link = entry.get("link", "")
            summary = norm(entry.get("summary", "") or entry.get("description", ""))

            if not link or link in seen_urls:
                continue

            text = f"{title} {summary}"

            # (転職系) AND (施工管理/設備管理系) を必須
            if not any_hit(MUST_CAREER, text):
                continue
            if not any_hit(MUST_ROLE, text):
                continue

            # スコア：求職者向けテーマ語が多いほど上に
            pr = count_hit(PRIORITY, text)
            role = count_hit(MUST_ROLE, text)
            career = count_hit(MUST_CAREER, text)
            score = pr * 100 + role * 10 + career

            published = get_published_dt(entry)

            items.append({
                "source": source_name,
                "title": title,
                "link": link,
                "summary": summary,
                "score": score,
                "published": published,
            })
            seen_urls.add(link)

        time.sleep(0.3)

    if not items:
        push_line("✅ 今日の該当ニュースはありませんでした（転職系 AND 施工管理/設備管理系）")
        return

    # スコア優先 → 新しい順
    items.sort(key=lambda x: (x["score"], x["published"]), reverse=True)
    items = items[:MAX_ARTICLES_TO_SEND]

    lines = ["🧑‍💼 求職者向け：転職×施工管理/設備管理（該当記事のみ）"]
    for it in items:
        summ = it["summary"][:220] + ("…" if len(it["summary"]) > 220 else "")
        lines.append(f"\n\n{it['title']}\n要旨：{summ}\nURL：{it['link']}")

    msg = "\n".join(lines)
    for chunk in split_for_line(msg):
        push_line(chunk)
        time.sleep(0.5)

if __name__ == "__main__":
    main()
