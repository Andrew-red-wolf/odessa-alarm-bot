import os
import time
import threading
from datetime import datetime

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
ALERTS_TOKEN = os.getenv("ALERTS_TOKEN")

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
API_URL = "https://api.alerts.in.ua/v1/alerts/active.json"

KEYWORDS = ["одеса", "м. одеса", "одеська міська", "одеська громада"]

# None = нормальна робота, True = тривога, False = відбій
FORCE_STATE = None

# Стан для тривалості
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
        ok = r.status_code == 200 and r.json().get("ok") is True
        if not ok:
            print("Telegram error:", r.status_code, r.text)
        return ok
    except Exception as e:
        print("Telegram exception:", e)
        return False

def fetch_alerts():
    if not ALERTS_TOKEN:
        raise RuntimeError("Missing ALERTS_TOKEN")
    r = requests.get(API_URL, params={"token": ALERTS_TOKEN}, timeout=20)
    r.raise_for_status()
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
    if seconds < 0:
        seconds = 0
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours} год {minutes} хв"
    return f"{minutes} хв"

def set_state(active: bool, source: str = "auto") -> None:
    """Єдина точка зміни стану, щоб не було розсинхрону."""
    global last_state, alert_start_time

    if last_state is None:
        last_state = active
        if active:
            alert_start_time = datetime.now()
        return

    # Тривога почалась
    if active and not last_state:
        alert_start_time = datetime.now()
        send_telegram(f"🚨 Одеса: ПОВІТРЯНА ТРИВОГА\n🕒 {alert_start_time.strftime('%H:%M:%S')}\n({source})")
        last_state = True
        return

    # Відбій
    if (not active) and last_state:
        end_time = datetime.now()
        dur = 0
        if alert_start_time:
            dur = int((end_time - alert_start_time).total_seconds())
        send_telegram(f"✅ Одеса: ВІДБІЙ\n⏱ Тривала: {format_duration_seconds(dur)}\n({source})")
        last_state = False
        alert_start_time = None
        return

def worker():
    global FORCE_STATE, last_check_ts
    print("Worker started. Poll:", POLL_SECONDS)

    while True:
        try:
            last_check_ts = int(time.time())

            # test mode
            if FORCE_STATE is not None:
                active = bool(FORCE_STATE)
                set_state(active, source="test")
            else:
                data = fetch_alerts()
                alerts = data.get("alerts", data if isinstance(data, list) else [])
                active = any(isinstance(a, dict) and is_odessa_alert(a) for a in alerts)
                set_state(active, source="api")

        except Exception as e:
            print("Worker error:", e)

        time.sleep(POLL_SECONDS)

@app.route("/")
def home():
    return "Bot is running", 200

@app.route("/health")
def health():
    now_ts = int(time.time())
    since = None if last_check_ts is None else (now_ts - last_check_ts)
    return jsonify({
        "ok": True,
        "force_state": FORCE_STATE,
        "last_state": last_state,
        "alert_start_time": None if alert_start_time is None else alert_start_time.isoformat(),
        "seconds_since_last_check": since
    })

@app.route("/test/ping")
def test_ping():
    sent = send_telegram("✅ TEST: ping")
    return jsonify({"ok": True, "sent": sent})

@app.route("/test/on")
def test_on():
    global FORCE_STATE
    FORCE_STATE = True
    # одразу шлемо
    set_state(True, source="test/on")
    return jsonify({"force": "ON", "sent": True})

@app.route("/test/off")
def test_off():
    global FORCE_STATE
    FORCE_STATE = False
    # одразу шлемо
    set_state(False, source="test/off")
    return jsonify({"force": "OFF", "sent": True})

@app.route("/test/auto")
def test_auto():
    global FORCE_STATE
    FORCE_STATE = None
    return jsonify({"force": "AUTO"})

# стартуємо потік один раз
threading.Thread(target=worker, daemon=True).start()
print("App started.")
