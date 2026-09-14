import sys
import os
import re
import json
import time
import logging
import tempfile
import base64
import html
import http.cookiejar
import requests
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Ensure UTF-8 output encoding on Windows console
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Load local .env if present
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

import pypdf
from google import genai
from google.genai import types

app = Flask(__name__)
logger = logging.getLogger("apuntes_ia")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class GeminiConfig:
    """Configuration for Google Gemini AI models and fallback hierarchy.
    Primary: gemini-3.7-flash
    Fallback: gemini-3.6-flash (recommended by Google to replace deprecated 2.5 models)
    """
    PRIMARY_MODEL = "gemini-3.7-flash"
    FALLBACK_MODEL = "gemini-3.6-flash"
    MODELS = [PRIMARY_MODEL, FALLBACK_MODEL]

GEMINI_MODELS = GeminiConfig.MODELS

def get_git_commit_hash():
    """Retrieve current commit hash for deployment verification."""
    render_commit = os.environ.get('RENDER_GIT_COMMIT')
    if render_commit:
        return render_commit[:7]
    try:
        import subprocess
        out = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], stderr=subprocess.DEVNULL)
        return out.decode('utf-8').strip()
    except Exception:
        pass
    return "unknown"

app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload
UPLOAD_FOLDER = Path(__file__).parent / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)

@app.errorhandler(500)
def handle_500(err):
    """Ensure Flask never returns raw HTML 500 pages."""
    return jsonify({
        "success": False,
        "error": "Ocurrió un error inesperado en el servidor al procesar la solicitud."
    }), 500

@app.errorhandler(404)
def handle_404(err):
    return jsonify({
        "success": False,
        "error": "Recurso no encontrado."
    }), 404

def extract_youtube_id(url_or_id):
    """Extract YouTube video ID from various URL patterns or direct ID."""
    if not url_or_id:
        return None
    url = url_or_id.strip()
    
    # Direct 11-char ID
    if re.fullmatch(r'[a-zA-Z0-9_-]{11}', url):
        return url
        
    patterns = [
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/embed\/([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/live\/([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_youtube_metadata(video_id):
    """Get video title and thumbnail via YouTube oEmbed."""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
        resp = requests.get(oembed_url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "title": data.get("title", f"Video {video_id}"),
                "author": data.get("author_name", ""),
                "thumbnail": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                "fallback_thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
            }
    except Exception as e:
        print(f"Error fetching oEmbed metadata: {e}")
    return {
        "title": f"Video de YouTube ({video_id})",
        "author": "YouTube",
        "thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        "fallback_thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    }

import yt_dlp

def get_youtube_cookiefile():
    """Retrieve or materialize YouTube cookies from environment variable or file."""
    cookie_path = os.environ.get('YOUTUBE_COOKIE_PATH', 'cookies.txt')
    if os.path.exists(cookie_path) and os.path.getsize(cookie_path) > 10:
        return cookie_path

    b64_cookies = os.environ.get('YOUTUBE_COOKIES_BASE64')
    if b64_cookies:
        try:
            decoded = base64.b64decode(b64_cookies.strip()).decode('utf-8', errors='ignore')
            tmp_path = os.path.join(tempfile.gettempdir(), 'youtube_cookies.txt')
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(decoded)
            return tmp_path
        except Exception as e:
            logger.warning(f"Error decoding YOUTUBE_COOKIES_BASE64: {e}")

    raw_cookies = os.environ.get('YOUTUBE_COOKIES')
    if raw_cookies and len(raw_cookies.strip()) > 20:
        tmp_path = os.path.join(tempfile.gettempdir(), 'youtube_cookies.txt')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(raw_cookies.strip())
        return tmp_path

    return None

def fetch_and_parse_timedtext(url):
    """Fetch YouTube timedtext XML (srv1 or srv3) and parse into snippets and full text."""
    try:
        r = requests.get(url, timeout=12)
        if r.status_code != 200 or not r.text or not r.text.strip():
            return None
        xml_text = r.text
        snippets = []
        
        # 1. Try format 1: <text start="12.34" dur="2.5">Hello</text>
        re_text = re.compile(r'<text\b[^>]*\bstart="([\d\.]+)"[^>]*>(.*?)</text>', re.DOTALL)
        matches = list(re_text.finditer(xml_text))
        if matches:
            for m in matches:
                start_sec = float(m.group(1))
                txt = html.unescape(re.sub(r'<[^>]+>', '', m.group(2))).strip()
                if txt:
                    snippets.append((start_sec, txt))
        else:
            # 2. Try format 3: <p t="12340" d="2500"><s>Hello</s></p>
            re_p = re.compile(r'<p\b[^>]*\bt="(\d+)"[^>]*>(.*?)</p>', re.DOTALL)
            re_s = re.compile(r'<s\b[^>]*>(.*?)</s>', re.DOTALL)
            for m in re_p.finditer(xml_text):
                start_sec = int(m.group(1)) / 1000.0
                inner = m.group(2)
                s_matches = re_s.findall(inner)
                if s_matches:
                    seg = ''.join(s_matches)
                else:
                    seg = re.sub(r'<[^>]+>', '', inner)
                txt = html.unescape(seg).strip()
                if txt:
                    snippets.append((start_sec, txt))

        if not snippets:
            return None

        full_text = ' '.join([s[1] for s in snippets]).strip()
        timed_snippets = []
        for s in snippets:
            mm = int(s[0] // 60)
            ss = int(s[0] % 60)
            timed_snippets.append(f"[{mm:02d}:{ss:02d}] {s[1]}")
        timed_text = '\n'.join(timed_snippets)

        return {
            "success": True,
            "language": "es",
            "full_text": full_text,
            "timed_text": timed_text,
            "snippets_count": len(snippets)
        }
    except Exception as e:
        logger.warning(f"Error fetching/parsing timedtext XML: {e}")
        return None

def get_innertube_android_data(video_id):
    """Query official YouTube Android Player API.
    Bypasses datacenter web bot challenges, runs in ~300ms, and provides full signed caption tracks and audio URLs.
    """
    try:
        url = "https://www.youtube.com/youtubei/v1/player?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
        payload = {
            "context": {
                "client": {
                    "clientName": "ANDROID",
                    "clientVersion": "20.10.38",
                    "androidSdkVersion": 34,
                    "hl": "es",
                    "gl": "ES",
                    "utcOffsetMinutes": 0
                }
            },
            "videoId": video_id
        }
        headers = {
            "User-Agent": "com.google.android.youtube/20.10.38 (Linux; U; Android 14)",
            "Content-Type": "application/json"
        }

        cookie_file = get_youtube_cookiefile()
        cookies_dict = {}
        if cookie_file and os.path.exists(cookie_file):
            try:
                cj = http.cookiejar.MozillaCookieJar(cookie_file)
                cj.load(ignore_discard=True, ignore_expires=True)
                cookies_dict = {c.name: c.value for c in cj}
            except Exception:
                pass

        resp = requests.post(url, json=payload, headers=headers, cookies=cookies_dict, timeout=10)
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        
        data = resp.json()
        playability = data.get("playabilityStatus", {}).get("status")
        if playability != "OK":
            return None, f"Playability: {playability}"

        raw_tracks = data.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
        caption_tracks = []
        for t in raw_tracks:
            name = t.get("name", {}).get("runs", [{}])[0].get("text", "Subtítulos")
            base_url = t.get("baseUrl", "")
            if "fmt=" not in base_url:
                base_url += "&fmt=srv1"
            caption_tracks.append({
                "name": name,
                "language_code": t.get("languageCode", "es"),
                "base_url": base_url,
                "is_auto": t.get("kind") == "asr" or "auto" in name.lower()
            })

        # Prefer Spanish first, then English
        caption_tracks.sort(key=lambda x: 0 if x["language_code"].startswith("es") else (1 if x["language_code"].startswith("en") else 2))

        sd = data.get("streamingData", {})
        prog_formats = sd.get("formats", [])
        adaptive_formats = sd.get("adaptiveFormats", [])
        
        # Prefer progressive MP4 format (itag 18 / 22) because YouTube CDN allows continuous streaming
        # without token 403 errors or strict byte-range limits on datacenter servers.
        selected_audio = next((f for f in prog_formats if f.get("itag") in [18, 22] and f.get("url")), None)
        if not selected_audio:
            audio_formats = [f for f in adaptive_formats if f.get("mimeType", "").startswith("audio/") and f.get("url")]
            if audio_formats:
                selected_audio = next((f for f in audio_formats if f.get("itag") in [140, 139, 251, 250]), audio_formats[0])

        details = data.get("videoDetails", {})
        title = details.get("title", f"Video {video_id}")
        author = details.get("author", "YouTube")
        duration_sec = 0
        try:
            duration_sec = int(details.get("lengthSeconds", 0))
        except Exception:
            pass

        return {
            "title": title,
            "author": author,
            "thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            "fallback_thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            "duration_seconds": duration_sec,
            "caption_tracks": caption_tracks,
            "has_captions": len(caption_tracks) > 0,
            "has_audio": selected_audio is not None,
            "audio_url": selected_audio.get("url") if selected_audio else None,
            "audio_ext": "webm" if (selected_audio and "webm" in selected_audio.get("mimeType", "")) else "m4a",
            "audio_headers": {
                "User-Agent": "com.google.android.youtube/20.10.38 (Linux; U; Android 14)"
            }
        }, "ok"
    except Exception as e:
        logger.warning(f"Innertube Android API failed for {video_id}: {e}")
        return None, str(e)

def get_youtube_transcript_api(video_id):
    """Retrieve subtitles directly via Innertube Android API or fallback to youtube-transcript-api."""
    # 1. Primary: Fast, datacenter-immune Innertube Android timedtext
    try:
        idata, _ = get_innertube_android_data(video_id)
        if idata and idata.get("caption_tracks"):
            for track in idata["caption_tracks"]:
                if track.get("base_url"):
                    parsed = fetch_and_parse_timedtext(track["base_url"])
                    if parsed and parsed.get("full_text"):
                        parsed["language"] = track.get("language_code", "es")
                        return parsed
    except Exception as ie:
        logger.warning(f"Innertube timedtext extraction failed for {video_id}: {ie}")

    # 2. Secondary fallback: youtube-transcript-api
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept-Language': 'es-419,es;q=0.9,en;q=0.8'
        })
        cookie_file = get_youtube_cookiefile()
        if cookie_file and os.path.exists(cookie_file):
            try:
                cj = http.cookiejar.MozillaCookieJar(cookie_file)
                cj.load(ignore_discard=True, ignore_expires=True)
                session.cookies = cj
            except Exception as ce:
                logger.warning(f"Could not load cookies into requests session: {ce}")

        snippets = []
        lang = 'es'
        if hasattr(YouTubeTranscriptApi, 'list'):
            api = YouTubeTranscriptApi(http_client=session)
            tl = api.list(video_id)
            try:
                transcript_obj = tl.find_transcript(['es', 'es-419', 'es-ES', 'en', 'en-US'])
            except Exception:
                transcript_obj = next(iter(tl))
            lang = getattr(transcript_obj, 'language_code', 'es')
            fetched = transcript_obj.fetch()
            snippets = [{'text': s.text, 'start': s.start, 'duration': s.duration} for s in fetched.snippets]
        elif hasattr(YouTubeTranscriptApi, 'get_transcript'):
            snippets = YouTubeTranscriptApi.get_transcript(video_id, languages=['es', 'es-419', 'en', 'en-US'])
        
        if not snippets:
            return None

        full_text = ' '.join([s['text'] for s in snippets if s.get('text')]).strip()
        timed_snippets = []
        for s in snippets:
            text = s.get('text', '').strip()
            if text:
                mm = int(s.get('start', 0) // 60)
                ss = int(s.get('start', 0) % 60)
                timed_snippets.append(f"[{mm:02d}:{ss:02d}] {text}")
        timed_text = '\n'.join(timed_snippets)

        return {
            "success": True,
            "language": lang,
            "full_text": full_text,
            "timed_text": timed_text,
            "snippets_count": len(snippets)
        }
    except Exception as e:
        logger.warning(f"youtube-transcript-api check failed for {video_id}: {e}")
        return None

def get_youtube_video_data(video_id):
    """Retrieve video metadata, subtitle tracks, and audio streaming info with progressive fallbacks:
    1. Direct Innertube Android API (fastest, unblocked on datacenters)
    2. yt-dlp with android player client
    3. youtube-transcript-api
    4. oEmbed metadata
    """
    innertube_err = None
    ytdlp_err = None
    transcript_err = None

    # 1. Primary: Innertube Android API
    vdata, err = get_innertube_android_data(video_id)
    if vdata and (vdata.get("has_captions") or vdata.get("has_audio")):
        return vdata, {"status": "ok_via_innertube_android"}
    innertube_err = err

    # 2. Secondary fallback: yt-dlp with android player client only
    cookie_file = get_youtube_cookiefile()
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'extractor_args': {
            'youtube': {
                'player_client': ['android'],
                'player_skip': ['webpage', 'configs']
            }
        },
        'http_headers': {
            'User-Agent': 'com.google.android.youtube/20.10.38 (Linux; U; Android 14)',
            'Accept-Language': 'es-419,es;q=0.9,en;q=0.8'
        }
    }
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            subs = info.get('subtitles', {})
            auto_subs = info.get('automatic_captions', {})
            caption_tracks = []
            
            for lang_code in ['es', 'es-419', 'es-ES', 'es-US', 'en', 'en-US']:
                track_list = subs.get(lang_code) or auto_subs.get(lang_code)
                if track_list:
                    pref = next((s['url'] for s in track_list if s.get('ext') == 'srv1'), None)
                    if not pref:
                        pref = next((s['url'] for s in track_list if s.get('ext') in ['srv3', 'vtt']), track_list[0]['url'])
                    caption_tracks.append({
                        "name": f"Español ({lang_code})" if lang_code.startswith('es') else f"Inglés ({lang_code})",
                        "language_code": lang_code,
                        "base_url": pref,
                        "is_auto": lang_code in auto_subs and lang_code not in subs
                    })
            
            if not caption_tracks:
                for lang_code, track_list in list(subs.items())[:3] + list(auto_subs.items())[:3]:
                    pref = next((s['url'] for s in track_list if s.get('ext') in ['srv1', 'srv3']), track_list[0]['url'])
                    caption_tracks.append({
                        "name": f"Subtítulos ({lang_code})",
                        "language_code": lang_code,
                        "base_url": pref,
                        "is_auto": lang_code in auto_subs and lang_code not in subs
                    })

            formats = info.get('formats', [])
            audio_formats = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none' and f.get('url')]
            selected_audio = None
            if audio_formats:
                selected_audio = next((f for f in audio_formats if f.get('format_id') in ['139', '250', '249']), audio_formats[0])
            elif formats:
                formats_with_audio = [f for f in formats if f.get('acodec') != 'none' and f.get('url')]
                if formats_with_audio:
                    selected_audio = formats_with_audio[0]

            return {
                "title": info.get('title', f"Video {video_id}"),
                "author": info.get('uploader', 'YouTube'),
                "thumbnail": info.get('thumbnail', f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"),
                "fallback_thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
                "duration_seconds": int(info.get('duration', 0)),
                "caption_tracks": caption_tracks,
                "has_captions": len(caption_tracks) > 0,
                "has_audio": selected_audio is not None,
                "audio_url": selected_audio.get('url') if selected_audio else None,
                "audio_headers": selected_audio.get('http_headers', {}) if selected_audio else {},
                "audio_format_id": selected_audio.get('format_id') if selected_audio else None,
                "audio_ext": selected_audio.get('ext', 'm4a') if selected_audio else 'm4a'
            }, {"status": "ok_via_yt_dlp"}
    except Exception as e:
        ytdlp_err = str(e)
        logger.warning(f"yt-dlp extract failed for {video_id}: {e}")

    # 3. Tertiary fallback: youtube-transcript-api
    t_data = get_youtube_transcript_api(video_id)
    if t_data and t_data.get("full_text"):
        meta = get_youtube_metadata(video_id)
        return {
            "title": meta.get("title", f"Video {video_id}"),
            "author": meta.get("author", "YouTube"),
            "thumbnail": meta.get("thumbnail", f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"),
            "fallback_thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            "duration_seconds": 0,
            "caption_tracks": [{
                "name": f"Transcripción Directa ({t_data.get('language', 'es')})",
                "language_code": t_data.get('language', 'es'),
                "base_url": f"/api/youtube-transcript?videoId={video_id}",
                "is_auto": False,
                "is_api": True
            }],
            "has_captions": True,
            "has_audio": False,
            "audio_url": None,
            "audio_headers": {},
            "audio_format_id": None,
            "audio_ext": "m4a"
        }, {"status": "ok_via_transcript_api"}
    transcript_err = "No transcript found via Innertube or youtube-transcript-api"

    # 4. Final fallback: oEmbed
    meta = get_youtube_metadata(video_id)
    return {
        "title": meta.get("title", f"Video {video_id}"),
        "author": meta.get("author", "YouTube"),
        "thumbnail": meta.get("thumbnail", f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"),
        "fallback_thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        "duration_seconds": 0,
        "caption_tracks": [],
        "has_captions": False,
        "has_audio": False,
        "audio_url": None,
        "audio_headers": {},
        "audio_format_id": None,
        "audio_ext": "m4a"
    }, {
        "status": "metadata_only",
        "innertube_err": innertube_err,
        "ytdlp_err": ytdlp_err,
        "transcript_err": transcript_err
    }

def get_youtube_duration_seconds(video_id):
    """Retrieve video duration in seconds via Innertube Android API, yt-dlp, or fallback."""
    try:
        idata, _ = get_innertube_android_data(video_id)
        if idata and idata.get("duration_seconds") and idata["duration_seconds"] > 0:
            return idata["duration_seconds"]
    except Exception:
        pass

    try:
        ydl_opts = {
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            if info and info.get('duration'):
                return int(info['duration'])
    except Exception:
        pass

    return 3600  # Default to 1 hour if unknown

def get_youtube_caption_tracks(video_id):
    """Retrieve available subtitle tracks and signed baseUrls."""
    data, debug_info = get_youtube_video_data(video_id)
    if data and data.get("caption_tracks"):
        return data["caption_tracks"], debug_info
    return [], debug_info



@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status', methods=['GET'])
def check_status():
    has_env_key = bool(os.environ.get('GEMINI_API_KEY'))
    return jsonify({
        "status": "ready",
        "engine": "Google Gemini AI (Direct SDK)",
        "commit": get_git_commit_hash(),
        "default_model": GeminiConfig.PRIMARY_MODEL,
        "fallback_model": GeminiConfig.FALLBACK_MODEL,
        "models": GeminiConfig.MODELS,
        "has_env_key": has_env_key,
        "version": "2.1.0",
        "message": "Servicio activo. Potenciado exclusivamente por Google Gemini AI para uso personal y privado."
    })

@app.route('/api/health-gemini', methods=['GET', 'POST'])
def health_gemini():
    api_key = extract_gemini_api_key(request)
    if not api_key:
        return jsonify({
            "success": False,
            "configured": False,
            "error": "No se encontró clave de API de Gemini."
        }), 200
    
    return jsonify({
        "success": True,
        "configured": True,
        "valid_format": len(api_key) >= 20,
        "default_model": GeminiConfig.PRIMARY_MODEL,
        "fallback_model": GeminiConfig.FALLBACK_MODEL,
        "models": GeminiConfig.MODELS,
        "commit": get_git_commit_hash()
    })

@app.route('/api/youtube-preview', methods=['POST'])
def youtube_preview():
    data = request.get_json(silent=True) or request.form or {}
    url = data.get('url', '')
    video_id = extract_youtube_id(url)
    if not video_id:
        return jsonify({"success": False, "error": "Enlace de YouTube no válido"}), 400
        
    vdata, debug_info = get_youtube_video_data(video_id)
    vdata["video_id"] = video_id
    vdata["success"] = True
    vdata["debug"] = debug_info
    return jsonify(vdata)

@app.route('/api/youtube-tracks', methods=['GET', 'POST'])
def youtube_tracks():
    """Lightweight endpoint returning available caption track URLs for client-side download."""
    url = ''
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form or {}
        url = data.get('url') or data.get('videoId') or ''
    else:
        url = request.args.get('url') or request.args.get('videoId') or ''
        
    video_id = extract_youtube_id(url)
    if not video_id:
        return jsonify({"success": False, "error": "Enlace o ID de YouTube no válido."}), 400
        
    vdata, debug_info = get_youtube_video_data(video_id)
    return jsonify({
        "success": True,
        "video_id": video_id,
        "title": vdata.get("title", f"Video {video_id}"),
        "thumbnail": vdata.get("thumbnail", ""),
        "has_captions": vdata.get("has_captions", False),
        "has_audio": vdata.get("has_audio", False),
        "caption_tracks": vdata.get("caption_tracks", []),
        "debug": debug_info
    })

@app.route('/api/youtube-transcript', methods=['GET', 'POST'])
def youtube_transcript():
    """Retrieve full transcript text of a YouTube video via youtube-transcript-api without downloading media."""
    url = ''
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form or {}
        url = data.get('url') or data.get('videoId') or ''
    else:
        url = request.args.get('url') or request.args.get('videoId') or ''
        
    video_id = extract_youtube_id(url)
    if not video_id:
        return jsonify({"success": False, "error": "ID o enlace de video no válido."}), 400

    t_data = get_youtube_transcript_api(video_id)
    if t_data and t_data.get("full_text"):
        return jsonify({
            "success": True,
            "video_id": video_id,
            "full_text": t_data["full_text"],
            "timed_text": t_data["timed_text"],
            "language": t_data.get("language", "es"),
            "snippets_count": t_data.get("snippets_count", 0)
        })

    return jsonify({
        "success": False,
        "video_id": video_id,
        "error": "No se encontraron subtítulos ni transcripciones para este video en YouTube."
    }), 404

@app.route('/api/youtube-audio', methods=['GET'])
def youtube_audio():
    """Stream audio of YouTube video directly to client for AI Speech-to-Text transcription."""
    video_id = extract_youtube_id(request.args.get('url') or request.args.get('videoId') or '')
    if not video_id:
        return jsonify({"success": False, "error": "ID o enlace de video no válido."}), 400
        
    vdata, debug_info = get_youtube_video_data(video_id)
    if not vdata or not vdata.get("audio_url"):
        error_msg = (
            "YouTube bloqueó temporalmente la extracción de audio desde el servidor (bot check / IP de datacenter). "
            "Para solucionarlo, puedes configurar cookies de YouTube en la variable de entorno YOUTUBE_COOKIES en Render "
            "o utilizar un video con subtítulos disponibles."
        )
        return jsonify({
            "success": False, 
            "error": error_msg, 
            "debug": debug_info
        }), 404

    audio_url = vdata["audio_url"]
    audio_headers = vdata.get("audio_headers", {})
    ext = vdata.get("audio_ext", "m4a")
    content_type = "audio/webm" if ext == "webm" else "audio/mp4"

    def stream_audio():
        # Stream audio up to ~24 MB (under Puter.js 25MB speech2txt limit)
        req_headers = dict(audio_headers)
        req_headers["Range"] = "bytes=0-24999999"
        
        # Load cookies if available
        cookie_file = get_youtube_cookiefile()
        cookies_dict = {}
        if cookie_file and os.path.exists(cookie_file):
            try:
                cj = http.cookiejar.MozillaCookieJar(cookie_file)
                cj.load(ignore_discard=True, ignore_expires=True)
                cookies_dict = {c.name: c.value for c in cj}
            except Exception:
                pass

        try:
            with requests.get(audio_url, headers=req_headers, cookies=cookies_dict, stream=True, timeout=25) as r:
                if r.status_code in [200, 206]:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            yield chunk
                else:
                    logger.error(f"YouTube audio stream returned HTTP status {r.status_code}")
        except Exception as e:
            logger.error(f"Error streaming audio from YouTube: {e}")

    return Response(
        stream_with_context(stream_audio()),
        content_type=content_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Disposition": f'attachment; filename="youtube_{video_id}.{ext}"'
        }
    )



@app.route('/api/demo', methods=['GET'])
def get_demo_notes():
    """Return a high-quality pre-generated study note for instant preview and testing."""
    sample = {
        "title": "Arquitectura y Fundamentos de Redes Neuronales Artificiales",
        "topic_overview": "Guía maestra que desglosa el funcionamiento matemático y estructural de los modelos de Deep Learning: desde el perceptrón simple hasta el algoritmo de Backpropagation y optimización con descenso de gradiente.",
        "estimated_study_time": "25 min",
        "sources": [
            {
                "type": "youtube",
                "title": "Clase Magistral: Deep Learning desde Cero",
                "thumbnail": "https://img.youtube.com/vi/aircAruvnKk/maxresdefault.jpg"
            },
            {
                "type": "pdf",
                "filename": "Capitulo4_Optimizacion_Gradiente.pdf",
                "pages": 18
            }
        ],
        "key_takeaways": [
            {
                "type": "critical",
                "title": "El Problema del Gradiente Desvaneciente",
                "description": "En redes profundas con funciones como Sigmoide, las derivadas menores a 1 se multiplican sucesivamente por la regla de la cadena, haciendo que los pesos de las primeras capas casi no se actualicen."
            },
            {
                "type": "rule",
                "title": "Regla de Oro de Inicialización",
                "description": "Nunca inicialices los pesos en cero: esto genera simetría en todas las neuronas de una capa oculta y aprenden exactamente la misma característica. Usa He o Xavier."
            },
            {
                "type": "tip",
                "title": "Elección de Función de Activación",
                "description": "Usa ReLU o Leaky ReLU en capas intermedias por su eficiencia computacional y gradiente no saturante en positivos. Reserva Softmax únicamente para la capa de salida multiclase."
            },
            {
                "type": "warning",
                "title": "Cuidado con el Sobreajuste (Overfitting)",
                "description": "Si la pérdida de entrenamiento baja pero la de validación sube, aplica Dropout ($p \\in [0.2, 0.5]$) o regularización $L_2$ de inmediato."
            }
        ],
        "developments": [
            {
                "unit_number": 1,
                "title": "El Perceptrón y la Neurona Artificial",
                "content_markdown": "Una neurona artificial procesa un vector de entradas $\\mathbf{x} = [x_1, x_2, \\dots, x_n]^T$ ponderado por un vector de pesos $\\mathbf{w}$ y un sesgo o bias $b$.\n\n### 1.1 Combinación Lineal\nLa suma ponderada se expresa algebraicamente como:\n$$z = \\sum_{i=1}^{n} w_i x_i + b = \\mathbf{w}^T \\mathbf{x} + b$$\n\n### 1.2 Aplicación de la Función No Lineal\nPara que la red sea capaz de aproximar relaciones no lineales (Teorema de Aproximación Universal), aplicamos una función de activación $\\sigma(z)$:\n$$a = \\sigma(z) = \\frac{1}{1 + e^{-z}}$$\n\nSi no tuviéramos activaciones no lineales, una red de 100 capas colapsaría matemáticamente en una simple transformación afín de una sola capa.",
                "visual_description": "Esquema vectorial que muestra flechas de entrada convergiendo en un nodo sumador Σ, seguido por el bloque de activación σ(z) que produce la salida escalar.",
                "mermaid_diagram": "graph LR\n    X1[x1 Entrante] -->|w1| SUM[Suma Ponderada Σ + b]\n    X2[x2 Entrante] -->|w2| SUM\n    X3[x3 Entrante] -->|w3| SUM\n    SUM --> ACT[Función σ: ReLU / Sigmoide]\n    ACT --> Y[Salida Activada a]"
            },
            {
                "unit_number": 2,
                "title": "Backpropagation y Regla de la Cadena",
                "content_markdown": "El aprendizaje consiste en minimizar la función de costo $J(W, b)$ utilizando el Descenso de Gradiente estocástico.\n\n### 2.1 Cálculo del Gradiente\nPara actualizar cualquier peso $w_{ij}^{(l)}$ en la capa $l$, calculamos la derivada parcial mediante la regla de la cadena del cálculo multivariable:\n$$\\frac{\\partial J}{\\partial w_{ij}^{(l)}} = \\frac{\\partial J}{\\partial a^{(l)}} \\cdot \\frac{\\partial a^{(l)}}{\\partial z^{(l)}} \\cdot \\frac{\\partial z^{(l)}}{\\partial w_{ij}^{(l)}}$$\n\n### 2.2 Regla de Actualización de Pesos\nCon una tasa de aprendizaje $\\alpha$:\n$$w_{ij}^{(l)} \\leftarrow w_{ij}^{(l)} - \\alpha \\frac{\\partial J}{\\partial w_{ij}^{(l)}}$$",
                "visual_description": "Diagrama de propagación hacia adelante (Forward Pass en verde) y flujo de retropropagación del gradiente (Backward Pass en rojo) a través de las capas de la red.",
                "mermaid_diagram": "graph LR\n    Entrada[Datos de Entrada] -->|Forward Pass| Oculta[Capas Ocultas]\n    Oculta -->|Forward Pass| Salida[Predicción]\n    Salida -->|Función de Pérdida| Loss[Cálculo del Error J]\n    Loss -.->|Backpropagation: Regla de la Cadena| Oculta\n    Oculta -.->|Actualización de Pesos Δw| Entrada"
            }
        ],
        "general_diagram": {
            "title": "Pipeline Completo de Aprendizaje Profundo",
            "mermaid_code": "graph TD\n    A[Datos Crudos: YouTube / PDF] --> B[Preprocesamiento & Extracción]\n    B --> C[Forward Pass: Combinación Lineal + Activación]\n    C --> D[Cálculo de Función de Costo J]\n    D --> E{¿Error < Umbral?}\n    E -- No --> F[Backward Pass: Cálculo de Gradientes]\n    F --> G[Optimizador Adam / SGD: Ajuste de Pesos]\n    G --> C\n    E -- Sí --> H[Modelo Convergente y Listo]"
        },
        "flashcards": [
            {
                "topic": "Arquitectura",
                "question": "¿Por qué es indispensable incluir funciones de activación no lineales entre capas?",
                "answer": "Porque sin no-linealidades, la composición de múltiples capas lineales es matemáticamente equivalente a una sola capa lineal, perdiendo la capacidad de modelar patrones complejos."
            },
            {
                "topic": "Optimización",
                "question": "¿Qué representa la tasa de aprendizaje (learning rate $\\alpha$)?",
                "answer": "Determina el tamaño del paso que dan los pesos en dirección opuesta al gradiente en cada iteración. Si es muy grande diverge; si es muy pequeña tarda demasiado en converger."
            },
            {
                "topic": "Activaciones",
                "question": "¿Cuál es la principal ventaja de ReLU frente a Sigmoide en capas ocultas?",
                "answer": "ReLU no satura para valores positivos (su derivada es 1), evitando el desvanecimiento del gradiente y siendo mucho más rápida de calcular."
            },
            {
                "topic": "Regularización",
                "question": "¿Cómo funciona la técnica de Dropout durante el entrenamiento?",
                "answer": "Desactiva aleatoriamente una fracción de neuronas en cada pasada de entrenamiento, obligando a la red a no depender de ninguna neurona específica y reduciendo el sobreajuste."
            }
        ],
        "quiz": [
            {
                "question": "Si inicializamos todos los pesos de una red neuronal multicapa con el valor exacto de cero, ¿qué ocurre?",
                "options": [
                    "La red aprende mucho más rápido porque parte del punto neutro.",
                    "Todas las neuronas de una misma capa reciben el mismo gradiente y aprenden idénticos pesos (problema de simetría).",
                    "El gradiente se vuelve infinito en la primera pasada.",
                    "La red funciona normalmente siempre que el bias sea distinto de cero."
                ],
                "correct_index": 1,
                "explanation": "Al tener pesos idénticos, la derivada de la pérdida respecto a cada peso es idéntica en toda la capa, lo que impide que las neuronas se especialicen en diferentes características."
            },
            {
                "question": "¿Qué fórmula representa la función de activación ReLU?",
                "options": [
                    "f(x) = 1 / (1 + e^(-x))",
                    "f(x) = max(0, x)",
                    "f(x) = tanh(x)",
                    "f(x) = e^x / Σ e^(x_j)"
                ],
                "correct_index": 1,
                "explanation": "ReLU (Rectified Linear Unit) devuelve 0 cuando x < 0 y devuelve x cuando x ≥ 0, representada como max(0, x)."
            },
            {
                "question": "¿Cuál es la principal causa del desvanecimiento del gradiente (vanishing gradient)?",
                "options": [
                    "Tasas de aprendizaje demasiado altas que superan el óptimo.",
                    "Multiplicación sucesiva de derivadas menores a 1 al aplicar la regla de la cadena hacia atrás.",
                    "Utilizar conjuntos de datos con muy pocas muestras.",
                    "Usar la función Softmax en la capa de salida."
                ],
                "correct_index": 1,
                "explanation": "Al retropropagar el error a través de muchas capas con funciones de activación cuyas derivadas tienen un máximo pequeño (ej. 0.25 para sigmoide), el producto de derivadas decrece exponencialmente hacia cero."
            }
        ],
        "exam_tips": [
            "Pregunta típica: Demostrar matemáticamente por qué dos capas lineales sucesivas W2(W1 * x + b1) + b2 equivalen a una sola capa W' * x + b'. Ten clara la propiedad distributiva matricial.",
            "Ojo con confundir función de pérdida (Loss, evaluada en un único ejemplo) con función de costo (Cost, promedio de pérdidas en todo el lote o dataset)."
        ],
        "glossary": [
            {
                "term": "Backpropagation",
                "definition": "Algoritmo basado en la regla de la cadena para calcular el gradiente de la función de costo respecto a cada peso de la red."
            },
            {
                "term": "Época (Epoch)",
                "definition": "Una pasada completa hacia adelante y hacia atrás de todo el conjunto de datos de entrenamiento a través de la red."
            },
            {
                "term": "Hiperparámetro",
                "definition": "Variable configurada por el usuario antes de entrenar (tasa de aprendizaje, número de capas, tamaño de lote), a diferencia de los pesos que los aprende la red."
            }
        ]
    }
    return jsonify({"success": True, "data": sample})

# ---------------------------------------------------------------------------
# Google Gemini AI Integration & Study Notes Generation
# ---------------------------------------------------------------------------

GEMINI_MODELS = GeminiConfig.MODELS

SYSTEM_PROMPT = """Eres un catedrático universitario de élite y pedagogo experto.
Tu misión es transformar el material recibido (videos de YouTube, documentos PDF, audios o apuntes) en un conjunto magistral de apuntes de estudio universitarios, profundos, estructurados, claros y estéticamente atractivos.

DEBES responder EXCLUSIVAMENTE con un único objeto JSON válido (sin texto introductorio ni explicaciones fuera del JSON) con la siguiente estructura exacta:
{
  "title": "Título conciso, profesional y atractivo del tema",
  "topic_overview": "Resumen ejecutivo de alto nivel que explica la importancia, alcance e impacto del tema (2-3 párrafos)",
  "estimated_study_time": "ej: 25 min",
  "key_takeaways": [
    {
      "type": "critical",
      "title": "Título del concepto crítico",
      "description": "Explicación directa y memorable."
    },
    {
      "type": "rule",
      "title": "Regla de oro o principio",
      "description": "Principio rector o axioma a recordar siempre."
    },
    {
      "type": "tip",
      "title": "Consejo de aplicación práctica",
      "description": "Cómo aplicar este conocimiento en la práctica."
    },
    {
      "type": "warning",
      "title": "Error o trampa común",
      "description": "Equívoco frecuente que cometen los estudiantes y cómo evitarlo."
    }
  ],
  "developments": [
    {
      "unit_number": 1,
      "title": "Nombre de la Unidad Temática",
      "content_markdown": "Desarrollo profundo y exhaustivo en formato Markdown. Usa subtítulos (###), listas numeradas, viñetas y ejemplos claros. Si incluye fórmulas matemáticas o notación científica, utiliza KaTeX válido: $inline$ o $$bloque$$.",
      "visual_description": "Descripción conceptual de lo que representa esquemáticamente esta sección.",
      "mermaid_diagram": "graph TD\\n    A[Paso 1] --> B[Paso 2]\\n    B --> C[Resultado]"
    }
  ],
  "general_diagram": {
    "title": "Mapa Conceptual Global",
    "mermaid_code": "graph TD\\n    A[Tema Central] --> B[Eje Teórico]\\n    A --> C[Eje Práctico]"
  },
  "flashcards": [
    {
      "topic": "Nombre del concepto o eje",
      "question": "¿Pregunta desafiante para autoevaluación activa?",
      "answer": "Respuesta pedagógica, rigurosa y directa."
    }
  ],
  "quiz": [
    {
      "question": "Pregunta de opción múltiple estilo examen universitario",
      "options": ["Opción A", "Opción B", "Opción C", "Opción D"],
      "correct_index": 0,
      "explanation": "Explicación detallada de por qué esta es la opción correcta y por qué las otras son incorrectas."
    }
  ],
  "exam_tips": [
    "Consejo estratégico para exámenes orales o escritos sobre este tema."
  ],
  "glossary": [
    {
      "term": "Término técnico",
      "definition": "Definición riguroora y clara del término."
    }
  ]
}

Reglas mandatorias:
1. 'key_takeaways': incluir entre 3 y 6 elementos variando los tipos ('critical', 'rule', 'tip', 'warning').
2. 'developments': desarrollar entre 2 y 5 unidades exhaustivas. Si el tema incluye matemática o lógica, incluye fórmulas completas en KaTeX ($ y $$).
3. 'general_diagram': diagrama conceptual en sintaxis Mermaid válida (graph TD o graph LR).
4. 'flashcards': entre 4 y 8 tarjetas de memorización activa.
5. 'quiz': entre 3 y 5 preguntas de opción múltiple con 4 opciones cada una y 'correct_index' (0, 1, 2 o 3).
6. 'exam_tips': entre 2 y 4 consejos para exámenes.
7. 'glossary': entre 3 y 6 definiciones técnicas clave.
8. Todo el contenido debe estar en ESPAÑOL fluido, académico y pedagógico.
9. En fórmulas KaTeX, asegúrate de escapar correctamente las barras invertidas en el JSON (ej: \\\\frac{a}{b}, \\\\sigma).
"""

def extract_gemini_api_key(req):
    """Extract Gemini API Key from header, form, json body, query param, or environment."""
    key = req.headers.get("X-Gemini-Api-Key")
    if key and key.strip():
        return key.strip()
    
    if req.is_json:
        body = req.get_json(silent=True) or {}
        key = body.get("apiKey")
        if key and str(key).strip():
            return str(key).strip()
    elif req.form:
        key = req.form.get("apiKey")
        if key and str(key).strip():
            return str(key).strip()
            
    key = req.args.get("apiKey")
    if key and str(key).strip():
        return str(key).strip()

    env_key = os.environ.get("GEMINI_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()

    return None

def extract_pdf_text(filepath):
    """Extract readable text from PDF pages using pypdf."""
    try:
        reader = pypdf.PdfReader(filepath)
        pages_text = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                pages_text.append(f"--- Página {i+1} ---\n{text.strip()}")
        return '\n\n'.join(pages_text)
    except Exception as e:
        logger.warning(f"Error extracting PDF text: {e}")
        return ""

def robust_parse_json(text):
    """Clean and parse JSON from Gemini, handling markdown code fences, trailing commas, and unescaped LaTeX backslashes."""
    if not text:
        raise ValueError("Texto de respuesta vacío de Gemini.")
    
    cleaned = text.strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'```\s*$', '', cleaned, flags=re.MULTILINE).strip()
    
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start != -1 and end != -1:
        cleaned = cleaned[start:end+1]
        
    try:
        return json.loads(cleaned)
    except Exception:
        # Escape invalid backslashes (especially from LaTeX like \frac, \sigma, \begin, etc.)
        fixed = re.sub(r'\\(?![\\"/bfnrtu])', r'\\\\', cleaned)
        try:
            return json.loads(fixed)
        except Exception:
            fixed2 = re.sub(r',\s*([\]}])', r'\1', fixed)
            return json.loads(fixed2)

MAP_SOURCE_SYSTEM_PROMPT = """Eres un docente universitario y pedagogo de élite.
Tu objetivo es analizar exhaustivamente la fuente de estudio provista (video audiovisual, audio, PDF o transcripción) y extraer una SÍNTESIS TÉCNICA Y PEDAGÓGICA RIGUROSA.

Debes extraer y explicar con máximo detalle:
1. CONCEPTOS TEÓRICOS FUNDAMENTALES: Principios físicos, teoremas, hipótesis y fundamentos paso a paso.
2. FÓRMULAS, ECUACIONES Y MODELOS MATEMÁTICOS: Escribe TODAS las fórmulas matemáticas y deducciones utilizando notación KaTeX válida ($inline$ y $$bloque$$). Explica el significado físico de cada variable y constante.
3. PROCEDIMIENTOS TÉCNICOS Y CRITERIOS PRÁCTICOS: Metodologías de cálculo, secuencias constructivas, normativas o criterios de diseño aplicados.
4. EJEMPLOS, CASOS DE APLICACIÓN Y ESQUEMAS: Si en el material se mencionan o muestran esquemas, diagramas o pizarras, descríbelos conceptualmente con precisión.
5. DEFINICIONES CLAVE: Términos técnicos con su definición formal.

Conserva todo el rigor científico y académico del material. Escribe en ESPAÑOL fluido, claro y estructurado con subtítulos Markdown (###).
"""

def call_gemini_with_fallback(client, contents_parts, system_instruction=None, response_mime_type=None, temperature=0.3):
    """Call Gemini using GEMINI_MODELS hierarchy with automatic exponential backoff on 503/transient errors."""
    attempted_errors = {}
    
    for model_name in GEMINI_MODELS:
        max_retries = 2
        for attempt in range(1, max_retries + 2):
            log_start = f"[GEMINI REQUEST] Consultando modelo: {model_name} (Intento {attempt}/{max_retries + 1})"
            logger.info(log_start)
            print(log_start, flush=True)

            try:
                config_args = {
                    "temperature": temperature
                }
                if system_instruction:
                    config_args["system_instruction"] = system_instruction
                if response_mime_type:
                    config_args["response_mime_type"] = response_mime_type

                response = client.models.generate_content(
                    model=model_name,
                    contents=contents_parts,
                    config=types.GenerateContentConfig(**config_args)
                )
                if response and response.text:
                    log_success = f"[GEMINI SUCCESS] Respuesta obtenida exitosamente con el modelo: {model_name}"
                    logger.info(log_success)
                    print(log_success, flush=True)
                    return response.text, model_name
            except Exception as e:
                err_str = str(e)
                is_transient = any(code in err_str for code in ["503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "temporarily unavailable"])
                if is_transient and attempt <= max_retries:
                    backoff_sec = attempt * 2  # 2s, then 4s
                    log_retry = f"[GEMINI RETRY] Modelo '{model_name}' devolvió error transitorio ({err_str[:120]}...). Reintentando en {backoff_sec}s (intento {attempt}/{max_retries})..."
                    logger.warning(log_retry)
                    print(log_retry, flush=True)
                    time.sleep(backoff_sec)
                    continue
                else:
                    log_err = f"[GEMINI ERROR] Falló generación con modelo '{model_name}': {err_str}"
                    logger.warning(log_err)
                    print(log_err, flush=True)
                    attempted_errors[model_name] = err_str
                    break  # move to fallback model

    err_summary = " | ".join([f"{m}: {err}" for m, err in attempted_errors.items()])
    log_critical = f"[GEMINI CRITICAL] Todos los modelos configurados {GEMINI_MODELS} fallaron. Resumen: {err_summary}"
    logger.error(log_critical)
    print(log_critical, flush=True)
    raise RuntimeError(err_summary)

def build_multimodal_video_tasks(video_id, v_title, v_thumb):
    """Create one or more source tasks for a YouTube video without captions.
    Uses adaptive frame rate (VideoMetadata fps) and temporal chunking so that
    even ultra-long videos (1h, 2h, 4h+) never exceed Gemini's 1M context limit.
    """
    duration_sec = get_youtube_duration_seconds(video_id)
    if duration_sec <= 0:
        duration_sec = 3600

    video_uri = f"https://www.youtube.com/watch?v={video_id}"
    tasks = []

    # Adaptive FPS rules:
    # Educational lectures have slides / whiteboards where 0.1 FPS (1 frame every 10s)
    # preserves all formulas and diagrams while reducing video tokens by 90% (~55 tokens/sec).
    if duration_sec <= 1200:  # <= 20 min
        fps = 0.5
        vm = types.VideoMetadata(fps=fps, start_offset="0s", end_offset=f"{duration_sec}s")
        parts = [
            types.Part(file_data=types.FileData(file_uri=video_uri), video_metadata=vm),
            types.Part.from_text(text=f"Analiza a fondo este video '{v_title}' ({duration_sec}s) para extraer y estructurar todas sus enseñanzas técnicas y fórmulas.")
        ]
        tasks.append({
            "type": "youtube_multimodal",
            "title": v_title,
            "video_id": video_id,
            "thumbnail": v_thumb,
            "duration_sec": duration_sec,
            "parts": parts,
            "estimated_tokens": int(duration_sec * 120)
        })
    elif duration_sec <= 7200:  # 20 min to 2 hours (e.g. 83m = 4983s -> ~274k tokens, 108m = 6536s -> ~359k tokens)
        fps = 0.1
        vm = types.VideoMetadata(fps=fps, start_offset="0s", end_offset=f"{duration_sec}s")
        parts = [
            types.Part(file_data=types.FileData(file_uri=video_uri), video_metadata=vm),
            types.Part.from_text(text=f"Analiza a fondo esta clase completa '{v_title}' ({duration_sec // 60} minutos) para extraer y estructurar exhaustivamente todas sus fórmulas KaTeX, conceptos y deducciones.")
        ]
        tasks.append({
            "type": "youtube_multimodal",
            "title": v_title,
            "video_id": video_id,
            "thumbnail": v_thumb,
            "duration_sec": duration_sec,
            "parts": parts,
            "estimated_tokens": int(duration_sec * 55)
        })
    else:  # > 2 hours (e.g. 3, 4, 6 hours): chunk into 3600s (1 hour) segments
        chunk_size = 3600
        fps = 0.1
        total_chunks = (duration_sec + chunk_size - 1) // chunk_size
        for i in range(total_chunks):
            start_s = i * chunk_size
            end_s = min(duration_sec, (i + 1) * chunk_size)
            chunk_title = f"{v_title} (Segmento {i+1}/{total_chunks}: min {start_s//60} a {end_s//60})"
            vm = types.VideoMetadata(fps=fps, start_offset=f"{start_s}s", end_offset=f"{end_s}s")
            parts = [
                types.Part(file_data=types.FileData(file_uri=video_uri), video_metadata=vm),
                types.Part.from_text(text=f"Analiza el segmento ({start_s//60}m a {end_s//60}m) del video '{v_title}' extrayendo todas sus explicaciones y fórmulas.")
            ]
            tasks.append({
                "type": "youtube_multimodal",
                "title": chunk_title,
                "video_id": video_id,
                "thumbnail": v_thumb,
                "duration_sec": end_s - start_s,
                "parts": parts,
                "estimated_tokens": int((end_s - start_s) * 55)
            })

    return tasks

@app.route('/api/generate-notes', methods=['POST'])
@app.route('/api/generate', methods=['POST'])
def generate_notes():
    """Main generation endpoint using direct Google Gemini AI with Map-Reduce and Adaptive Video processing."""
    api_key = extract_gemini_api_key(request)
    if not api_key:
        return jsonify({
            "success": False,
            "needs_key": True,
            "error": "Por favor configura tu clave de Gemini API para sintetizar tus apuntes. Es 100% gratuita y privada."
        }), 401

    is_json = request.is_json
    body = request.get_json(silent=True) or {} if is_json else {}
    form = request.form if not is_json else {}

    # Extract parameters
    depth = (body.get('depth') or form.get('depth') or 'standard').strip()
    style = (body.get('style') or form.get('style') or 'academic').strip()
    user_instructions = (body.get('instructions') or form.get('instructions') or '').strip()
    notes_text = (body.get('notes_text') or body.get('manual_text') or form.get('notes_text') or form.get('manual_text') or '').strip()

    # YouTube URLs
    raw_yt = body.get('youtube_urls') or body.get('youtube_url') or form.get('youtube_urls') or form.get('youtube_url')
    youtube_urls = []
    if isinstance(raw_yt, list):
        youtube_urls = [str(u).strip() for u in raw_yt if str(u).strip()]
    elif isinstance(raw_yt, str) and raw_yt.strip():
        if raw_yt.strip().startswith('['):
            try:
                parsed_list = json.loads(raw_yt)
                if isinstance(parsed_list, list):
                    youtube_urls = [str(u).strip() for u in parsed_list if str(u).strip()]
            except Exception:
                youtube_urls = [raw_yt.strip()]
        else:
            youtube_urls = [u.strip() for u in raw_yt.split(',') if u.strip()]

    # Client-side transcripts map
    raw_ct = body.get('client_transcripts') or form.get('client_transcripts')
    client_transcripts = {}
    if isinstance(raw_ct, dict):
        client_transcripts = raw_ct
    elif isinstance(raw_ct, str) and raw_ct.strip():
        try:
            client_transcripts = json.loads(raw_ct)
        except Exception:
            pass

    source_tasks = []
    sources_list = []
    saved_temp_files = []

    try:
        client = genai.Client(api_key=api_key)

        # 1. Process YouTube videos (deduplicate by video_id)
        seen_video_ids = set()
        for yt_url in youtube_urls:
            video_id = extract_youtube_id(yt_url)
            if not video_id or video_id in seen_video_ids:
                continue
            seen_video_ids.add(video_id)

            v_meta = get_youtube_metadata(video_id)
            v_title = v_meta.get("title", f"Video {video_id}")
            v_thumb = v_meta.get("thumbnail", f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg")

            transcript_text = None
            # Check client-side transcript first
            if video_id in client_transcripts and len(str(client_transcripts[video_id]).strip()) > 5:
                transcript_text = str(client_transcripts[video_id]).strip()

            # Check server-side transcript extraction if client didn't supply one
            if not transcript_text:
                t_data = get_youtube_transcript_api(video_id)
                if t_data and t_data.get("full_text"):
                    transcript_text = t_data["full_text"]

            if transcript_text:
                clean_transcript = re.sub(r'[ \t]+', ' ', transcript_text)
                clean_transcript = re.sub(r'\n{3,}', '\n\n', clean_transcript).strip()
                source_tasks.append({
                    "type": "youtube_transcript",
                    "title": v_title,
                    "video_id": video_id,
                    "thumbnail": v_thumb,
                    "parts": [
                        types.Part.from_text(
                            text=f"=== FUENTE VIDEO YOUTUBE ({video_id}): '{v_title}' ===\nTranscripción completa:\n{clean_transcript}"
                        )
                    ],
                    "estimated_tokens": len(clean_transcript) // 4
                })
                sources_list.append({
                    "type": "youtube",
                    "title": v_title,
                    "video_id": video_id,
                    "thumbnail": v_thumb,
                    "has_captions": True
                })
            else:
                # Video has NO captions or datacenter is blocked:
                # Use Gemini Native Multimodal Video understanding with adaptive FPS & chunking!
                logger.info(f"Using Gemini Native Multimodal Video understanding with adaptive FPS for {video_id}")
                video_tasks = build_multimodal_video_tasks(video_id, v_title, v_thumb)
                source_tasks.extend(video_tasks)
                sources_list.append({
                    "type": "youtube",
                    "title": v_title,
                    "video_id": video_id,
                    "thumbnail": v_thumb,
                    "has_captions": False,
                    "mode": "gemini_multimodal_video"
                })

        # 2. Process PDF uploads
        pdf_files = request.files.getlist('pdf_files') or request.files.getlist('files')
        for file in pdf_files:
            if file and file.filename:
                safe_name = secure_filename(file.filename)
                dest_path = UPLOAD_FOLDER / f"pdf_{os.urandom(4).hex()}_{safe_name}"
                file.save(dest_path)
                saved_temp_files.append(dest_path)

                pdf_text = extract_pdf_text(dest_path)
                if pdf_text and len(pdf_text.strip()) > 100:
                    source_tasks.append({
                        "type": "pdf_text",
                        "title": file.filename,
                        "parts": [
                            types.Part.from_text(text=f"=== FUENTE DOCUMENTO PDF: '{file.filename}' ===\n{pdf_text}")
                        ],
                        "estimated_tokens": len(pdf_text) // 4
                    })
                    sources_list.append({
                        "type": "pdf",
                        "filename": file.filename,
                        "pages": len(pdf_text.split("--- Página ")) - 1
                    })
                else:
                    # Upload visual/scanned PDF directly to Gemini
                    logger.info(f"Uploading visual PDF {file.filename} to Gemini File API")
                    uploaded_pdf = client.files.upload(file=str(dest_path))
                    source_tasks.append({
                        "type": "pdf_multimodal",
                        "title": file.filename,
                        "parts": [
                            uploaded_pdf,
                            types.Part.from_text(text=f"Analiza este documento PDF adjunto ('{file.filename}') exhaustivamente.")
                        ],
                        "estimated_tokens": 50000
                    })
                    sources_list.append({
                        "type": "pdf",
                        "filename": file.filename,
                        "mode": "gemini_file_upload"
                    })

        # 3. Process Audio uploads
        audio_files = request.files.getlist('audio_files')
        for afile in audio_files:
            if afile and afile.filename:
                safe_name = secure_filename(afile.filename)
                dest_path = UPLOAD_FOLDER / f"audio_{os.urandom(4).hex()}_{safe_name}"
                afile.save(dest_path)
                saved_temp_files.append(dest_path)

                logger.info(f"Uploading audio {afile.filename} to Gemini File API")
                uploaded_audio = client.files.upload(file=str(dest_path))
                source_tasks.append({
                    "type": "audio_multimodal",
                    "title": afile.filename,
                    "parts": [
                        uploaded_audio,
                        types.Part.from_text(text=f"Escucha y analiza exhaustivamente la grabación de audio ('{afile.filename}') para extraer y estructurar las enseñanzas de la clase.")
                    ],
                    "estimated_tokens": 100000
                })
                sources_list.append({
                    "type": "audio",
                    "filename": afile.filename,
                    "mode": "gemini_audio_upload"
                })

        # 4. Process manual notes
        if notes_text:
            source_tasks.append({
                "type": "notes",
                "title": "Notas personales",
                "parts": [
                    types.Part.from_text(text=f"=== APUNTES Y NOTAS PERSONALES DEL USUARIO ===\n{notes_text}")
                ],
                "estimated_tokens": len(notes_text) // 4
            })
            sources_list.append({
                "type": "notes",
                "title": "Notas personales"
            })

        if not source_tasks:
            return jsonify({
                "success": False,
                "error": "No se proporcionó ningún material. Ingresa un video de YouTube, sube un PDF, audio o escribe tus apuntes."
            }), 400

        # Safety guard for massive text inputs (> 1M tokens)
        total_text_tokens = None
        try:
            text_parts = [p for t in source_tasks for p in t["parts"] if hasattr(p, 'text') and p.text]
            if text_parts:
                cnt_resp = client.models.count_tokens(model=GeminiConfig.PRIMARY_MODEL, contents=text_parts)
                raw_tokens = getattr(cnt_resp, 'total_tokens', None)
                if isinstance(raw_tokens, (int, float)):
                    total_text_tokens = int(raw_tokens)
        except Exception:
            pass

        MAX_ALLOWED_TOKENS = 1_000_000
        if total_text_tokens is not None and total_text_tokens > MAX_ALLOWED_TOKENS:
            user_err_msg = (
                f"El contenido combinado de las fuentes es demasiado extenso "
                f"({total_text_tokens:,} tokens calculados, superando el límite de 1,048,576 tokens de Gemini). "
                "Por favor probá con menos texto o material más conciso."
            )
            return jsonify({
                "success": False,
                "error": user_err_msg,
                "total_tokens": total_text_tokens,
                "token_limit": 1048576
            }), 400

        total_estimated_tokens = sum(t.get("estimated_tokens", 5000) for t in source_tasks)
        log_pipeline = (
            f"[PIPELINE START] Fuentes/tareas independientes: {len(source_tasks)} | "
            f"Tokens estimados: {total_estimated_tokens:,} | "
            f"Estrategia: {'FAST PATH (1 llamada directa)' if (len(source_tasks) == 1 and total_estimated_tokens <= 350000) else f'MAP-REDUCE ({len(source_tasks)} maps + 1 reduce)'}"
        )
        logger.info(log_pipeline)
        print(log_pipeline, flush=True)

        result_data = None
        used_model = GeminiConfig.PRIMARY_MODEL

        # Fast Path (1 single source, moderate size)
        if len(source_tasks) == 1 and total_estimated_tokens <= 350000:
            task = source_tasks[0]
            fast_parts = list(task["parts"])
            inst_text = f"Genera los apuntes de estudio maestros para el material proporcionado.\nProfundidad: {depth}\nEstilo pedagógico: {style}\n"
            if user_instructions:
                inst_text += f"Instrucciones específicas del usuario: {user_instructions}\n"
            fast_parts.append(types.Part.from_text(text=inst_text))

            text_resp, used_model = call_gemini_with_fallback(
                client,
                fast_parts,
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.3
            )
            result_data = robust_parse_json(text_resp)

        else:
            # Map-Reduce Path: Process each source in isolation, then consolidate
            source_summaries = []
            for idx, task in enumerate(source_tasks):
                log_map = f"[MAP PHASE] ({idx+1}/{len(source_tasks)}) Analizando fuente: '{task['title']}' (tokens est: ~{task.get('estimated_tokens', 0):,})..."
                logger.info(log_map)
                print(log_map, flush=True)

                map_parts = list(task["parts"])
                map_parts.append(types.Part.from_text(
                    text=(
                        f"Analiza a fondo esta fuente de estudio ('{task['title']}'). "
                        "Produce un extracto técnico y pedagógico exhaustivo y denso. "
                        "Extrae todas las definiciones, fórmulas matemáticas en notación KaTeX ($inline$ y $$bloque$$), "
                        "demostraciones, procedimientos paso a paso y criterios prácticos."
                    )
                ))

                summary_text, last_model = call_gemini_with_fallback(
                    client,
                    map_parts,
                    system_instruction=MAP_SOURCE_SYSTEM_PROMPT,
                    response_mime_type=None,
                    temperature=0.3
                )
                used_model = last_model
                source_summaries.append(f"=== SÍNTESIS TÉCNICA DE FUENTE ({idx+1}/{len(source_tasks)}): '{task['title']}' ===\n{summary_text}")

            # Reduce Phase
            log_reduce = f"[REDUCE PHASE] Consolidando {len(source_summaries)} síntesis independientes en el apunte maestro definitivo..."
            logger.info(log_reduce)
            print(log_reduce, flush=True)

            combined_summaries = "\n\n".join(source_summaries)
            reduce_prompt = (
                f"A continuación tienes las síntesis técnicas y pedagógicas detalladas extraídas de {len(source_summaries)} fuentes independientes de estudio:\n\n"
                f"{combined_summaries}\n\n"
                f"Tu misión es integrar y estructurar TODO este conocimiento en el APUNTE MAESTRO DEFINITIVO.\n"
                f"Profundidad solicitada: {depth}\n"
                f"Estilo pedagógico: {style}\n"
            )
            if user_instructions:
                reduce_prompt += f"Instrucciones específicas del usuario: {user_instructions}\n"
            reduce_prompt += (
                "\nGenera el objeto JSON completo según las especificaciones del sistema, con KaTeX, diagramas Mermaid, "
                "flashcards, quiz, consejos de examen y glosario técnico."
            )

            text_resp, used_model = call_gemini_with_fallback(
                client,
                [types.Part.from_text(text=reduce_prompt)],
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.3
            )
            result_data = robust_parse_json(text_resp)

        result_data["_used_model"] = used_model

        # Merge sources
        if not result_data.get("sources"):
            result_data["sources"] = sources_list
        else:
            for s in sources_list:
                if not any(x.get("video_id") == s.get("video_id") and s.get("video_id") for x in result_data["sources"]):
                    result_data["sources"].append(s)

        return jsonify({"success": True, "data": result_data})

    except Exception as e:
        logger.error(f"Error general en generate_notes: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": f"Error al procesar la solicitud: {str(e)}"
        }), 500

    finally:
        # Cleanup temporary uploaded files
        for tmp_path in saved_temp_files:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"Iniciando ApuntesIA en http://localhost:{port} ...")
    app.run(host='0.0.0.0', port=port, debug=True)
