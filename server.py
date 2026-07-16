
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
    session,
    send_file
)
from werkzeug.security import (
    generate_password_hash, 
    check_password_hash
)
import json
import json_repair
import os, sys
import time, datetime
from dotenv import load_dotenv
from pathlib import Path
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

port = int(os.environ.get("PORT", 5000))
ONLINE_TIMEOUT = 10
# FIXME: PLEAAASEEE FIX RUNTIME BUGGING
RUNTIME_FILE = "runtime.json"

def resolve_user_id(name: str) -> str | None:
    """Resolve a username/account name/ID into a Squda ID."""
    
    runtime = load_data(RUNTIME_FILE)
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


def load_data(file):
    if not os.path.exists(file):
        return {}
    with open(file, "r") as f:
        return json.load(f)

def save_data(data, file):
    # use json_repair just to make sure
    # we have no malformed json >:/
    data = str(data)
    data = json_repair.loads(data)
    with open(file, "w") as f:
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

@app.route("/scores_lb")
def leaderboard():
    return send_from_directory(".", "leaderboard.html")

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/bot")
def bot():
    return send_from_directory(".", "bot.html")

@app.route("/about")
def about():
    return send_from_directory(".", "about.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    username = ""
    runtime = load_data(RUNTIME_FILE)
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
        runtime.setdefault('passwords', {})
        passwords = runtime.get('passwords')
        for sqid in list( info.keys() ):
            # get user
            if resolve_user_id(sqid):
                correct_pass = passwords.get(sqid)
                correct_user = sqid
                break
            else:
                pass
        
        # if there is a correct user, 
        # but no password,
        # make it our new one
        if correct_user and not correct_pass:
            passwords[sqid] = generate_password_hash(password)
            correct_pass = passwords.get(sqid)
            save_runtime(runtime)
                
        if not correct_user or not check_password_hash(correct_pass, password):
            error = "Invalid username or password."
        else:
            session['squda_id'] = correct_user
            return redirect(url_for('acc_settings'))

    return render_template("login.html", error=error, user=username)

@app.route("/online", methods=["GET"])
def get_online_players():
    runtime = load_data(RUNTIME_FILE)
    cleanup_offline_clients(runtime)
    save_runtime(runtime)

    return jsonify(runtime.get("online_clients", {}))

@app.route("/acc_settings")
def acc_settings():
    runtime = load_data(RUNTIME_FILE)
    squda_id = session.get('squda_id')
    # ew
    runtime_info = runtime.get('user_info', {})
    user_info = runtime_info.get(squda_id, {})
    username = user_info.get(
        'username', 
        user_info.get('account_name')
    )
    if not username:
        username = squda_id
    
    if not squda_id:
        return "You aren't logged in!"
    return render_template("acc_settings.html", id=squda_id, username=username)
    
    
@app.route("/ping", methods=["POST"])
def ping():
    data = request.json
    runtime = load_data(RUNTIME_FILE)
    reply = {"ok": True}
    runtime.setdefault('user_info', {})
    bs_id = data.get("bs_id")
    info = runtime.get('user_info')
    acc_name = data.get("account", None)
    acc_name = clean_display_name(acc_name)
    if bs_id not in info.keys():
        info[bs_id] = {
            "account_name": acc_name,
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
    runtime.setdefault("client_statuses", {})
    runtime["client_statuses"][bs_id] = data.get("squda_status", {})
    cleanup_offline_clients(runtime)
    save_runtime(runtime)

    chosenconvos = []
    convos = runtime.get("friend_messages", {})
    user1 = resolve_user_id(acc_name)
    for convo in convos.keys():
        if user1 in convo:
            chosenconvos.append(convos[convo])
    for convos in chosenconvos:
        for message in convos:
            if not message.get('seen', False) and message.get('from') != user1:
                new_msgs = reply.setdefault('new_messages', {})
                user = message.get('from')
                content = message.get('message')
                new_msgs[user] = content
                message['seen'] = True
            
    save_runtime(runtime)
    return jsonify(reply)

@app.route("/sendcur", methods=["POST"])
def sendcur():
    data = request.json
    subkey = data.get('type', 'tickets')
    key = f"saved_{subkey}"
    runtime = load_data(RUNTIME_FILE)
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
    runtime = load_data(RUNTIME_FILE)
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
    runtime = load_data(RUNTIME_FILE)
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

    runtime = load_data(RUNTIME_FILE)

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

@app.route("/friends/remove", methods=["POST"])
def remove_friend():
    data = request.get_json(silent=True) or {}

    user = resolve_user_id(data.get("user", ""))
    target = resolve_user_id(data.get("target", ""))

    if not user or not target:
        return jsonify({"error": "invalid_user"})

    if user == target:
        return jsonify({"error": "cannot_friend_self"})

    runtime = load_data(RUNTIME_FILE)

    runtime.setdefault("friends", {})

    # Not friends
    if not are_friends(runtime, user, target):
        return jsonify({"status": "not_friends"})

    # Create request list
    friends = runtime.get('friends', {}).get(user)

    # Avoid duplicates
    if target in friends:
        friends.remove(target)
    
    friends = runtime.get('friends', {}).get(target)
    
    # Avoid duplicates
    if user in friends:
        friends.remove(user)

    save_runtime(runtime)

    return jsonify({"status": "done"})

@app.route("/friends/respond", methods=["POST"])
def respond_friend_request():
    data = request.get_json(silent=True) or {}

    user = resolve_user_id(data.get("user", ""))
    sender = resolve_user_id(data.get("from", ""))
    accept = bool(data.get("accept", False))

    if not user or not sender:
        return jsonify({"error": "invalid_user"})

    runtime = load_data(RUNTIME_FILE)

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
    
    if len(message) > 80:
        message = message[:80]

    runtime = load_data(RUNTIME_FILE)

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

@app.route("/api/set_profile_data", methods=["POST"])
def profile_data():
    data = request.get_json(silent=True) or {}

    user_id = resolve_user_id(data.get('user'))

    runtime = load_data(RUNTIME_FILE)

    info = runtime.setdefault("user_info", {})
    thisinfo = info.setdefault(user_id, {})

    for key, value in data.items():
        if isinstance(value, str):
            if key in ['username', 'status']:
                value = value[:40]
        if key == 'user':
            continue
        thisinfo[key] = value

    save_runtime(runtime)

    return jsonify({"status": "ok"})

@app.route("/api/submit_score", methods=["POST"])
def submit_score():
    data = request.get_json(silent=True) or {}

    runtime = load_data(RUNTIME_FILE)
    scores = runtime.setdefault("scores", {})

    level = data["level"]
    order = data["order"]  # increasing or decreasing
    player_amount = data["game_config"] # player count
    name = data["name"] # player's name??
    score = data["score"]
    campaign = data["campaign"]

    campaign_scores = scores.setdefault(campaign, {})
    level_scores = campaign_scores.setdefault(level, {})

    # Store score type.
    level_scores["score_type"] = data["score_type"]

    leaderboard = level_scores.setdefault(player_amount, [])

    # Whether a smaller score is better.
    lower_is_better = (order == "decreasing")

    # Look for an existing score from this player.
    for i, (old_score, old_name) in enumerate(leaderboard):
        if old_name == name:
            better = (
                score < old_score
                if lower_is_better
                else score > old_score
            )

            if better:
                leaderboard[i] = (score, name)

            break
    else:
        # Player not found.
        leaderboard.append((score, name))

    # Sort leaderboard.
    leaderboard.sort(
        key=lambda x: x[0],
        reverse=not lower_is_better
    )

    save_runtime(runtime)

    return jsonify({
        "total": len(leaderboard),
        "tops": leaderboard[:10],
        "link": "https://bombsquda.tailc76b25.ts.net/scores_lb",
    })
        

@app.route("/friends/messages", methods=["POST"])
def get_friend_messages():
    data = request.get_json(silent=True) or {}

    user1 = resolve_user_id(data.get("user", ""))
    user2 = resolve_user_id(data.get("with", ""))

    if not user1 or not user2:
        return jsonify({"error": "invalid_user"})

    runtime = load_data(RUNTIME_FILE)

    convo_id = "_".join(sorted([user1, user2]))

    return jsonify({
        "messages": runtime.get("friend_messages", {}).get(convo_id, [])
    })

@app.route("/friends/set_all_seen", methods=["POST"])
def set_seen():
    data = request.get_json(silent=True) or {}

    user1 = resolve_user_id(data.get("user", ""))
    user2 = resolve_user_id(data.get("with", ""))

    if not user1 or not user2:
        return jsonify({"error": "invalid_user"})

    runtime = load_data(RUNTIME_FILE)

    convo_id = "_".join(sorted([user1, user2]))
    for message in runtime.get("friend_messages", {}).get(convo_id, []):
        if message.get('from') == user2:
            message['seen'] = True
    save_runtime(runtime)

    return jsonify({'status': 'ok'})

@app.route("/friends/list", methods=["POST"])
def get_friends():
    data = request.get_json(silent=True) or {}

    user = resolve_user_id(data.get("user", ""))

    if not user:
        return jsonify({"error": "invalid_user"})

    runtime = load_data(RUNTIME_FILE)

    return jsonify({
        "friends": runtime.get("friends", {}).get(user, []),
        "requests": runtime.get("friend_requests", {}).get(user, [])
    })

@app.route("/api/get_info", methods=["POST"])
def get_info():
    data = request.get_json(silent=True) or {}
    id = data.get('id')
    runtime = load_data(RUNTIME_FILE)
    info = runtime.get("user_info", {})
    thisinfo = info.get(id, {})
    return jsonify(thisinfo)

@app.route("/api/get_status", methods=["POST"])
def get_status():
    data = request.get_json(silent=True) or {}
    id = data.get('id')
    runtime = load_data(RUNTIME_FILE)
    info = runtime.get("client_statuses", {})
    thisinfo = info.get(id, {})
    return jsonify(thisinfo)

@app.route("/submit", methods=["POST"])
def submit():
    payload = request.json

    level = payload["level"]
    player = payload["player"]
    time = payload["time"]

    data = load_data('leaderboard.json')

    if level not in data:
        data[level] = {}

    best = data[level].get(player)
    if best is None or time < best:
        data[level][player] = time

    save_data(data, 'leaderboard.json')
    return jsonify({"status": "ok"})
    


@app.route("/api/get_scores")
def get_scores():
    runtime = load_data(RUNTIME_FILE)

    return jsonify(runtime.get('scores', {}))

# ok so dumbasses dlc isnt just for paid stuff
# it's called 'Downloadable Content' for a REASON
# i mostly just made this to test myself
@app.route('/api/get_dlc', methods=["POST"])
def get_dlc():
    payload = request.get_json() or {}
    if not payload:
        return jsonify({'error': 'no_payload'})
    requested_name = payload.get('name')
    # dlcs,,,,
    available_dlc = load_data('dlc_data.json')
    # file suffixes for bombsquad
    file_suffixes = {
        'meshes': 'bob',
        'textures': 'dds',
        'audio': 'ogg',
        'python': 'py', # FIXME: are we really gonna include scripts as dlc???
    }
    # file converters (make later)
    file_conversions = {}
    data = available_dlc.get(requested_name)
    if not data:
        return jsonify({'error': 'invalid_dlc'})
    # get the required files that the dlc wants to share
    req_texs = data.get('textures')
    req_mesh = data.get('meshes')
    req_audio = data.get('audio')
    persistent = data.get('persistent', False)
    # url generator
    def gen_files(file_dict: dict, keyname: str):
        nonlocal file_suffixes
        files = {}
        if not file_dict:
            return {}
        for name, file in file_dict.items():
            file = Path(file)
            if file_suffixes.get(keyname) != file.suffix.lstrip('.'):
                if file_conversions.get(keyname):
                    print(f'GOT A UNCONVERTED FILE ({file.name}, for {keyname}) WHILE TRANSFERRING DLC; CONVERTING...')
                    func = file_conversions.get(keyname)
                    result = func(file)
                else:
                    print(f'GOT A UNCONVERTED FILE ({file.name}, for {keyname}) WHILE TRANSFERRING DLC AND HAVE NO CONVERTER; THIS MAY FAIL!!')
                    result = file
            else:
                result = file
            url = url_for(
                'dlc_file',
                filename=str(result),
                _external=True
            )
            files[name] = url
        return files
    # generate urls from required files
    result_texs = gen_files(req_texs, 'textures')
    result_mesh = gen_files(req_mesh, 'meshes')
    result_audio = gen_files(req_audio, 'audio')
    # we return the end result urls,
    # and then rely on the client downloading them
    return jsonify({
        'audio': result_audio,
        'meshes': result_mesh,
        'textures': result_texs,
        'persistent': persistent,
    })

@app.route('/dlc/<path:filename>')
def dlc_file(filename):
    return send_file(f'dlc_files/{filename}')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port)

