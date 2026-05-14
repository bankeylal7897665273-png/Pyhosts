import os
import time
import requests
import base64
import mimetypes
from flask import Flask, render_template, request, jsonify, session, redirect, Response
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "Nexus_Ultimate_Secret_2026")

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

# --- ROUTES ---
@app.route('/')
def home():
    if 'uid' in session: return redirect('/dashboard')
    return render_template('auth.html')

@app.route('/api/auth', methods=['POST'])
def auth():
    data = request.json
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:{'signInWithPassword' if data.get('action') == 'login' else 'signUp'}?key={API_KEY}"
    res = requests.post(url, json={"email": data.get('email'), "password": data.get('password'), "returnSecureToken": True}).json()
    if 'idToken' in res:
        session['uid'] = res['localId']
        if data.get('action') != 'login': db_put(f"users/{res['localId']}", {"email": data.get('email')})
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Auth Failed"})

@app.route('/dashboard')
def dashboard():
    if 'uid' not in session: return redirect('/')
    all_spaces = db_get("spaces") or {}
    my_spaces = {k: v for k, v in all_spaces.items() if v.get('uid') == session['uid']}
    return render_template('dashboard.html', spaces=my_spaces)

@app.route('/api/create_space', methods=['POST'])
def create_space():
    name = request.json.get('name').lower().strip()
    if db_get(f"spaces/{name}"): return jsonify({"status": "error", "message": "Name taken!"})
    db_put(f"spaces/{name}", {"uid": session['uid'], "type": request.json.get('type'), "status": "Building ⏳", "created": int(time.time())})
    return jsonify({"status": "success", "space": name})

@app.route('/api/delete_space', methods=['POST'])
def delete_space():
    name = request.json.get('name')
    space_data = db_get(f"spaces/{name}")
    if space_data and space_data['uid'] == session['uid']:
        db_delete(f"spaces/{name}")
        db_delete(f"space_files/{name}")
        return jsonify({"status": "success"})
    return jsonify({"status": "error"})

@app.route('/workspace/<space_name>')
def workspace(space_name):
    if 'uid' not in session: return redirect('/')
    data = db_get(f"spaces/{space_name}")
    if not data or data['uid'] != session['uid']: return "Unauthorized", 404
    files_data = db_get(f"space_files/{space_name}") or {}
    file_list = [{"path": v['path'], "key": k} for k, v in files_data.items()]
    return render_template('space.html', space=space_name, data=data, files=file_list, base_url=request.host_url.rstrip('/'))

@app.route('/api/save_file', methods=['POST'])
def save_file():
    space, path, content = request.json.get('space'), request.json.get('path'), request.json.get('content')
    db_put(f"space_files/{space}/{encode_path(path)}", {"path": path, "content": content})
    db_patch(f"spaces/{space}", {"status": "Live 🟢"})
    return jsonify({"status": "success"})

@app.route('/api/delete_file', methods=['POST'])
def delete_file():
    db_delete(f"space_files/{request.json.get('space')}/{request.json.get('key')}")
    return jsonify({"status": "success"})

@app.route('/<space_name>')
@app.route('/<space_name>/<path:file_path>')
def serve(space_name, file_path="index.html"):
    file_data = db_get(f"space_files/{space_name}/{encode_path(file_path)}")
    if not file_data and file_path == "index.html":
        for p in ['main.py', 'app.py']:
            file_data = db_get(f"space_files/{space_name}/{encode_path(p)}")
            if file_data: break
    if file_data:
        mime = mimetypes.guess_type(file_data['path'])[0] or "text/html"
        return Response(base64.b64decode(file_data['content']), mimetype=mime)
    return "404 Not Found", 404
