import os
import requests

# LINE トークンと userId は GitHub の秘密情報として後で設定します
CHANNEL_TOKEN = os.getenv("LINE_CHANNEL_TOKEN")
TO_USER_ID = os.getenv("LINE_TO_USER_ID")

message = "おはよう！ニュースBOTが動いています ☀️"

url = "https://api.line.me/v2/bot/message/push"
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {CHANNEL_TOKEN}"
}
body = {
    "to": TO_USER_ID,
    "messages": [
        {"type": "text", "text": message}
    ]
}

requests.post(url, json=body, headers=headers)
