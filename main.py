import os
import time
import requests
import feedparser
import trafilatura

# =========================
# 1) あなた向けキーワード（施工管理・設備管理・建設×人材）
# =========================
KEYWORDS = [
    # 施工管理・設備管理
    "施工管理", "設備管理", "ビルメン", "施設管理", "FM", "現場監督",
    "電気工事施工管理", "管工事施工管理", "建築施工管理", "土木施工管理",
    "電気主任技術者", "監理技術者", "主任技術者", "技術士",
    "1級施工管理技士", "2級施工管理技士", "建築士",

    # 人材・転職市場
    "人手不足", "採用", "転職", "賃上げ", "初任給", "年収", "残業", "2024年問題",
    "働き方改革", "時間外労働", "週休2日", "36協定",
    "派遣", "外注", "協力会社", "下請法",

    # 建設DX
    "BIM", "CIM", "i-Construction", "DX", "現場DX", "遠隔臨場", "電子黒板",
    "積算", "原価管理", "工程管理",

    # 設備・省エネ
    "省エネ", "ZEB", "ZEH", "脱炭素", "カーボンニュートラル", "BEMS",
    "空調", "HVAC", "冷凍機", "ボイラー", "消防設備", "防災", "点検", "法改正",

    # 発注側・用途
    "データセンター", "工場", "プラント", "物流倉庫", "病院", "商業施設",
    "不動産管理", "PM", "BM", "AM", "REIT"
]

# =========================
# 2) 調整（最初はこのままでOK）
# =========================
MAX_ARTICLES_TO_SEND = 10      # 1回に送る最大記事数
REQUEST_TIMEOUT = 20

# まずは安定してRSSが取れる2サイト（この後5サイトに増やせます）
RSS_SOURCES = [
    ("ITmedia NEWS", "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml"),
    ("東洋経済オンライン", "https://toyokeizai.net/list/feed/header"),
]

# =========================
# 3) Secrets（GitHubに登録したもの）
# =========================
LINE_TOKEN = os.getenv("LINE_CHANNEL_TOKEN")
LINE_TO = os.getenv("LINE_TO_USER_ID")

if not (LINE_TOKEN and LINE_TO):
    raise RuntimeError("Secrets不足: LINE_CHANNEL_TOKEN / LINE_TO_USER_ID を確認してください。")

def keyword_hit(text: str) -> bool:
    t = text or ""
    return any(k in t for k in KEYWORDS)

def normalize_text(s: str) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ").strip()
    while "  " in s:
        s = s.replace("  ", " ")
    return s

def try_fetch_body_preview(url: str, max_chars: int = 240) -> str:
    """
    可能なら本文を少しだけ取って“概要補強”に使う（無料・要約なし）。
    取れない場合は空文字。
    """
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        extracted = trafilatura.extract(downloaded)
        if not extracted:
            return ""
        extracted = normalize_text(extracted)
        return extracted[:max_chars]
    except Exception:
        return ""

def push_line(message: str) -> None:
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}",
    }
    body = {"to": LINE_TO, "messages": [{"type": "text", "text": message}]}
    r = requests.post(url, json=body, headers=headers, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

def main():
    picked = []

    # RSS取得 → タイトル＋概要でキーワード判定
    for source_name, rss_url in RSS_SOURCES:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:40]:
            title = entry.get("title", "")
            link = entry.get("link", "")
            snippet = entry.get("summary", "") or entry.get("description", "") or ""
            if not link:
                continue

            hay = f"{title} {snippet}"
            if keyword_hit(hay):
                picked.append((source_name, title, link, snippet))

    if not picked:
        push_line("✅ 今日の該当ニュースはありませんでした（キーワード一致なし）")
        return

    picked = picked[:MAX_ARTICLES_TO_SEND]

    lines = ["📰 今日の該当ニュース（無料版：タイトル＋概要＋URL）"]
    for source_name, title, link, snippet in picked:
        snippet = normalize_text(snippet)
        body_preview = try_fetch_body_preview(link)
        # “概要”が短い/空なら本文の冒頭を補足として使う
        preview = snippet if snippet else body_preview
        if body_preview and snippet and (len(snippet) < 80):
            preview = f"{snippet} / 本文冒頭: {body_preview}"
        elif body_preview and not snippet:
            preview = f"本文冒頭: {body_preview}"

        if preview:
            preview = preview[:260] + ("…" if len(preview) > 260 else "")

        lines.append(f"\n\n{title}\n概要：{preview}\nURL：{link}")
        time.sleep(0.5)

    push_line("\n".join(lines))

if __name__ == "__main__":
    main()
