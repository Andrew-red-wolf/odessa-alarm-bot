 import os
import time
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CHAT_ID = os.getenv("TG_CHAT_ID")  # має бути типу -100xxxxxxxxxx

# тут зберігаємо останній стан
state = {
    "last_state": None,            # "alarm" / "clear"
    "last_check_ts": None,
    "last_error": None,
    "seconds_since_last_check": None,
}

def tg_send(text: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        state["last_error"] = "Missing TG_BOT_TOKEN or TG_CHAT_ID"
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=20)
    ok = r.status_code == 200 and r.json().get("ok") is True
    if not ok:
        state["last_error"] = f"Telegram error: {r.text[:300]}"
    return ok

def read_alarm_state() -> str:
    """
    ПОВЕРТАЄ "alarm" або "clear".
    Тут треба вставити ТВОЄ джерело тривог (те що ми вже робили).
    Поки що заглушка -> завжди clear.
    """
    return "clear"

def check():
    try:
        cur = read_alarm_state()
        prev = state["last_state"]

        state["last_state"] = cur
        state["last_check_ts"] = int(time.time())
        state["last_error"] = None

        if prev is None:
            # перший запуск — не спамимо
            return {"changed": False, "state": cur}

        if cur != prev:
            if cur == "alarm":
                tg_send("🚨 ТРИВОГА (авто)")
            else:
                tg_send("✅ ВІДБІЙ (авто)")
            return {"changed": True, "state": cur}

        return {"changed": False, "state": cur}

    except Exception as e:
        state["last_error"] = str(e)
        return {"changed": False, "error": str(e)}

@app.route("/")
def home():
    return "OK", 200

@app.route("/status")
def status():
    if state["last_check_ts"]:
        state["seconds_since_last_check"] = int(time.time()) - int(state["last_check_ts"])
    return jsonify({"ok": True, **state})

@app.route("/check")
def check_route():
    res = check()
    return jsonify({"ok": True, **res, **state})

@app.route("/test")
def test_route():
    text = request.args.get("text", "✅ ТЕСТ: бот активний")
    sent = tg_send(text)
    return jsonify({"ok": sent})

@app.route("/force")
def force_route():
    st = request.args.get("state", "").strip().lower()
    if st not in ("alarm", "clear"):
        return jsonify({"ok": False, "error": "use ?state=alarm or ?state=clear"}), 400

    state["last_state"] = st
    if st == "alarm":
        sent = tg_send("🚨 ПРЯМИЙ ТЕСТ: ТРИВОГА")
    else:
        sent = tg_send("✅ ПРЯМИЙ ТЕСТ: ВІДБІЙ")

    return jsonify({"ok": sent, "forced": st})
