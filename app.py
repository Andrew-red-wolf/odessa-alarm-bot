  import os
import time
import threading
import requests
from flask import Flask, jsonify

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()
ALERTS_API_TOKEN = os.getenv("ALERTS_API_TOKEN", "").strip()

API_URL = "https://api.alerts.in.ua/v1/alerts/active.json"

last_state = False
alert_start_time = None
last_error = None
last_check_ts = None


def tg_send(text: str) -> dict:
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN is empty"}
    if not CHAT_ID:
        return {"ok": False, "error": "CHAT_ID is empty"}

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        r = requests.post(url, data=payload, timeout=15)
        return {"ok": r.ok, "status_code": r.status_code, "text": r.text[:300]}
    except Exception as e:
        return {"ok": False, "error": f"Telegram send error: {e}"}


def fetch_alerts() -> list:
    # alerts.in.ua тепер потребує токен -> додаємо заголовок Authorization
    headers = {}
    if ALERTS_API_TOKEN:
        headers["Authorization"] = f"Bearer {ALERTS_API_TOKEN}"

    r = requests.get(API_URL, headers=headers, timeout=15)

    if r.status_code == 401:
        # щоб ти одразу бачив причину
        raise RuntimeError('Alerts API HTTP 401: "API token required" (set ALERTS_API_TOKEN)')

    r.raise_for_status()
    return r.json()


def is_odessa_alert(data) -> bool:
    # Формат може бути різний, але в їхньому active.json зазвичай список регіонів.
    # Ми шукаємо "Одеська" + alert == True
    for region in data:
        name = str(region.get("name", ""))
        alert = bool(region.get("alert", False))
        if "Одеська" in name and alert:
            return True
    return False


def check_alert_once() -> dict:
    global last_state, alert_start_time, last_error, last_check_ts

    last_check_ts = int(time.time())
    try:
        data = fetch_alerts()
        odessa = is_odessa_alert(data)

        # старт
        if odessa and not last_state:
            alert_start_time = time.time()
            tg_send("🚨 ТРИВОГА в Одеській області!")

        # відбій
        if (not odessa) and last_state and alert_start_time:
            duration = int(time.time() - alert_start_time)
            minutes = duration // 60
            tg_send(f"✅ Відбій тривоги. Тривалість: {minutes} хв")
            alert_start_time = None

        last_state = odessa
        last_error = None
        return {"ok": True, "odessa_alert": odessa}

    except Exception as e:
        last_error = str(e)
        return {"ok": False, "error": last_error}


def bg_loop():
    while True:
        check_alert_once()
        time.sleep(30)


@app.route("/")
def home():
    return "Bot is alive"


@app.route("/ping")
def ping():
    res = tg_send("✅ Bot active (ping). Якщо бачиш це повідомлення — Telegram налаштовано.")
    return jsonify(res)


@app.route("/check")
def manual_check():
    res = check_alert_once()
    return jsonify(res)


@app.route("/status")
def status():
    return jsonify({
        "bot_token_set": bool(BOT_TOKEN),
        "chat_id_set": bool(CHAT_ID),
        "alerts_api_token_set": bool(ALERTS_API_TOKEN),
        "last_state": last_state,
        "last_error": last_error,
        "last_check_seconds_ago": None if not last_check_ts else int(time.time()) - last_check_ts
    })


if __name__ == "__main__":
    # Запускаємо фон-перевірку
    threading.Thread(target=bg_loop, daemon=True).start()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
