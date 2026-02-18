import os
import time
import threading
from datetime import datetime

import requests
from flask import Flask, jsonify

app = Flask(__name__)

TG_TOKEN = os.getenv("TG_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()
ALERTS_TOKEN = os.getenv("ALERTS_TOKEN", "").strip()

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
API_URL = "https://api.alerts.in.ua/v1/alerts/active.json"

KEYWORDS = ["одеса", "м. одеса", "одеська міська", "одеська громада"]

# --- глобальний стан для тесту
FORCE_STATE = None  # None = реальні дані, True = тривога, False = відбій

# --- глобальний стан воркера (для /status)
STATE = {
    "last_state": None,
    "alert_start_time": None,
    "last_check_ts": None,
    "last_error": None,
}

def send_telegram(text: str) -> bool:
    """Надсилає в телеграм. Повертає True/False."""
    if not TG_TOKEN or not TG_CHAT_ID:
        STATE["last_error"] = "TG_TOKEN або TG_CHAT_ID не задані"
        return False

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=20)
        if r.status_code != 200:
            STATE["last_error"] = f"Telegram HTTP {r.status_code}: {r.text[:200]}"
            return False
        return True
    except Exception as e:
        STATE["last_error"] = f"Telegram error: {e}"
        return False

def fetch_alerts():
    if not ALERTS_TOKEN:
        raise RuntimeError("ALERTS_TOKEN не заданий")
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

def format_duration(duration):
    total_seconds = int(duration.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0:
        return f"{hours} год {minutes} хв"
    return f"{minutes} хв"

def apply_state(active: bool, reason: str = ""):
    """Єдина логіка переходів станів + відправка повідомлень."""
    last_state = STATE["last_state"]

    # перший запуск — просто запам'ятали стан
    if last_state is None:
        STATE["last_state"] = active
        if active:
            STATE["alert_start_time"] = datetime.now()
        return

    # перехід: відбій -> тривога
    if active and not last_state:
        start_time = datetime.now()
        STATE["alert_start_time"] = start_time
        ok = send_telegram(
            f"🚨 Одеса: ПОВІТРЯНА ТРИВОГА\n🕒 {start_time.strftime('%H:%M:%S')}"
            + (f"\n({reason})" if reason else "")
        )
        STATE["last_state"] = True
        return ok

    # перехід: тривога -> відбій
    if (not active) and last_state:
        end_time = datetime.now()
        start_time = STATE["alert_start_time"] or end_time
        duration = end_time - start_time
        ok = send_telegram(
            f"✅ Одеса: ВІДБІЙ\n⏱ Тривала: {format_duration(duration)}"
            + (f"\n({reason})" if reason else "")
        )
        STATE["last_state"] = False
        STATE["alert_start_time"] = None
        return ok

    # стан не змінився
    return None

def worker():
    global FORCE_STATE
    while True:
        try:
            # визначаємо active
            if FORCE_STATE is not None:
                active = bool(FORCE_STATE)
                apply_state(active, reason="TEST MODE")
            else:
                data = fetch_alerts()
                alerts = data.get("alerts", data if isinstance(data, list) else [])
                active = any(isinstance(a, dict) and is_odessa_alert(a) for a in alerts)
                apply_state(active)

            STATE["last_check_ts"] = time.time()
            STATE["last_error"] = None

        except Exception as e:
            STATE["last_error"] = str(e)

        time.sleep(POLL_SECONDS)

@app.route("/")
def home():
    return "Bot is running. Use /health, /status, /test/on, /test/off, /test/auto", 200

@app.route("/health")
def health():
    return "OK", 200

@app.route("/status")
def status():
    now = time.time()
    seconds_since = None if STATE["last_check_ts"] is None else int(now - STATE["last_check_ts"])
    return jsonify({
        "ok": True,
        "force_state": FORCE_STATE,
        "last_state": STATE["last_state"],
        "alert_start_time": None if STATE["alert_start_time"] is None else STATE["alert_start_time"].isoformat(),
        "seconds_since_last_check": seconds_since,
        "last_error": STATE["last_error"],
    })

# --- ТЕСТОВІ КНОПКИ (ОДРАЗУ ШЛЮТЬ ПОВІДОМЛЕННЯ) ---
@app.route("/test/on")
def test_on():
    global FORCE_STATE
    FORCE_STATE = True
    res = apply_state(True, reason="MANUAL TEST /test/on")
    return jsonify({"force": "ON", "sent": bool(res)}), 200

@app.route("/test/off")
def test_off():
    global FORCE_STATE
    FORCE_STATE = False
    res = apply_state(False, reason="MANUAL TEST /test/off")
    return jsonify({"force": "OFF", "sent": bool(res)}), 200

@app.route("/test/auto")
def test_auto():
    global FORCE_STATE
    FORCE_STATE = None
    return jsonify({"force": "AUTO"}), 200

# старт воркера
threading.Thread(target=worker, daemon=True).start()

# ✅ ВАЖЛИВО: запуск веб-сервера для Render
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
