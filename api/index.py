import os
import time
import requests
import base64
import mimetypes
from flask import Flask, render_template, request, jsonify, session, redirect, Response
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "NexusSpace_Secure_100")

API_KEY = os.getenv("FIREBASE_API_KEY")
DB_URL = os.getenv("FIREBASE_DATABASE_URL")

# --- FIREBASE REST HELPERS ---
def firebase_auth(email, password, is_login=True):
    endpoint = "signInWithPassword" if is_login else "signUp"
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:{endpoint}?key={API_KEY}"
    res = requests.post(url, json={"email": email, "password": password, "returnSecureToken": True})
    return res.json()

def db_get(path):
    res = requests.get(f"{DB_URL}/{path}.json")
    return res.json() if res.ok else None

def db_put(path, data):
    requests.put(f"{DB_URL}/{path}.json", json=data)

def db_patch(path, data):
    requests.patch(f"{DB_URL}/{path}.json", json=data)

def db_delete(path):
    requests.delete(f"{DB_URL}/{path}.json")

# Encode path for safe Firebase Key
def encode_path(path):
    return base64.urlsafe_b64encode(path.encode()).decode().rstrip('=')

# --- MAIN APP ROUTES ---
@app.route('/')
def home():
    if 'uid' in session: return redirect('/dashboard')
    return render_template('auth.html')

@app.route('/api/auth', methods=['POST'])
def auth():
    data = request.json
    is_login = data.get('action') == 'login'
    res = firebase_auth(data.get('email'), data.get('password'), is_login)
    
    if 'idToken' in res:
        uid = res['localId']
        session['uid'] = uid
        session.modified = True
        if not is_login: 
            db_put(f"users/{uid}", {"email": data.get('email')})
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": res.get("error", {}).get("message", "Auth Failed")})

@app.route('/dashboard')
def dashboard():
    if 'uid' not in session: return redirect('/')
    uid = session['uid']
    all_spaces = db_get("spaces") or {}
    my_spaces = {k: v for k, v in all_spaces.items() if v.get('uid') == uid}
    return render_template('dashboard.html', spaces=my_spaces)

@app.route('/api/create_space', methods=['POST'])
def create_space():
    if 'uid' not in session: return jsonify({"error": "Unauthorized"}), 401
    name = request.json.get('name').lower().strip() # BUG FIXED: Lowercase mapping
    type_ = request.json.get('type')
    
    if name in ['api', 'dashboard', 'static', 'admin', 'auth', 'workspace', 'checkout']:
        return jsonify({"status": "error", "message": "Reserved name!"})
        
    if db_get(f"spaces/{name}"):
        return jsonify({"status": "error", "message": "Space name already taken!"})
        
    db_put(f"spaces/{name}", {"uid": session['uid'], "type": type_, "status": "Running 🟢", "created": int(time.time())})
    return jsonify({"status": "success", "space": name}) # Returning exact name for redirect

# --- FILE MANAGER WORKSPACE ---
@app.route('/workspace/<space_name>')
def workspace(space_name):
    if 'uid' not in session: return redirect('/')
    space_data = db_get(f"spaces/{space_name}")
    
    if not space_data or space_data['uid'] != session['uid']:
        return "Unauthorized or Space Not Found. Please create it first.", 404
        
    files = db_get(f"space_files/{space_name}") or {}
    file_list = [{"path": v['path'], "key": k} for k, v in files.items()]
    
    return render_template('space.html', space=space_name, data=space_data, files=file_list, base_url=request.host_url.rstrip('/'))

@app.route('/api/save_file', methods=['POST'])
def save_file():
    if 'uid' not in session: return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    space = data.get('space')
    path = data.get('path').strip('/')
    content = data.get('content') # Base64 encoded
    
    safe_key = encode_path(path)
    db_put(f"space_files/{space}/{safe_key}", {
        "path": path,
        "content": content,
        "updated": int(time.time())
    })
    db_patch(f"spaces/{space}", {"status": "Updated & Live 🟢"})
    return jsonify({"status": "success", "message": f"Deployed {path}!"})

@app.route('/api/delete_file', methods=['POST'])
def delete_file():
    if 'uid' not in session: return jsonify({"error": "Unauthorized"}), 401
    space = request.json.get('space')
    key = request.json.get('key')
    db_delete(f"space_files/{space}/{key}")
    return jsonify({"status": "success", "message": "File deleted."})

# --- LIVE HOSTING SYSTEM ---
@app.route('/<space_name>')
@app.route('/<space_name>/<path:file_path>')
def serve_file(space_name, file_path="index.html"):
    space_data = db_get(f"spaces/{space_name}")
    if not space_data: return f"<h1>404 Space Not Found</h1>", 404
    
    safe_key = encode_path(file_path)
    file_data = db_get(f"space_files/{space_name}/{safe_key}")
    
    if not file_data and file_path == "index.html":
        file_data = db_get(f"space_files/{space_name}/{encode_path('main.py')}")

    if file_data:
        content = base64.b64decode(file_data['content'])
        mime_type, _ = mimetypes.guess_type(file_path)
        if file_data['path'].endswith('.py'):
            mime_type = "text/plain"
            
        return Response(content, mimetype=mime_type or "text/html")
        
    return f"404 File '{file_path}' Not Found", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
