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

# Під Одесу / Одеську міську громаду (можна доповнювати)
KEYWORDS = ["одеса", "м. одеса", "одеська міська", "одеська громада", "одеська міська громада"]

# ====== STATE ======
LAST_STATE = None
ALERT_START_TIME = None


def send_telegram(text: str):
    """Надіслати повідомлення в Telegram."""
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
    """Забрати активні тривоги з alerts.in.ua."""
    if not ALERTS_TOKEN:
        raise RuntimeError("ALERTS_TOKEN is missing")

    r = requests.get(API_URL, params={"token": ALERTS_TOKEN}, timeout=20)
    r.raise_for_status()
    return r.json()


def is_odessa_alert(alert: dict) -> bool:
    """Фільтр: тільки повітряна тривога по Одеській області і з назвою під Одесу/громаду."""
    if str(alert.get("alert_type", "")).lower() != "air_raid":
        return False

    title = str(alert.get("location_title", "")).lower()
    oblast = str(alert.get("location_oblast", "")).lower()

    if "одесь" not in oblast:
        return False

    return any(word in title for word in KEYWORDS)


def format_duration(duration):
    """Формат тривалості: 'X год Y хв' або 'Y хв'."""
    total_seconds = int(duration.total_seconds())
    if total_seconds < 0:
        total_seconds = 0

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60

    if hours > 0:
        return f"{hours} год {minutes} хв"
    return f"{minutes} хв"


def worker():
    """Основний цикл: слідкує за станом тривоги і шле повідомлення при зміні."""
    global LAST_STATE, ALERT_START_TIME

    while True:
        try:
            data = fetch_alerts()
            alerts = data.get("alerts", data if isinstance(data, list) else [])

            active = any(isinstance(a, dict) and is_odessa_alert(a) for a in alerts)

            if LAST_STATE is None:
                # ініціалізація без спаму
                LAST_STATE = active
                if active:
                    ALERT_START_TIME = datetime.now()

            elif active and not LAST_STATE:
                # старт тривоги
                ALERT_START_TIME = datetime.now()
                send_telegram(
                    f"🚨 Одеса: ПОВІТРЯНА ТРИВОГА\n🕒 {ALERT_START_TIME.strftime('%H:%M:%S')}"
                )
                LAST_STATE = True

            elif (not active) and LAST_STATE:
                # відбій
                end_time = datetime.now()
                if ALERT_START_TIME is None:
                    ALERT_START_TIME = end_time

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


# ====== TEST ROUTES (НЕ залежать від worker і не ламаються через кілька воркерів gunicorn) ======
@app.route("/test/on")
def test_on():
    global LAST_STATE, ALERT_START_TIME
    ALERT_START_TIME = datetime.now()
    LAST_STATE = True
    send_telegram(f"🧪 ТЕСТ: ТРИВОГА\n🕒 {ALERT_START_TIME.strftime('%H:%M:%S')}")
    return "Sent TEST ON to Telegram.", 200


@app.route("/test/off")
def test_off():
    global LAST_STATE, ALERT_START_TIME
    end_time = datetime.now()

    if ALERT_START_TIME is None:
        ALERT_START_TIME = end_time

    duration = end_time - ALERT_START_TIME
    LAST_STATE = False
    ALERT_START_TIME = None

    send_telegram(f"🧪 ТЕСТ: ВІДБІЙ\n⏱ Тривала: {format_duration(duration)}")
    return "Sent TEST OFF to Telegram.", 200


@app.route("/test/reset")
def test_reset():
    global LAST_STATE, ALERT_START_TIME
    LAST_STATE = None
    ALERT_START_TIME = None
    return "State reset OK.", 200


# Запуск фонового потоку
threading.Thread(target=worker, daemon=True).start()
