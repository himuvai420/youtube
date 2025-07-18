from flask import Flask, request, jsonify, send_file, redirect, render_template, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user
from oauthlib.oauth2 import WebApplicationClient
import requests
import yt_dlp
import os
from datetime import datetime
import json # Added for JSON serialization/deserialization

app = Flask(__name__)

# Load sensitive information from environment variables
# IMPORTANT: Set these environment variables in Render dashboard
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your-default-secure-secret-key') # Change 'your-default-secure-secret-key' in production
login_manager = LoginManager(app)

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')

if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set as environment variables.")

client = WebApplicationClient(GOOGLE_CLIENT_ID)

# Folder to save downloaded files
# Changed to be inside 'static' for easier serving, though send_file is used
DOWNLOAD_FOLDER = os.path.join(app.static_folder, "downloads") if app.static_folder else "static/downloads"
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# Store download history (in-memory for simplicity, use a database for persistence)
download_history = []
# Path for a simple JSON file to persist history across restarts (optional, but better than nothing)
HISTORY_FILE = 'download_history.json'

def load_history():
    global download_history
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            try:
                download_history = json.load(f)
            except json.JSONDecodeError:
                download_history = [] # Handle empty or corrupt file
    else:
        download_history = []

def save_history():
    with open(HISTORY_FILE, 'w') as f:
        json.dump(download_history, f)

# Load history when app starts
load_history()


# YouTube DL options
ydl_opts = {
    'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'noplaylist': True, # Ensure only single video is downloaded by default
}

class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

# Route for the main UI
@app.route('/')
@login_required
def index():
    return render_template('index.html', history=download_history)

@app.route('/login')
def login():
    google_provider_cfg = requests.get('https://accounts.google.com/.well-known/openid-configuration').json()
    authorization_endpoint = google_provider_cfg['authorization_endpoint']

    redirect_uri = os.environ.get('GOOGLE_REDIRECT_URI', 'http://localhost:5000/callback')

    request_uri = client.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=redirect_uri,
        scope=["openid", "email", "profile"]
    )
    return redirect(request_uri)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    token_url = 'https://oauth2.googleapis.com/token'

    redirect_uri = os.environ.get('GOOGLE_REDIRECT_URI', 'http://localhost:5000/callback')

    token = client.fetch_token(
        token_url, code=code, client_secret=GOOGLE_CLIENT_SECRET, redirect_uri=redirect_uri
    )
    # Simulate user login (in practice, verify token and get user info)
    user = User('1')  # Placeholder user ID
    login_user(user)
    return redirect(url_for('index')) # Redirect to the main page after login

@app.route('/dashboard') # Kept for backward compatibility, but now redirects to index
@login_required
def dashboard():
    return redirect(url_for('index'))

@app.route('/download', methods=['POST'])
@login_required
def download_video():
    data = request.json
    url = data.get('url')
    download_format = data.get('format', 'mp3')
    download_type = data.get('type', 'single_video') # Added type for future playlist support

    if not url:
        return jsonify({'error': 'URL প্রয়োজন'}), 400

    current_ydl_opts = ydl_opts.copy() # Use a copy to modify options per request

    try:
        if download_format == 'mp4':
            current_ydl_opts['format'] = 'bestvideo+bestaudio/best'
            current_ydl_opts.pop('postprocessors', None)
        else: # mp3
            current_ydl_opts['format'] = 'bestaudio/best'
            current_ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        # For playlist support, you'd modify 'noplaylist' based on download_type
        # For now, keeping it 'noplaylist': True as per current backend logic
        current_ydl_opts['noplaylist'] = True


        with yt_dlp.YoutubeDL(current_ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Get the actual downloaded file path
            # yt-dlp might download as .webm and then convert to .mp3
            # We need to find the final file path after post-processing
            file_path = None
            if 'requested_downloads' in info and info['requested_downloads']:
                # For single file, it's usually the first one
                file_path = info['requested_downloads'][0]['filepath']
            elif '_format_note' in info and 'filename' in info:
                # Fallback for simpler cases
                file_path = os.path.join(DOWNLOAD_FOLDER, info['filename'])
            else:
                # Try to construct from outtmpl if direct path not found
                # This is a bit tricky, relying on outtmpl pattern
                base_name = ydl.prepare_filename(info)
                if download_format == 'mp3' and not base_name.endswith('.mp3'):
                    file_path = os.path.splitext(base_name)[0] + '.mp3'
                else:
                    file_path = base_name

            # Ensure the file path is relative to DOWNLOAD_FOLDER for serving
            relative_file_path = os.path.relpath(file_path, DOWNLOAD_FOLDER)
            
            # Add to history
            entry = {
                'id': len(download_history) + 1,
                'title': info.get('title', 'Unknown Title'),
                'status': 'Success',
                'file_name': relative_file_path,
                'timestamp': datetime.now().isoformat()
            }
            download_history.append(entry)
            save_history()

        return jsonify({
            'message': 'ডাউনলোড সফল',
            'file_name': relative_file_path, # Use file_name for frontend
            'title': info.get('title', 'অজানা শিরোনাম')
        })

    except Exception as e:
        # If download fails, remove partially downloaded files to save space
        # This part is complex and might require more sophisticated cleanup
        print(f"Download failed: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/get_file/<path:filename>', methods=['GET'])
@login_required
def get_file(filename):
    full_path = os.path.join(DOWNLOAD_FOLDER, filename)
    if os.path.exists(full_path):
        return send_file(full_path, as_attachment=True)
    else:
        return jsonify({'error': 'File not found'}), 404

@app.route('/get_history', methods=['GET'])
@login_required
def get_history():
    return jsonify(download_history)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)