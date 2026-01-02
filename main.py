import os
import time
import requests
import feedparser
from urllib.parse import quote_plus
from datetime import datetime, timezone, timedelta

# =========================
# 直近N日だけ送る
# =========================
RECENT_DAYS = 3
REQUEST_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (NewsBot/1.0)"

# =========================
# キーワード設計（あなた向け）
# =========================
ROLE_TERMS = [
    "施工管理", "現場監督", "設備管理", "施設管理", "ビルメン", "設備保全",
    "サブコン", "ゼネコン", "管工事", "電気工事", "空調", "衛生"
]

CANDIDATE_TERMS = [
    "転職", "求人", "採用", "中途", "人材紹介", "キャリア",
    "年収", "給与", "賃上げ", "残業", "休日", "週休2日", "有給",
    "働き方改革", "労働時間", "未経験", "経験者", "資格"
]

INDUSTRY_TERMS = [
    "2024年問題", "働き方改革", "時間外労働", "法改正", "建設業法", "下請",
    "人手不足", "高齢化", "価格転嫁", "資材高騰", "公共工事", "建設投資",
    "BIM", "CIM", "DX", "遠隔臨場",
    "省エネ", "ZEB", "脱炭素"
]

MAX_ARTICLES = 12  # 1回に送る最大件数

# =========================
# 取得元（指定5サイト）
# - RSSが安定なものは直RSS
# - それ以外は GoogleニュースRSSで site: しばり
# =========================
def google_news_rss(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ja&gl=JP&ceid=JP:ja"

SITE_FEEDS = [
    ("日経クロステック", [
        google_news_rss("site:xtech.nikkei.com 施工管理"),
        google_news_rss("site:xtech.nikkei.com 設備管理"),
        google_news_rss("site:xtech.nikkei.com 建設 人手不足"),
    ]),
    ("ダイヤモンド・オンライン", [
        google_news_rss("site:diamond.jp 施工管理"),
        google_news_rss("site:diamond.jp 設備管理"),
        google_news_rss("site:diamond.jp 建設 採用"),
    ]),
    ("NewsPicks", [
        google_news_rss("site:newspicks.com 施工管理"),
        google_news_rss("site:newspicks.com 設備管理"),
        google_news_rss("site:newspicks.com 建設 採用"),
    ]),
]

DIRECT_FEEDS = [
    ("ITmedia NEWS", ["https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml"]),
    ("東洋経済オンライン", ["https://toyokeizai.net/list/feed/header"]),
]

SOURCES = DIRECT_FEEDS + SITE_FEEDS

# =========================
# LINE送信（Secrets）
# =========================
LINE_TOKEN = os.getenv("LINE_CHANNEL_TOKEN")
LINE_TO = os.getenv("LINE_TO_USER_ID")

if not (LINE_TOKEN and LINE_TO):
    raise RuntimeError("Secrets不足: LINE_CHANNEL_TOKEN / LINE_TO_USER_ID を確認してください。")

def push_line(text: str) -> None:
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    body = {"to": LINE_TO, "messages": [{"type": "text", "text": text}]}
    r = requests.post(url, json=body, headers=headers, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

# =========================
# ユーティリティ
# =========================
def norm(s: str) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ").strip()
    while "  " in s:
        s = s.replace("  ", " ")
    return s

def count_hit(words, text: str) -> int:
    return sum(1 for w in words if w in text)

def get_published_dt(entry) -> datetime:
    t = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not t:
        # 日付が取れないものは古い扱い（直近だけにしたいので）
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return datetime(*t[:6], tzinfo=timezone.utc)

def is_recent(published_dt: datetime) -> bool:
    now = datetime.now(timezone.utc)
    return published_dt >= (now - timedelta(days=RECENT_DAYS))

def resolve_final_url(url: str) -> str:
    """
    Google NewsのリダイレクトURLを元記事URLに解決（生存確認も兼ねる）
    失敗したら空文字を返す。
    """
    try:
        r = requests.get(
            url,
            allow_redirects=True,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        if r.status_code >= 400:
            return ""
        # たまにGoogleの同意画面に飛ぶことがあるので、その場合は元のURLを返す
        if "consent.google.com" in (r.url or ""):
            return url
        return r.url or url
    except Exception:
        return ""

def split_for_line(message: str, limit: int = 4500):
    chunks, buf = [], ""
    for line in message.split("\n"):
        while len(line) > limit:
            head, line = line[:limit], line[limit:]
            if buf:
                chunks.append(buf); buf = ""
            chunks.append(head)
        if len(buf) + len(line) + 1 > limit:
            chunks.append(buf); buf = line
        else:
            buf = (buf + "\n" + line) if buf else line
    if buf:
        chunks.append(buf)
    return chunks

# =========================
# メイン（2カテゴリで送る）
# =========================
def main():
    items = []
    seen = set()

    for source_name, feed_urls in SOURCES:
        for feed_url in feed_urls:
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:50]:
                title = norm(entry.get("title", ""))
                raw_link = entry.get("link", "")
                summary = norm(entry.get("summary", "") or entry.get("description", ""))

                if not raw_link:
                    continue

                published = get_published_dt(entry)
                if not is_recent(published):
                    continue

                # URLを元記事に解決（死んでる/飛べない率を下げる）
                final_url = resolve_final_url(raw_link)
                if not final_url:
                    continue

                if final_url in seen:
                    continue

                text = f"{title} {summary}"

                role_score = count_hit(ROLE_TERMS, text)
                cand_score = count_hit(CANDIDATE_TERMS, text)
                ind_score = count_hit(INDUSTRY_TERMS, text)

                # 建設/設備の文脈が薄いものは落とす（ノイズ対策）
                if role_score == 0 and ind_score == 0:
                    continue

                items.append({
                    "source": source_name,
                    "title": title,
                    "link": final_url,
                    "summary": summary,
                    "published": published,
                    "role_score": role_score,
                    "cand_score": cand_score,
                    "ind_score": ind_score,
                })
                seen.add(final_url)

            time.sleep(0.2)

    if not items:
        push_line(f"✅ 直近{RECENT_DAYS}日で該当ニュースはありませんでした（建設/設備文脈のヒットなし）")
        return

    # A) 求職者向け：転職・待遇系を強く評価
    cand_items = sorted(
        items,
        key=lambda x: (x["cand_score"]*100 + x["role_score"]*20 + x["ind_score"]*5, x["published"]),
        reverse=True
    )

    # B) 業界理解：制度・市場・DX等を強く評価
    ind_items = sorted(
        items,
        key=lambda x: (x["ind_score"]*100 + x["role_score"]*20 + x["cand_score"]*5, x["published"]),
        reverse=True
    )

    cand_top = [x for x in cand_items if x["cand_score"] > 0][:6]
    ind_top  = [x for x in ind_items if x["ind_score"] > 0][:6]

    # 保険：どっちも空なら、役割語で拾えたものを送る
    if not cand_top and not ind_top:
        fallback = sorted(items, key=lambda x: (x["role_score"], x["published"]), reverse=True)[:6]
        msg = f"📰 直近{RECENT_DAYS}日：建設/設備ニュース（参考）\n"
        for it in fallback:
            summ = it["summary"][:220] + ("…" if len(it["summary"]) > 220 else "")
            msg += f"\n\n{it['title']}\n要旨：{summ}\nURL：{it['link']}\n"
        for chunk in split_for_line(msg):
            push_line(chunk); time.sleep(0.5)
        return

    lines = [f"🧑‍💼 直近{RECENT_DAYS}日：求職者向け（転職・待遇・働き方）"]
    for it in cand_top:
        summ = it["summary"][:220] + ("…" if len(it["summary"]) > 220 else "")
        lines.append(f"\n\n{it['title']}\n要旨：{summ}\nURL：{it['link']}")

    lines.append(f"\n🏗️ 直近{RECENT_DAYS}日：業界理解（制度・市場・DX・省エネ）")
    for it in ind_top:
        summ = it["summary"][:220] + ("…" if len(it["summary"]) > 220 else "")
        lines.append(f"\n\n{it['title']}\n要旨：{summ}\nURL：{it['link']}")

    msg = "\n".join(lines)[:18000]  # 暴走防止
    for chunk in split_for_line(msg):
        push_line(chunk)
        time.sleep(0.5)

if __name__ == "__main__":
    main()
