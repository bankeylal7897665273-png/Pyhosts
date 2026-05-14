import os
import time
import requests
import base64
import mimetypes
from flask import Flask, render_template, request, jsonify, session, redirect, Response
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "NexusSpace_Ultimate_999")

API_KEY = os.getenv("FIREBASE_API_KEY")
DB_URL = os.getenv("FIREBASE_DATABASE_URL")

# --- FIREBASE REST HELPERS ---
def db_get(path):
    res = requests.get(f"{DB_URL}/{path}.json")
    return res.json() if res.ok else None

def db_put(path, data):
    requests.put(f"{DB_URL}/{path}.json", json=data)

def db_patch(path, data):
    requests.patch(f"{DB_URL}/{path}.json", json=data)

def db_delete(path):
    requests.delete(f"{DB_URL}/{path}.json")

def encode_path(path):
    return base64.urlsafe_b64encode(path.encode()).decode().rstrip('=')

# --- AUTH & DASHBOARD ---
@app.route('/')
def home():
    if 'uid' in session: return redirect('/dashboard')
    return render_template('auth.html')

@app.route('/api/auth', methods=['POST'])
def auth():
    data = request.json
    is_login = data.get('action') == 'login'
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:{'signInWithPassword' if is_login else 'signUp'}?key={API_KEY}"
    res = requests.post(url, json={"email": data.get('email'), "password": data.get('password'), "returnSecureToken": True}).json()
    
    if 'idToken' in res:
        session['uid'] = res['localId']
        session.modified = True
        if not is_login: db_put(f"users/{res['localId']}", {"email": data.get('email')})
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": res.get("error", {}).get("message", "Auth Failed")})

@app.route('/dashboard')
def dashboard():
    if 'uid' not in session: return redirect('/')
    all_spaces = db_get("spaces") or {}
    my_spaces = {k: v for k, v in all_spaces.items() if v.get('uid') == session['uid']}
    return render_template('dashboard.html', spaces=my_spaces)

@app.route('/api/create_space', methods=['POST'])
def create_space():
    if 'uid' not in session: return jsonify({"error": "Unauthorized"}), 401
    name = request.json.get('name').lower().strip()
    stype = request.json.get('type')
    if db_get(f"spaces/{name}"): return jsonify({"status": "error", "message": "Space name already taken!"})
    
    # Yellow Building Status
    db_put(f"spaces/{name}", {"uid": session['uid'], "type": stype, "status": "Building ⏳", "created": int(time.time())})
    return jsonify({"status": "success", "space": name})

@app.route('/api/delete_space', methods=['POST'])
def delete_space():
    if 'uid' not in session: return jsonify({"error": "Unauthorized"}), 401
    name = request.json.get('name')
    space = db_get(f"spaces/{name}")
    if space and space['uid'] == session['uid']:
        db_delete(f"spaces/{name}")
        db_delete(f"space_files/{name}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Unauthorized or not found."})

# --- WORKSPACE & FILES ---
@app.route('/workspace/<space_name>')
def workspace(space_name):
    if 'uid' not in session: return redirect('/')
    data = db_get(f"spaces/{space_name}")
    if not data or data['uid'] != session['uid']: return "Access Denied or Space Not Found", 403
    
    files = db_get(f"space_files/{space_name}") or {}
    file_list = [{"path": v['path'], "key": k} for k, v in files.items()]
    return render_template('space.html', space=space_name, data=data, files=file_list, base_url=request.host_url.rstrip('/'))

@app.route('/api/save_file', methods=['POST'])
def save_file():
    if 'uid' not in session: return jsonify({"error": "Unauthorized"}), 401
    d = request.json
    safe_key = encode_path(d['path'])
    
    # 100% Real saving to Firebase
    db_put(f"space_files/{d['space']}/{safe_key}", {"path": d['path'], "content": d['content'], "updated": int(time.time())})
    
    # Green Live Status updated instantly in database
    db_patch(f"spaces/{d['space']}", {"status": "Live 🟢"}) 
    return jsonify({"status": "success"})

@app.route('/api/delete_file', methods=['POST'])
def delete_file():
    if 'uid' not in session: return jsonify({"error": "Unauthorized"}), 401
    db_delete(f"space_files/{request.json.get('space')}/{request.json.get('key')}")
    return jsonify({"status": "success"})

# --- LIVE HOSTING SERVE ---
@app.route('/<space_name>')
@app.route('/<space_name>/<path:file_path>')
def serve(space_name, file_path="index.html"):
    safe_key = encode_path(file_path)
    f_data = db_get(f"space_files/{space_name}/{safe_key}")
    
    if not f_data and file_path == "index.html":
        f_data = db_get(f"space_files/{space_name}/{encode_path('main.py')}")
        
    if f_data:
        content = base64.b64decode(f_data['content'])
        mime, _ = mimetypes.guess_type(file_path)
        if f_data['path'].endswith('.py'):
            mime = "text/plain" # Execute as script or text
        return Response(content, mimetype=mime or "text/html")
        
    return "404 Not Found - Upload files in your workspace", 404

if __name__ == '__main__': 
    app.run(host='0.0.0.0', port=5000)
