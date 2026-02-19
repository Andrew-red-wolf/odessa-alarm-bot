import os
import time
import requests
from flask import Flask

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

API_URL = "https://api.alerts.in.ua/v1/alerts/active.json"
last_state = False
alert_start_time = None


def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": text
    }
    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print("Send error:", e)


def check_alert():
    global last_state, alert_start_time
    try:
        r = requests.get(API_URL, timeout=10)
        data = r.json()

        odessa_alert = False
        for region in data:
            if "Одеська" in region["name"] and region["alert"]:
                odessa_alert = True
                break

        if odessa_alert and not last_state:
            alert_start_time = time.time()
            send_message("🚨 ТРИВОГА в Одеській області!")

        if not odessa_alert and last_state and alert_start_time:
            duration = int(time.time() - alert_start_time)
            minutes = duration // 60
            send_message(f"✅ Відбій тривоги. Тривалість: {minutes} хв")

        last_state = odessa_alert

    except Exception as e:
        print("Check error:", e)


@app.route("/")
def home():
    return "Bot is alive"


@app.route("/check")
def manual_check():
    check_alert()
    return {"ok": True}


def loop():
    while True:
        check_alert()
        time.sleep(30)


if __name__ == "__main__":
    import threading
    threading.Thread(target=loop).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
