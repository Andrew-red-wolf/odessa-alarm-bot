import os
import time
import threading
from datetime import datetime

import requests
from flask import Flask

app = Flask(__name__)

TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
ALERTS_TOKEN = os.getenv("ALERTS_TOKEN")

POLL_SECONDS = 30
API_URL = "https://api.alerts.in.ua/v1/alerts/active.json"

KEYWORDS = ["одеса", "м. одеса", "одеська міська", "одеська громада"]

def now():
    return datetime.now().strftime("%H:%M:%S")

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text})

def fetch_alerts():
    r = requests.get(API_URL, params={"token": ALERTS_TOKEN})
    return r.json()

def is_odessa_alert(alert):
    if str(alert.get("alert_type")).lower() != "air_raid":
        return False

    title = str(alert.get("location_title", "")).lower()
    oblast = str(alert.get("location_oblast", "")).lower()

    if "одесь" not in oblast:
        return False

    return any(word in title for word in KEYWORDS)

def format_duration(duration):
    total_seconds = int(duration.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60

    if hours > 0:
        return f"{hours} год {minutes} хв"
    else:
        return f"{minutes} хв"

def worker():
    last_state = None
    alert_start_time = None

    while True:
        try:
            data = fetch_alerts()
            alerts = data.get("alerts", data if isinstance(data, list) else [])

            active = any(isinstance(a, dict) and is_odessa_alert(a) for a in alerts)

            if last_state is None:
                last_state = active
                if active:
                    alert_start_time = datetime.now()

            elif active and not last_state:
                alert_start_time = datetime.now()
                send_telegram(
                    f"🚨 Одеса: ПОВІТРЯНА ТРИВОГА\n🕒 {alert_start_time.strftime('%H:%M:%S')}"
                )
                last_state = True

            elif not active and last_state:
                end_time = datetime.now()
                duration = end_time - alert_start_time

                send_telegram(
                    f"✅ Одеса: ВІДБІЙ\n"
                    f"⏱ Тривала: {format_duration(duration)}"
                )

                last_state = False
                alert_start_time = None

        except Exception as e:
            print("Error:", e)

        time.sleep(POLL_SECONDS)

@app.route("/")
def home():
    return "Bot is running", 200

threading.Thread(target=worker, daemon=True).start()
