import os
import time
import requests
import feedparser
import trafilatura
from openai import OpenAI

# =========================
# 1) あなた向けキーワード（施工管理・設備管理・建設×人材）
# =========================
KEYWORDS = [
    # 施工管理・設備管理
    "施工管理", "設備管理", "ビルメン", "施設管理", "FM", "現場監督",
    "電気工事施工管理", "管工事施工管理", "建築施工管理", "土木施工管理",
    "電気主任技術者", "監理技術者", "主任技術者", "技術士",
    "1級施工管理技士", "2級施工管理技士", "建築士",

    # 人材・転職市場（あなたの仕事に直結）
    "人手不足", "採用", "転職", "賃上げ", "初任給", "年収", "残業", "2024年問題",
    "働き方改革", "時間外労働", "週休2日", "36協定",
    "派遣", "外注", "協力会社", "下請法",

    # 建設DX
    "BIM", "CIM", "i-Construction", "DX", "現場DX", "遠隔臨場", "電子黒板",
    "積算", "原価管理", "工程管理",

    # 設備・省エネ（設備管理に強い武器）
    "省エネ", "ZEB", "ZEH", "脱炭素", "カーボンニュートラル", "BEMS",
    "空調", "HVAC", "冷凍機", "ボイラー", "消防設備", "防災", "点検", "法改正",

    # 発注側・用途（設備管理キャリアに刺さる）
    "データセンター", "工場", "プラント", "物流倉庫", "病院", "商業施設",
    "不動産管理", "PM", "BM", "AM", "REIT"
]

# =========================
# 2) 調整パラメータ（最初はこのままでOK）
# =========================
MAX_ARTICLES_TO_SEND = 6          # 1回に送る最大記事数（増やすと長文になります）
MAX_CHARS_FOR_SUMMARY = 6000      # AIに渡す本文の最大文字数（コストと安定性のため）
REQUEST_TIMEOUT = 20

# まずはRSSが比較的取りやすい2つから開始（安定稼働を優先）
# ※あとで5サイトに増やします
RSS_SOURCES = [
    ("ITmedia NEWS", "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml"),
    ("東洋経済オンライン", "https://toyokeizai.net/list/feed/header"),
]

# =========================
# 3) Secrets（GitHubに登録したものを読む）
# =========================
LINE_TOKEN = os.getenv("LINE_CHANNEL_TOKEN")
LINE_TO = os.getenv("LINE_TO_USER_ID")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

if not (LINE_TOKEN and LINE_TO and OPENAI_KEY):
    raise RuntimeError("Secrets不足: LINE_CHANNEL_TOKEN / LINE_TO_USER_ID / OPENAI_API_KEY を確認してください。")

client = OpenAI(api_key=OPENAI_KEY)

def keyword_hit(text: str) -> bool:
    t = text or ""
    return any(k in t for k in KEYWORDS)

def fetch_article_text(url: str) -> str:
    """
    できるだけ本文を取る。
    取れない（会員制・ブロック・構造的に難しい）場合は空文字。
    その場合はRSSの概要（snippet）を要約します。
    """
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        extracted = trafilatura.extract(downloaded)
        return extracted or ""
    except Exception:
        return ""

def summarize(title: str, material: str, url: str) -> str:
    """
    AI要約。必ず「結論/要点/リンク」形式で返す。
    """
    text = (material or "")[:MAX_CHARS_FOR_SUMMARY]
    prompt = f"""
あなたは建設業界（施工管理・設備管理）に特化したキャリアアドバイザーTLのためのニュース要約者です。
以下の記事を、日本語で「実務に役立つ視点」で短くまとめてください。

【記事タイトル】
{title}

【本文（または概要）】
{text}

【出力形式】必ずこの3行構成（余計な前置き不要）
結論：〜（1行）
要点：・〜 ・〜 ・〜（最大3つ）
リンク：{url}
""".strip()

    resp = client.responses.create(
        model="gpt-4o-mini",
        input=prompt,
    )
    return resp.output_text.strip()

def push_line(message: str) -> None:
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}",
    }
    body = {
        "to": LINE_TO,
        "messages": [{"type": "text", "text": message}],
    }
    r = requests.post(url, json=body, headers=headers, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

def main():
    picked = []

    # 1) RSS取得 → タイトル/概要で先にキーワード判定（高速で安定）
    for source_name, rss_url in RSS_SOURCES:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:30]:
            title = entry.get("title", "")
            link = entry.get("link", "")
            snippet = entry.get("summary", "") or entry.get("description", "") or ""
            if not link:
                continue
            if keyword_hit(title + " " + snippet):
                picked.append((source_name, title, link, snippet))

    if not picked:
        push_line("✅ 今日の該当ニュースはありませんでした（キーワード一致なし）")
        return

    # 2) 上限までに絞る
    picked = picked[:MAX_ARTICLES_TO_SEND]

    # 3) 本文取得→要約→まとめ
    lines = ["📰 今日のニュース要約（キーワード一致）"]
    for source_name, title, link, snippet in picked:
        body = fetch_article_text(link)
        material = body if body.strip() else snippet  # 本文が取れなければ概要で要約
        summary = summarize(title, material, link)
        lines.append(f"\n\n{summary}")
        time.sleep(1)  # 連続アクセスを少しだけゆっくりに

    # 4) LINE送信
    push_line("\n".join(lines))

if __name__ == "__main__":
    main()
