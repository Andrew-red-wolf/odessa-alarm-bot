import os
import time
import threading
from datetime import datetime

import requests
from flask import Flask, jsonify

app = Flask(__name__)

TG_TOKEN = os.getenv("TG_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")
ALERTS_TOKEN = os.getenv("ALERTS_TOKEN", "")

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
API_URL = "https://api.alerts.in.ua/v1/alerts/active.json"

KEYWORDS = ["одеса", "м. одеса", "одеська міська", "одеська громада"]

# None = робота по API, True = тривога, False = відбій
FORCE_STATE = None

# для статусу
last_state = None
alert_start_time = None
last_error = None
last_check_ts = 0


def tg_url(method: str) -> str:
    return f"https://api.telegram.org/bot{TG_TOKEN}/{method}"


def send_telegram(text: str):
    """
    Повертає (ok: bool, info: dict)
    """
    global last_error
    if not TG_TOKEN or not TG_CHAT_ID:
        last_error = "Missing TG_TOKEN or TG_CHAT_ID"
        return False, {"error": last_error}

    try:
        r = requests.post(
            tg_url("sendMessage"),
            json={"chat_id": TG_CHAT_ID, "text": text, "disable_web_page_preview": True},
            timeout=20,
        )
        data = r.json()
        if not data.get("ok"):
            # тут буде реальна причина: chat not found / forbidden / etc.
            last_error = f"Telegram error: {data}"
            return False, data
        return True, data
    except Exception as e:
        last_error = f"Telegram exception: {e}"
        return False, {"exception": str(e)}


def fetch_alerts():
    if not ALERTS_TOKEN:
        raise RuntimeError("Missing ALERTS_TOKEN")
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


def format_duration(duration):
    total_seconds = int(duration.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0:
        return f"{hours} год {minutes} хв"
    return f"{minutes} хв"


def worker():
    global FORCE_STATE, last_state, alert_start_time, last_check_ts, last_error

    while True:
        try:
            last_check_ts = int(time.time())

            # режим тесту
            if FORCE_STATE is not None:
                active = bool(FORCE_STATE)
            else:
                data = fetch_alerts()
                alerts = data.get("alerts", data if isinstance(data, list) else [])
                active = any(isinstance(a, dict) and is_odessa_alert(a) for a in alerts)

            # логіка сповіщень
            if last_state is None:
                last_state = active
                if active:
                    alert_start_time = datetime.now()

            elif active and not last_state:
                alert_start_time = datetime.now()
                send_telegram(f"🚨 Одеса: ПОВІТРЯНА ТРИВОГА\n🕒 {alert_start_time.strftime('%H:%M:%S')}")
                last_state = True

            elif (not active) and last_state:
                end_time = datetime.now()
                duration = end_time - (alert_start_time or end_time)
                send_telegram(f"✅ Одеса: ВІДБІЙ\n⏱ Тривала: {format_duration(duration)}")
                last_state = False
                alert_start_time = None

            last_error = None

        except Exception as e:
            last_error = f"Worker exception: {e}"

        time.sleep(POLL_SECONDS)


@app.route("/")
def home():
    return "Bot is running", 200


@app.route("/status")
def status():
    now = int(time.time())
    return jsonify({
        "ok": True,
        "tg_chat_id": TG_CHAT_ID,
        "force_state": FORCE_STATE,
        "last_state": last_state,
        "alert_start_time": alert_start_time.isoformat() if alert_start_time else None,
        "last_error": last_error,
        "seconds_since_last_check": (now - last_check_ts) if last_check_ts else None,
    })


@app.route("/test/on")
def test_on():
    global FORCE_STATE
    FORCE_STATE = True
    ok, info = send_telegram("🚨 ТЕСТ: ТРИВОГА (FORCE ON)")
    return jsonify({"force": "ON", "sent": ok, "tg_response": info})


@app.route("/test/off")
def test_off():
    global FORCE_STATE
    FORCE_STATE = False
    ok, info = send_telegram("✅ ТЕСТ: ВІДБІЙ (FORCE OFF)")
    return jsonify({"force": "OFF", "sent": ok, "tg_response": info})


@app.route("/test/auto")
def test_auto():
    global FORCE_STATE
    FORCE_STATE = None
    return jsonify({"force": None, "ok": True})


threading.Thread(target=worker, daemon=True).start()
