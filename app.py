from flask import Flask, request, jsonify, send_file, redirect
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user
from oauthlib.oauth2 import WebApplicationClient
import requests
import yt_dlp
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # Change this to a secure secret key
login_manager = LoginManager(app)
client = WebApplicationClient('your-google-client-id')

# Folder to save downloaded files
DOWNLOAD_FOLDER = "downloads"
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# YouTube DL options
ydl_opts = {
    'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
}

class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

@app.route('/login')
def login():
    google_provider_cfg = requests.get('https://accounts.google.com/.well-known/openid-configuration').json()
    authorization_endpoint = google_provider_cfg['authorization_endpoint']
    request_uri = client.prepare_request_uri(
        authorization_endpoint,
        redirect_uri="http://localhost:5000/callback",
        scope=["openid", "email", "profile"]
    )
    return redirect(request_uri)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    token_url = 'https://oauth2.googleapis.com/token'
    token = client.fetch_token(
        token_url, code=code, client_secret='your-client-secret', redirect_uri="http://localhost:5000/callback"
    )
    # Simulate user login (in practice, verify token and get user info)
    user = User('1')  # Placeholder user ID
    login_user(user)
    return redirect('/dashboard')

@app.route('/dashboard')
@login_required
def dashboard():
    return "Welcome, " + current_user.id + "! This is your dashboard."

@app.route('/download', methods=['POST'])
@login_required
def download_video():
    data = request.json
    url = data.get('url')
    format = data.get('format', 'mp3')

    if not url:
        return jsonify({'error': 'URL প্রয়োজন'}), 400

    try:
        if format == 'mp4':
            ydl_opts['format'] = 'bestvideo+bestaudio/best'
            ydl_opts.pop('postprocessors', None)
        else:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info).replace('.webm', '.mp3') if format == 'mp3' else ydl.prepare_filename(info)

        return jsonify({
            'message': 'ডাউনলোড সফল',
            'file_path': file_path,
            'title': info.get('title', 'অজানা শিরোনাম')
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_file/<path:filename>', methods=['GET'])
@login_required
def get_file(filename):
    return send_file(os.path.join(DOWNLOAD_FOLDER, filename), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)