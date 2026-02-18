import os
import time
import threading
from datetime import datetime

import requests
from flask import Flask

app = Flask(__name__)

# ====== ENV ======
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
ALERTS_TOKEN = os.getenv("ALERTS_TOKEN")

# ====== SETTINGS ======
POLL_SECONDS = 30
API_URL = "https://api.alerts.in.ua/v1/alerts/active.json"

# Під Одесу/Одеську міську громаду (можна доповнювати)
KEYWORDS = ["одеса", "м. одеса", "одеська міська", "одеська громада", "одеська міська громада"]

# ====== TEST SWITCH ======
# None = реальні дані з alerts.in.ua
# True = примусово "тривога"
# False = примусово "відбій"
FORCE_STATE = None

# ====== STATE ======
LAST_STATE = None
ALERT_START_TIME = None


def send_telegram(text: str):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("TG_TOKEN or TG_CHAT_ID is missing")
        return

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=20)
        if r.status_code != 200:
            print("Telegram error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram send exception:", e)


def fetch_alerts():
    if not ALERTS_TOKEN:
        raise RuntimeError("ALERTS_TOKEN is missing")

    r = requests.get(API_URL, params={"token": ALERTS_TOKEN}, timeout=20)
    r.raise_for_status()
    return r.json()


def is_odessa_alert(alert: dict) -> bool:
    # Тип тривоги: повітряна
    if str(alert.get("alert_type", "")).lower() != "air_raid":
        return False

    title = str(alert.get("location_title", "")).lower()
    oblast = str(alert.get("location_oblast", "")).lower()

    # тільки Одеська область
    if "одесь" not in oblast:
        return False

    # фільтр саме під місто/громаду
    return any(word in title for word in KEYWORDS)


def format_duration(duration):
    total_seconds = int(duration.total_seconds())
    if total_seconds < 0:
        total_seconds = 0

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60

    if hours > 0:
        return f"{hours} год {minutes} хв"
    return f"{minutes} хв"


def worker():
    global FORCE_STATE, LAST_STATE, ALERT_START_TIME

    while True:
        try:
            # 1) Визначаємо active
            if FORCE_STATE is not None:
                active = bool(FORCE_STATE)
            else:
                data = fetch_alerts()
                alerts = data.get("alerts", data if isinstance(data, list) else [])
                active = any(isinstance(a, dict) and is_odessa_alert(a) for a in alerts)

            # 2) Логіка переходів
            if LAST_STATE is None:
                LAST_STATE = active
                if active:
                    ALERT_START_TIME = datetime.now()

            elif active and not LAST_STATE:
                ALERT_START_TIME = datetime.now()
                send_telegram(
                    f"🚨 Одеса: ПОВІТРЯНА ТРИВОГА\n🕒 {ALERT_START_TIME.strftime('%H:%M:%S')}"
                )
                LAST_STATE = True

            elif (not active) and LAST_STATE:
                end_time = datetime.now()
                if ALERT_START_TIME is None:
                    ALERT_START_TIME = end_time  # на всяк випадок

                duration = end_time - ALERT_START_TIME
                send_telegram(
                    f"✅ Одеса: ВІДБІЙ\n⏱ Тривала: {format_duration(duration)}"
                )
                LAST_STATE = False
                ALERT_START_TIME = None

        except Exception as e:
            print("Worker error:", e)

        time.sleep(POLL_SECONDS)


@app.route("/")
def home():
    return "Bot is running", 200


# ====== TEST ROUTES ======
@app.route("/test/on")
def test_on():
    global FORCE_STATE, LAST_STATE, ALERT_START_TIME
    FORCE_STATE = True
    LAST_STATE = False
    ALERT_START_TIME = None
    return "Test ON set (forced alarm). Wait up to 30s.", 200


@app.route("/test/off")
def test_off():
    global FORCE_STATE, LAST_STATE
    FORCE_STATE = False
    LAST_STATE = True
    return "Test OFF set (forced all-clear). Wait up to 30s.", 200


@app.route("/test/auto")
def test_auto():
    global FORCE_STATE, LAST_STATE, ALERT_START_TIME
    FORCE_STATE = None
    LAST_STATE = None
    ALERT_START_TIME = None
    return "Back to real alerts (FORCE_STATE=None).", 200


threading.Thread(target=worker, daemon=True).start()
