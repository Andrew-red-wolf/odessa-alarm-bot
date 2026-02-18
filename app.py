import os
import time
import threading
from datetime import datetime

import requests
from flask import Flask, jsonify

app = Flask(__name__)

TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
ALERTS_TOKEN = os.getenv("ALERTS_TOKEN")

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
API_URL = "https://api.alerts.in.ua/v1/alerts/active.json"

KEYWORDS = ["одеса", "м. одеса", "одеська міська", "одеська громада"]

# --- тестовий режим
FORCE_STATE = None  # None = реальні дані, True = тривога, False = відбій

# --- стан для статусу/тривалості
last_state = None
alert_start_time = None
last_check_ts = None


def send_telegram(text: str) -> bool:
    if not TG_TOKEN or not TG_CHAT_ID:
        print("Missing TG_TOKEN or TG_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=20)
        ok = r.ok
        if not ok:
            print("Telegram send failed:", r.status_code, r.text)
        return ok
    except Exception as e:
        print("Telegram send exception:", e)
        return False


def fetch_alerts():
    r = requests.get(API_URL, params={"token": ALERTS_TOKEN}, timeout=20)
    return r.json()


def is_odessa_alert(alert: dict) -> bool:
    if str(alert.get("alert_type", "")).lower() != "air_raid":
        return False

    title = str(alert.get("location_title", "")).lower()
    oblast = str(alert.get("location_oblast", "")).lower()

    if "одесь" not in oblast:
        return False

    return any(word in title for word in KEYWORDS)


def format_duration_seconds(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours} год {minutes} хв {secs} с"
    if minutes > 0:
        return f"{minutes} хв {secs} с"
    return f"{secs} с"


def worker():
    global FORCE_STATE, last_state, alert_start_time, last_check_ts

    while True:
        try:
            last_check_ts = time.time()

            # 1) визначаємо active
            if FORCE_STATE is not None:
                active = bool(FORCE_STATE)
            else:
                data = fetch_alerts()
                alerts = data.get("alerts", data if isinstance(data, list) else [])
                active = any(isinstance(a, dict) and is_odessa_alert(a) for a in alerts)

            # 2) логіка переходів
            if last_state is None:
                # перший запуск — фіксуємо стан, але не спамимо
                last_state = active
                if active:
                    alert_start_time = datetime.now()

            elif active and not last_state:
                alert_start_time = datetime.now()
                send_telegram(
                    f"🚨 Одеса: ПОВІТРЯНА ТРИВОГА\n🕒 {alert_start_time.strftime('%H:%M:%S')}"
                )
                last_state = True

            elif (not active) and last_state:
                end_time = datetime.now()
                if alert_start_time is None:
                    # якщо з якоїсь причини старту нема — просто відбій без тривалості
                    send_telegram(f"✅ Одеса: ВІДБІЙ\n🕒 {end_time.strftime('%H:%M:%S')}")
                else:
                    duration_s = int((end_time - alert_start_time).total_seconds())
                    send_telegram(
                        f"✅ Одеса: ВІДБІЙ\n⏱ Тривала: {format_duration_seconds(duration_s)}"
                    )

                last_state = False
                alert_start_time = None

        except Exception as e:
            print("Worker error:", e)

        time.sleep(POLL_SECONDS)


@app.route("/")
def home():
    return "Bot is running", 200


@app.route("/status")
def status():
    now_ts = time.time()
    return jsonify(
        ok=True,
        force_state=FORCE_STATE,
        last_state=last_state,
        alert_start_time=alert_start_time.isoformat() if alert_start_time else None,
        seconds_since_last_check=int(now_ts - last_check_ts) if last_check_ts else None,
    )


# --- ТЕСТ: одразу шле повідомлення + ставить FORCE_STATE ---
@app.route("/test/on")
def test_on():
    global FORCE_STATE, last_state, alert_start_time
    FORCE_STATE = True

    # якщо ще не було тривоги — зафіксувати старт і надіслати
    if last_state is not True:
        alert_start_time = datetime.now()
        sent = send_telegram(
            f"🧪 ТЕСТ\n🚨 Одеса: ПОВІТРЯНА ТРИВОГА\n🕒 {alert_start_time.strftime('%H:%M:%S')}"
        )
        last_state = True
    else:
        sent = send_telegram("🧪 ТЕСТ\n🚨 Тривога вже активна")
    return jsonify(force="ON", sent=sent), 200


@app.route("/test/off")
def test_off():
    global FORCE_STATE, last_state, alert_start_time
    FORCE_STATE = False

    end_time = datetime.now()
    if last_state is True and alert_start_time:
        duration_s = int((end_time - alert_start_time).total_seconds())
        sent = send_telegram(
            f"🧪 ТЕСТ\n✅ Одеса: ВІДБІЙ\n⏱ Тривала: {format_duration_seconds(duration_s)}"
        )
    else:
        sent = send_telegram(f"🧪 ТЕСТ\n✅ Одеса: ВІДБІЙ\n🕒 {end_time.strftime('%H:%M:%S')}")

    last_state = False
    alert_start_time = None
    return jsonify(force="OFF", sent=sent), 200


@app.route("/test/auto")
def test_auto():
    global FORCE_STATE
    FORCE_STATE = None
    sent = send_telegram("🧪 ТЕСТ\n🔁 Повернувся до реальних тривог (API)")
    return jsonify(force="AUTO", sent=sent), 200


@app.route("/test/ping")
def test_ping():
    sent = send_telegram("🧪 ПІНГ: бот живий ✅")
    return jsonify(ok=True, sent=sent), 200


threading.Thread(target=worker, daemon=True).start()
