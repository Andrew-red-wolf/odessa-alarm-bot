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

# --- для тесту (не залежить від alerts.in.ua)
FORCE_STATE = None  # None = нормальна робота, True = тривога, False = відбій

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=20)

def fetch_alerts():
    r = requests.get(API_URL, params={"token": ALERTS_TOKEN}, timeout=20)
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
    global FORCE_STATE
    last_state = None
    alert_start_time = None

    while True:
        try:
            # 1) якщо ввімкнений тестовий режим — беремо FORCE_STATE
            if FORCE_STATE is not None:
                active = bool(FORCE_STATE)
            else:
                data = fetch_alerts()
                alerts = data.get("alerts", data if isinstance(data, list) else [])
                active = any(isinstance(a, dict) and is_odessa_alert(a) for a in alerts)

            # 2) логіка сповіщень
            if last_state is None:
                last_state = active
                if active:
                    alert_start_time = datetime.now()

            elif active and not last_state:
                alert_start_time = datetime.now()
                send_telegram(f"🚨 Одеса: ПОВІТРЯНА ТРИВОГА\n🕒 {alert_start_time.strftime('%H:%M:%S')}")
                last_state = True

            elif not active and last_state:
                end_time = datetime.now()
                duration = end_time - alert_start_time
                send_telegram(f"✅ Одеса: ВІДБІЙ\n⏱ Тривала: {format_duration(duration)}")
                last_state = False
                alert_start_time = None

        except Exception as e:
            print("Error:", e)

        time.sleep(POLL_SECONDS)

@app.route("/")
def home():
    return "Bot is running", 200

# --- ТЕСТОВІ КНОПКИ ---
@app.route("/test/on")
def test_on():
    global FORCE_STATE
    FORCE_STATE = True
    return "FORCE_STATE = True (test alarm ON). Wait up to 30s.", 200

@app.route("/test/off")
def test_off():
    global FORCE_STATE
    FORCE_STATE = False
    return "FORCE_STATE = False (test alarm OFF). Wait up to 30s.", 200

@app.route("/test/auto")
def test_auto():
    # Повертає до нормальної роботи через API
    global FORCE_STATE
    FORCE_STATE = None
    return "FORCE_STATE = None (back to real alerts).", 200

threading.Thread(target=worker, daemon=True).start()
