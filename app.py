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

# Файл для тестового режиму (працює навіть якщо в тебе 2+ процеси на Render)
FORCE_FILE = "/tmp/force_state.txt"
# Значення: "ON", "OFF", або файл відсутній = AUTO


def send_telegram(text: str):
    """Надіслати повідомлення в Telegram + показати помилки в логах Render."""
    if not TG_TOKEN or not TG_CHAT_ID:
        print("ERROR: TG_TOKEN or TG_CHAT_ID is empty")
        return False

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=20)
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        print("TG RESP:", data)  # <-- найважливіше, буде видно причину якщо не відправляє
        return bool(data.get("ok"))
    except Exception as e:
        print("TG ERROR:", e)
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


def read_force_state():
    """Повертає True/False/None (None = AUTO)."""
    try:
        with open(FORCE_FILE, "r", encoding="utf-8") as f:
            v = f.read().strip().upper()
        if v == "ON":
            return True
        if v == "OFF":
            return False
        return None
    except FileNotFoundError:
        return None
    except Exception as e:
        print("FORCE READ ERROR:", e)
        return None


def format_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h} год {m} хв {s} с"
    if m > 0:
        return f"{m} хв {s} с"
    return f"{s} с"


def worker():
    last_state = None
    alert_start_time = None

    while True:
        try:
            forced = read_force_state()

            if forced is not None:
                active = forced
            else:
                data = fetch_alerts()
                alerts = data.get("alerts", data if isinstance(data, list) else [])
                active = any(isinstance(a, dict) and is_odessa_alert(a) for a in alerts)

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
                if alert_start_time:
                    dur_s = int((end_time - alert_start_time).total_seconds())
                else:
                    dur_s = 0
                send_telegram(f"✅ Одеса: ВІДБІЙ\n⏱ Тривала: {format_duration(dur_s)}")
                last_state = False
                alert_start_time = None

        except Exception as e:
            print("WORKER ERROR:", e)

        time.sleep(POLL_SECONDS)


@app.route("/")
def home():
    return "Bot is running", 200


# --- ТЕСТОВІ РУЧКИ (працюють стабільно) ---

@app.route("/test/ping")
def test_ping():
    ok = send_telegram("✅ TEST: ping (перевірка звʼязку)")
    return jsonify({"ok": ok}), 200


@app.route("/test/on")
def test_on():
    with open(FORCE_FILE, "w", encoding="utf-8") as f:
        f.write("ON")
    # НЕ чекаємо 30 сек — одразу шлемо тестове
    ok = send_telegram("🚨 TEST: FORCE ON (імітація тривоги)")
    return jsonify({"force": "ON", "sent": ok}), 200


@app.route("/test/off")
def test_off():
    with open(FORCE_FILE, "w", encoding="utf-8") as f:
        f.write("OFF")
    ok = send_telegram("✅ TEST: FORCE OFF (імітація відбою)")
    return jsonify({"force": "OFF", "sent": ok}), 200


@app.route("/test/auto")
def test_auto():
    try:
        os.remove(FORCE_FILE)
    except FileNotFoundError:
        pass
    ok = send_telegram("🔄 TEST: AUTO (назад до реальних тривог)")
    return jsonify({"force": "AUTO", "sent": ok}), 200


# старт потоку
threading.Thread(target=worker, daemon=True).start()
