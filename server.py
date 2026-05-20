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
import time, datetime
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

DATA_FILE = "leaderboard.json"
port = int(os.environ.get("PORT", 5000))
ONLINE_TIMEOUT = 10
RUNTIME_FILE = "runtime.json"

def resolve_user_id(name: str) -> str | None:
    """Resolve a username/account name/ID into a Squda ID."""
    
    runtime = load_runtime()
    info = runtime.get("user_info", {})

    name = clean_display_name(name)

    # Direct ID match
    if name in info:
        return name

    # Username/account name lookup
    for sqid, user_info in info.items():
        username = user_info.get("username")
        account_name = user_info.get("account_name")

        if username and username.upper() == name.upper():
            return sqid

        if account_name and account_name.upper() == name.upper():
            return sqid

    return None


def are_friends(runtime: dict, user1: str, user2: str) -> bool:
    """Check if two users are friends."""
    
    return user2 in runtime.get("friends", {}).get(user1, [])

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
            # get user
            if resolve_user_id(sqid):
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
    reply = {"ok": True}
    runtime.setdefault('user_info', {})
    bs_id = data["bs_id"]
    info = runtime['user_info']
    if bs_id not in info.keys():
        acc_name = data.get("account", None)
        info[bs_id] = {
            "account_name": clean_display_name(acc_name),
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

    return reply

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
    data = request.get_json(silent=True) or {}

    sender = resolve_user_id(data.get("from", ""))
    target = resolve_user_id(data.get("to", ""))

    if not sender or not target:
        return jsonify({"error": "invalid_user"})

    if sender == target:
        return jsonify({"error": "cannot_friend_self"})

    runtime = load_runtime()

    runtime.setdefault("friend_requests", {})
    runtime.setdefault("friends", {})

    # Already friends
    if are_friends(runtime, sender, target):
        return jsonify({"status": "already_friends"})

    # Create request list
    requests = runtime["friend_requests"].setdefault(target, [])

    # Avoid duplicates
    if sender not in requests:
        requests.append(sender)

    save_runtime(runtime)

    return jsonify({"status": "sent"})

@app.route("/friends/respond", methods=["POST"])
def respond_friend_request():
    data = request.get_json(silent=True) or {}

    user = resolve_user_id(data.get("user", ""))
    sender = resolve_user_id(data.get("from", ""))
    accept = bool(data.get("accept", False))

    if not user or not sender:
        return jsonify({"error": "invalid_user"})

    runtime = load_runtime()

    requests = runtime.setdefault("friend_requests", {})
    friends = runtime.setdefault("friends", {})

    user_requests = requests.get(user, [])

    if sender not in user_requests:
        return jsonify({"error": "no_request"})

    # Remove request
    user_requests.remove(sender)

    if not user_requests:
        requests.pop(user, None)

    # Accept request
    if accept:
        friends.setdefault(user, [])
        friends.setdefault(sender, [])

        if sender not in friends[user]:
            friends[user].append(sender)

        if user not in friends[sender]:
            friends[sender].append(user)

    save_runtime(runtime)

    return jsonify({
        "status": "accepted" if accept else "declined"
    })


@app.route("/friends/message", methods=["POST"])
def send_friend_message():
    data = request.get_json(silent=True) or {}

    sender = resolve_user_id(data.get("from", ""))
    target = resolve_user_id(data.get("to", ""))
    message = str(data.get("message", "")).strip()

    if not sender or not target:
        return jsonify({"error": "invalid_user"})

    if not message:
        return jsonify({"error": "empty_message"})

    runtime = load_runtime()

    # Must be friends
    if not are_friends(runtime, sender, target):
        return jsonify({"error": "not_friends"})

    runtime.setdefault("friend_messages", {})

    convo_id = "_".join(sorted([sender, target]))

    runtime["friend_messages"].setdefault(convo_id, [])
    thistime = datetime.datetime.now()
    thistime = thistime.strftime("%H:%M:%S")
    runtime["friend_messages"][convo_id].append({
        "from": sender,
        "message": message,
        "time": thistime,
        'seen': False,
    })

    save_runtime(runtime)

    return jsonify({"status": "sent"})

@app.route("/friends/messages", methods=["POST"])
def get_friend_messages():
    data = request.get_json(silent=True) or {}

    user1 = resolve_user_id(data.get("user", ""))
    user2 = resolve_user_id(data.get("with", ""))
    print(user1)
    print(user2)

    if not user1 or not user2:
        return jsonify({"error": "invalid_user"})

    runtime = load_runtime()

    convo_id = "_".join(sorted([user1, user2]))

    return jsonify({
        "messages": runtime.get("friend_messages", {}).get(convo_id, [])
    })
    

@app.route("/friends/list", methods=["POST"])
def get_friends():
    data = request.get_json(silent=True) or {}

    user = resolve_user_id(data.get("user", ""))

    if not user:
        return jsonify({"error": "invalid_user"})

    runtime = load_runtime()

    return jsonify({
        "friends": runtime.get("friends", {}).get(user, []),
        "requests": runtime.get("friend_requests", {}).get(user, [])
    })


@app.route("/api/get_name_from_id", methods=["POST"])
def get_name():
    data = request.get_json(silent=True) or {}
    id = data.get('id')
    runtime = load_runtime()
    info = runtime.get("user_info", {})
    thisinfo = info.get(id)
    name = thisinfo.get('username')
    if not name:
        name = thisinfo.get('account_name', '')
    return name

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

