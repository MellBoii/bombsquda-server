from flask import (
    Flask, 
    request, 
    jsonify, 
    abort, 
    send_from_directory,
    render_template_string,
    make_response,
    render_template,
    redirect,
    url_for,
    session
)
import json
import os, sys
import time
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

DATA_FILE = "leaderboard.json"
port = int(os.environ.get("PORT", 5000))
ONLINE_TIMEOUT = 10
RUNTIME_FILE = "runtime.json"
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def cleanup_offline_clients(runtime):
    now = time.time()
    online = runtime.get("online_clients", {})

    runtime["online_clients"] = {
        bs_id: info
        for bs_id, info in online.items()
        if now - info.get("last_seen", 0) <= ONLINE_TIMEOUT
    }

def clean_display_name(s: str) -> str:
    return "".join(c for c in s if not (0xE000 <= ord(c) <= 0xF8FF)).strip()

@app.errorhandler(404)
def page_not_found(error):
    return send_from_directory(".", "not_found.html"), 404

@app.errorhandler(500)
def internal_error(error):
    return send_from_directory(".", "internal_error.html"), 500

@app.route("/leaderboard")
def leaderboard():
    return send_from_directory(".", "leaderboard.html")

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/bot")
def bot():
    return send_from_directory(".", "bot.html")
    

def load_runtime():
    if not os.path.exists(RUNTIME_FILE):
        return {}

    with open(RUNTIME_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_runtime(data):
    with open(RUNTIME_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

@app.route("/about")
def about():
    return send_from_directory(".", "about.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    username = ""
    runtime = load_runtime()
    correct_user = None
    correct_pass = None

    if session.get('squda_id'):
        return redirect(url_for('acc_settings'))

    if request.method == "POST":
        username = request.form.get("user", "")
        password = request.form.get("pass", "")

        if username == "":
            error = "Username is required."

        elif password == "":
            error = "Password is required."

        info = runtime.get('user_info', {})
        for sqid in list( info.keys() ):
            # get user by ID
            if username == sqid:
                correct_pass = info[sqid].get('password')
                correct_user = sqid
                break
            # otherwise try getting by username
            elif username == info[sqid]['username']:
                correct_pass = info[sqid].get('password')
                correct_user = sqid
                break
            else:
                pass
        
        # if there is a correct user, 
        # but no password,
        # make it our new one
        if correct_user and not correct_pass:
            runtime.get(correct_user)['password'] = password
            save_runtime(runtime)
                
        if not correct_user or password != correct_pass:
            error = "Invalid username or password."
        else:
            session['squda_id'] = correct_user
            return redirect(url_for('acc_settings'))

    return render_template("login.html", error=error, user=username)

@app.route("/online", methods=["GET"])
def get_online_players():
    runtime = load_runtime()
    cleanup_offline_clients(runtime)
    save_runtime(runtime)

    return jsonify(runtime.get("online_clients", {}))

@app.route("/acc_settings")
def acc_settings():
    runtime = load_runtime()
    squda_id = session.get('squda_id')
    # ew
    runtime_info = runtime.get('user_info', {})
    user_info = runtime_info.get(squda_id, {})
    username = user_info.get('username')
    if not username:
        username = squda_id
    
    if not squda_id:
        return "You aren't logged in!"
    return render_template("acc_settings.html", id=squda_id, username=username)
    
    
@app.route("/ping", methods=["POST"])
def ping():
    data = request.json
    runtime = load_runtime()
    runtime.setdefault('user_info', {})
    bs_id = data["bs_id"]
    info = runtime['user_info']
    if bs_id not in info.keys():
        info[bs_id] = {
            "account_name": clean_display_name(data.get("account", None)),
        }
        
    runtime.setdefault("online_clients", {})
    runtime["online_clients"][bs_id] = {
        "last_seen": time.time(),
        "account": data.get("account", None),
        "device_id": data.get("device_id", None),
        "bs_version": data.get("client_version", None),
        "squda_version": data.get("squda_version", 0.0),
        "squda_updatedate": data.get("squda_updatedate", '00/00/2000'),
    }
    cleanup_offline_clients(runtime)
    save_runtime(runtime)

    return {"ok": True}

@app.route("/sendcur", methods=["POST"])
def sendcur():
    data = request.json
    subkey = data.get('type', 'tickets')
    key = f"saved_{subkey}"
    runtime = load_runtime()
    bs_id = data["bs_id"]
    runtime.setdefault(key, {})
    runtime[key][bs_id] = runtime[key].get(bs_id, 0) + data.get('amount')
    save_runtime(runtime)

    return jsonify(
        {
            "ok": True, 
            "amount": data.get('amount'), 
            "new_bal": runtime[key].get(bs_id, 0)
        }
    )

@app.route("/withdrawcur", methods=["POST"])
def withdrawcur():
    data = request.json
    subkey = data.get('type', 'tickets')
    key = f"saved_{subkey}"
    runtime = load_runtime()
    bs_id = data["bs_id"]
    runtime.setdefault(key, {})
    runtime[key][bs_id] = runtime[key].get(bs_id, 0) - data.get('amount')
    save_runtime(runtime)

    return jsonify(
        {
            "ok": True, 
            "amount": data.get('amount'), 
            "new_bal": runtime[key].get(bs_id, 0)
        }
    )

@app.route("/getcur", methods=["POST"])
def getcur():
    data = request.json
    subkey = data.get('type', 'tickets')
    key = f"saved_{subkey}"
    runtime = load_runtime()
    bs_id = data["bs_id"]
    runtime.setdefault(key, {})
    save_runtime(runtime)
    return jsonify(
        {
            "ok": True, 
            "amount": runtime[key].get(bs_id, 0)
        }
    )


@app.route("/friends/request", methods=["POST"])
def send_friend_request():
    runtime = load_runtime()
    data = request.get_json(silent=True) or {}
    sender = clean_display_name(data.get("from", ""))
    target = clean_display_name(data.get("to", ""))
    info = runtime.get('user_info')
    for sqid in list( info.keys() ):
        thisinfo = info.get('sqid')
        username = thisinfo.get('username')
        if not username:
            username thisinfo.get('account_name')
        if username.upper() == target.upper():
            target = sqid

    if not sender or not target or sender == target:
        return jsonify({"error": "invalid"}), 400

    runtime = load_runtime()
    runtime.setdefault("friend_requests", {})
    runtime.setdefault("friends", {})

    # Already friends?
    if target in runtime["friends"].get(sender, []):
        return jsonify({"status": "already_friends"})

    runtime["friend_requests"].setdefault(target, [])
    if sender not in runtime["friend_requests"][target]:
        runtime["friend_requests"][target].append(sender)

    save_runtime(runtime)
    return jsonify({"status": "sent"})

@app.route("/friends/respond", methods=["POST"])
def respond_friend_request():
    data = request.get_json(silent=True) or {}
    user = clean_display_name(data.get("user", ""))
    sender = clean_display_name(data.get("from", ""))
    accept = bool(data.get("accept", False))
    info = runtime.get('user_info')
    for sqid in list( info.keys() ):
        thisinfo = info.get('sqid')
        username = thisinfo.get('username')
        if not username:
            username thisinfo.get('account_name')
        if username.upper() == target.upper():
            sender = sqid

    runtime = load_runtime()
    requests = runtime.setdefault("friend_requests", {})
    friends = runtime.setdefault("friends", {})

    if sender not in requests.get(user, []):
        return jsonify({"error": "no_request"}), 400

    requests[user].remove(sender)
    if not requests[user]:
        del requests[user]

    if accept:
        friends.setdefault(user, []).append(sender)
        friends.setdefault(sender, []).append(user)

    save_runtime(runtime)
    return jsonify({"status": "ok"})

@app.route("/friends/list", methods=["POST"])
def get_friends():
    data = request.get_json(silent=True) or {}
    user = clean_display_name(data.get("user", ""))

    runtime = load_runtime()
    return jsonify({
        "friends": runtime.get("friends", {}).get(user, []),
        "requests": runtime.get("friend_requests", {}).get(user, [])
    })

@app.route("/send_command", methods=["POST"])
def send_command():
    data = request.json
    bs_id = data["bs_id"]

    runtime = load_runtime()
    runtime["commands"].setdefault(bs_id, []).append(data)
    save_runtime(runtime)

    return {"queued": True}

@app.route("/submit", methods=["POST"])
def submit():
    payload = request.json

    level = payload["level"]
    player = payload["player"]
    time = payload["time"]

    data = load_data()

    if level not in data:
        data[level] = {}

    best = data[level].get(player)
    if best is None or time < best:
        data[level][player] = time

    save_data(data)
    print(f'{player} submitted time {time} for {level}')
    return jsonify({"status": "ok"})

@app.route("/get/<level>")
def get_level(level):
    data = load_data()
    return jsonify(data.get(level, {}))

@app.route("/get/all")
def get_all():
    if not os.path.exists(DATA_FILE):
        return {}

    with open(DATA_FILE, "r") as f:
        return json.load(f)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port)

