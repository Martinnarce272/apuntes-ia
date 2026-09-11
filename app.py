import sys
import os
import re
import json
import logging
import tempfile
import base64
import http.cookiejar
import requests
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, stream_with_context

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("ApuntesIA")

# Ensure UTF-8 output encoding on Windows console
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

app = Flask(__name__)

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

def get_youtube_transcript_api(video_id):
    """Retrieve subtitles directly via youtube-transcript-api without downloading media."""
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
    """Retrieve video metadata, subtitle tracks, and audio streaming info via yt-dlp with cookie & player fallback."""
    cookie_file = get_youtube_cookiefile()
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'mweb', 'web'],
                'player_skip': ['webpage', 'configs']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
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
            
            # Prioritize Spanish, then English
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
            
            # If no matches above, add whatever subtitles exist
            if not caption_tracks:
                for lang_code, track_list in list(subs.items())[:3] + list(auto_subs.items())[:3]:
                    pref = next((s['url'] for s in track_list if s.get('ext') in ['srv1', 'srv3']), track_list[0]['url'])
                    caption_tracks.append({
                        "name": f"Subtítulos ({lang_code})",
                        "language_code": lang_code,
                        "base_url": pref,
                        "is_auto": lang_code in auto_subs and lang_code not in subs
                    })

            # Check youtube-transcript-api as backup for caption_tracks if empty
            if not caption_tracks:
                t_data = get_youtube_transcript_api(video_id)
                if t_data and t_data.get("full_text"):
                    caption_tracks.append({
                        "name": f"Transcripción Directa ({t_data.get('language', 'es')})",
                        "language_code": t_data.get('language', 'es'),
                        "base_url": f"/api/youtube-transcript?videoId={video_id}",
                        "is_auto": False,
                        "is_api": True
                    })
            
            # Extract lightweight audio format for Speech-to-Text
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
                "caption_tracks": caption_tracks,
                "has_captions": len(caption_tracks) > 0,
                "has_audio": selected_audio is not None,
                "audio_url": selected_audio.get('url') if selected_audio else None,
                "audio_headers": selected_audio.get('http_headers', {}) if selected_audio else {},
                "audio_format_id": selected_audio.get('format_id') if selected_audio else None,
                "audio_ext": selected_audio.get('ext', 'm4a') if selected_audio else 'm4a'
            }, {"status": "ok"}
    except Exception as e:
        logger.warning(f"yt-dlp extract failed for {video_id}: {e}")
        # Even if yt-dlp failed, attempt direct subtitles via youtube-transcript-api!
        t_data = get_youtube_transcript_api(video_id)
        if t_data and t_data.get("full_text"):
            meta = get_youtube_metadata(video_id)
            return {
                "title": meta.get("title", f"Video {video_id}"),
                "author": meta.get("author", "YouTube"),
                "thumbnail": meta.get("thumbnail", f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"),
                "fallback_thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
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
        return None, {"error": str(e)}

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
    return jsonify({
        "status": "ready",
        "engine": "Puter.js (Client-Side AI & Transcripts)",
        "version": "1.3.0",
        "message": "Servicio activo. La IA corre en el navegador mediante Puter.js y las transcripciones se descargan desde el cliente."
    })

@app.route('/api/youtube-preview', methods=['POST'])
def youtube_preview():
    data = request.get_json(silent=True) or request.form or {}
    url = data.get('url', '')
    video_id = extract_youtube_id(url)
    if not video_id:
        return jsonify({"success": False, "error": "Enlace de YouTube no válido"}), 400
        
    vdata, debug_info = get_youtube_video_data(video_id)
    if vdata:
        vdata["video_id"] = video_id
        vdata["success"] = True
        vdata["debug"] = debug_info
        return jsonify(vdata)

    # Fallback to oEmbed + youtube-transcript-api check
    meta = get_youtube_metadata(video_id)
    t_data = get_youtube_transcript_api(video_id)
    has_captions = t_data is not None and bool(t_data.get("full_text"))
    caption_tracks = []
    if has_captions:
        caption_tracks.append({
            "name": f"Transcripción Directa ({t_data.get('language', 'es')})",
            "language_code": t_data.get('language', 'es'),
            "base_url": f"/api/youtube-transcript?videoId={video_id}",
            "is_auto": False,
            "is_api": True
        })

    meta["video_id"] = video_id
    meta["success"] = True
    meta["caption_tracks"] = caption_tracks
    meta["has_captions"] = has_captions
    meta["has_audio"] = False
    meta["debug"] = debug_info
    return jsonify(meta)

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
    if vdata:
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

    meta = get_youtube_metadata(video_id)
    t_data = get_youtube_transcript_api(video_id)
    has_captions = t_data is not None and bool(t_data.get("full_text"))
    caption_tracks = []
    if has_captions:
        caption_tracks.append({
            "name": f"Transcripción Directa ({t_data.get('language', 'es')})",
            "language_code": t_data.get('language', 'es'),
            "base_url": f"/api/youtube-transcript?videoId={video_id}",
            "is_auto": False,
            "is_api": True
        })

    return jsonify({
        "success": True,
        "video_id": video_id,
        "title": meta.get("title", f"Video {video_id}"),
        "thumbnail": meta.get("thumbnail", ""),
        "has_captions": has_captions,
        "has_audio": False,
        "caption_tracks": caption_tracks,
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"Iniciando ApuntesIA en http://localhost:{port} ...")
    app.run(host='0.0.0.0', port=port, debug=True)
