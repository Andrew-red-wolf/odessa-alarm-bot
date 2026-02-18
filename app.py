import os
import time
import threading
from datetime import datetime
import requests
from flask import Flask, jsonify

app = Flask(__name__)

# ===== ENV VARS =====
TG_TOKEN = os.getenv("TG_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()  # group id like -100xxxxxxxxxx
ALERTS_TOKEN = os.getenv("ALERTS_TOKEN", "").strip()

# ===== SETTINGS =====
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
HEARTBEAT_HOUR = int(os.getenv("HEARTBEAT_HOUR", "9"))  # 09:00
TIMEZONE_LABEL = os.getenv("TIMEZONE_LABEL", "Europe/Kyiv")  # just label in text

API_URL = "https://api.alerts.in.ua/v1/alerts/active.json"

# Keywords for Odessa / Odesa region (alerts.in.ua titles can vary)
KEYWORDS = [
    "одеса", "м. одеса", "м одеса", "одеська", "одеська громада", "одеський",
    "odesa", "odessa"
]

# State
last_state = None           # True = alert, False = no alert
alert_start_time = None     # when alert started
last_check_ts = None        # last poll time
last_error = None
last_heartbeat_date = None  # "dd.mm.yyyy"

force_state = None          # None / True / False


def now_time():
    return datetime.now().strftime("%H:%M:%S")


def today_date():
    return datetime.now().strftime("%d.%m.%Y")


def send_telegram(text: str) -> bool:
    """Send message to telegram chat."""
    global last_error
    if not TG_TOKEN or not TG_CHAT_ID:
        last_error = "Missing TG_TOKEN or TG_CHAT_ID"
        return False

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=15)
        if r.status_code != 200:
            last_error = f"Telegram sendMessage HTTP {r.status_code}: {r.text[:200]}"
            return False

        data = r.json()
        if not data.get("ok", False):
            last_error = f"Telegram sendMessage not ok: {str(data)[:200]}"
            return False

        return True
    except Exception as e:
        last_error = f"Telegram exception: {e}"
        return False


def fetch_alerts():
    """Fetch active alerts from alerts.in.ua API."""
    global last_error
    if not ALERTS_TOKEN:
        last_error = "Missing ALERTS_TOKEN"
        return []

    try:
        r = requests.get(API_URL, params={"token": ALERTS_TOKEN}, timeout=20)
        if r.status_code != 200:
            last_error = f"alerts.in.ua HTTP {r.status_code}: {r.text[:200]}"
            return []

        data = r.json()
        # API sometimes returns {"alerts":[...]} or a list directly
        if isinstance(data, dict) and "alerts" in data:
            return data["alerts"]
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        last_error = f"alerts.in.ua exception: {e}"
        return []


def is_odessa_air_alert(alert: dict) -> bool:
    """Detect Odessa air raid alert."""
    try:
        # Some APIs have alert_type or type; keep it flexible
        a_type = str(alert.get("alert_type", alert.get("type", ""))).lower()
        if "air" not in a_type and "повіт" not in a_type and "raid" not in a_type:
            # If API doesn't provide type reliably, don't hard-fail
            # We'll still try to match by oblast/title
            pass

        oblast = str(alert.get("location_oblast", alert.get("oblast", ""))).lower()
        title = str(alert.get("location_title", alert.get("title", ""))).lower()

        # Must be Odessa oblast
        if "одес" not in oblast and "odes" not in oblast:
            return False

        # Title should mention Odessa city/community or relevant keyword
        return any(k in title for k in KEYWORDS) or ("одес" in title) or ("odes" in title)
    except Exception:
        return False


def get_active_state() -> bool:
    """Return True if Odessa air alert is active."""
    # forced state has priority
    if force_state is True:
        return True
    if force_state is False:
        return False

    alerts = fetch_alerts()
    return any(isinstance(a, dict) and is_odessa_air_alert(a) for a in alerts)


def worker_loop():
    """Background loop: check alerts and heartbeat."""
    global last_state, alert_start_time, last_check_ts, last_heartbeat_date

    while True:
        try:
            last_check_ts = int(time.time())

            # Heartbeat once per day at HEARTBEAT_HOUR
            dt = datetime.now()
            if dt.hour == HEARTBEAT_HOUR and last_heartbeat_date != today_date():
                send_telegram(f"🟢 IZTalarm: бот активний\nДата: {today_date()} ({TIMEZONE_LABEL})")
                last_heartbeat_date = today_date()

            active = get_active_state()

            if last_state is None:
                last_state = active
                if active:
                    alert_start_time = datetime.now().isoformat()
                # don't spam on first start
            else:
                # Rising edge: OFF -> ON
                if active and not last_state:
                    alert_start_time = datetime.now().isoformat()
                    send_telegram(f"🚨 Одеса: ПОВІТРЯНА ТРИВОГА\nЧас: {now_time()}")
                    last_state = True

                # Falling edge: ON -> OFF
                elif (not active) and last_state:
                    send_telegram(f"✅ Одеса: ВІДБІЙ\nЧас: {now_time()}")
                    last_state = False
                    alert_start_time = None

        except Exception as e:
            # keep loop alive
            print("Worker error:", e)

        time.sleep(POLL_SECONDS)


# Start background thread
threading.Thread(target=worker_loop, daemon=True).start()


# ===== ROUTES =====
@app.route("/")
def home():
    return "OK", 200


@app.route("/ping")
def ping():
    return jsonify({
        "ok": True,
        "last_state": last_state,
        "force_state": force_state,
        "alert_start_time": alert_start_time,
        "seconds_since_last_check": None if not last_check_ts else int(time.time()) - last_check_ts,
        "last_error": last_error
    }), 200


@app.route("/test")
def test():
    ok = send_telegram(f"🧪 ТЕСТ: бот на звʼязку\nЧас: {now_time()}\nДата: {today_date()}")
    return jsonify({"ok": ok}), 200


@app.route("/force_on")
def force_on():
    global force_state
    force_state = True
    ok = send_telegram("🚨 (ТЕСТ) Примусово УВІМКНУВ тривогу")
    return jsonify({"force": "ON", "sent": ok}), 200


@app.route("/force_off")
def force_off():
    global force_state
    force_state = False
    ok = send_telegram("✅ (ТЕСТ) Примусово ВИМКНУВ тривогу")
    return jsonify({"force": "OFF", "sent": ok}), 200


@app.route("/force_clear")
def force_clear():
    global force_state
    force_state = None
    ok = send_telegram("🧼 (ТЕСТ) Примус вимкнено, повернувся в автоматичний режим")
    return jsonify({"force": None, "sent": ok}), 200


if __name__ == "__main__":
    # Render provides PORT automatically sometimes; keep default 10000 for local
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
