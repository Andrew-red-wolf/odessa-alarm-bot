import os
import time
import threading
import requests
from flask import Flask, jsonify

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()

API_URL = "https://api.alerts.in.ua/v1/alerts/active.json"

CHECK_EVERY_SEC = int(os.getenv("CHECK_EVERY_SEC", "30"))
REGION_QUERY = os.getenv("REGION_QUERY", "Одеська")  # можна змінити без коду

last_state = None            # None = ще не знаємо
alert_start_time = None
last_check_ts = None
last_error = None
bg_started = False


def tg_send(text: str) -> tuple[bool, str]:
    if not BOT_TOKEN:
        return False, "BOT_TOKEN is empty"
    if not CHAT_ID:
        return False, "CHAT_ID is empty"

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}

    try:
        r = requests.post(url, data=data, timeout=15)
        # важливо бачити помилки телеги
        if r.status_code != 200:
            return False, f"Telegram HTTP {r.status_code}: {r.text[:300]}"
        j = r.json()
        if not j.get("ok"):
            return False, f"Telegram not ok: {str(j)[:300]}"
        return True, "sent"
    except Exception as e:
        return False, f"Telegram exception: {e}"


def parse_odessa_alert(data) -> bool:
    """
    Робимо парсер максимально "живучим" під різні формати.
    Твій початковий варіант очікує список регіонів з полями name/alert.
    """
    # Варіант 1: це список
    if isinstance(data, list):
        for region in data:
            try:
                name = str(region.get("name", ""))
                alert = bool(region.get("alert"))
                if REGION_QUERY in name and alert:
                    return True
            except Exception:
                continue
        return False

    # Варіант 2: це dict (раптом API змінив формат)
    if isinstance(data, dict):
        # інколи може бути ключ типу "regions" або "data"
        for key in ("regions", "data", "alerts"):
            if key in data and isinstance(data[key], list):
                return parse_odessa_alert(data[key])

    return False


def check_alert() -> dict:
    global last_state, alert_start_time, last_check_ts, last_error

    last_check_ts = time.time()
    last_error = None

    try:
        r = requests.get(API_URL, timeout=20)
        if r.status_code != 200:
            last_error = f"alerts API HTTP {r.status_code}: {r.text[:200]}"
            return {"ok": False, "error": last_error}

        data = r.json()
        odessa_alert = parse_odessa_alert(data)

        # перший запуск — просто запам'ятали стан, без спаму
        if last_state is None:
            last_state = odessa_alert
            return {"ok": True, "init_state": odessa_alert}

        # старт тривоги
        if odessa_alert and not last_state:
            alert_start_time = time.time()
            ok, info = tg_send(f"🚨 ТРИВОГА в {REGION_QUERY} області!")
            if not ok:
                last_error = info
                return {"ok": False, "error": info, "event": "alarm_start"}

        # відбій
        if (not odessa_alert) and last_state:
            if alert_start_time:
                duration = int(time.time() - alert_start_time)
                minutes = max(0, duration // 60)
            else:
                minutes = 0
            ok, info = tg_send(f"✅ Відбій тривоги. Тривалість: {minutes} хв")
            if not ok:
                last_error = info
                return {"ok": False, "error": info, "event": "alarm_end"}
            alert_start_time = None

        last_state = odessa_alert
        return {"ok": True, "state": odessa_alert}

    except Exception as e:
        last_error = f"check exception: {e}"
        return {"ok": False, "error": last_error}


def loop():
    while True:
        res = check_alert()
        # щоб бачити в Render logs
        print("check:", res)
        time.sleep(CHECK_EVERY_SEC)


def ensure_bg():
    global bg_started
    if bg_started:
        return
    bg_started = True
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    print("Background loop started")


@app.before_request
def _startup():
    # стартуємо фон навіть якщо запуск не через __main__
    ensure_bg()


@app.route("/")
def home():
    return "Bot is alive"


@app.route("/ok")
def ok():
    now = time.time()
    since = None if not last_check_ts else int(now - last_check_ts)
    return jsonify({
        "ok": True,
        "bot_token_set": bool(BOT_TOKEN),
        "chat_id_set": bool(CHAT_ID),
        "last_state": last_state,
        "last_error": last_error,
        "seconds_since_last_check": since
    })


@app.route("/test")
def test():
    ensure_bg()
    ok_send, info = tg_send("✅ Бот активний (тест).")
    return jsonify({"ok": ok_send, "info": info})


@app.route("/check")
def manual_check():
    ensure_bg()
    res = check_alert()
    return jsonify(res)


if __name__ == "__main__":
    ensure_bg()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
