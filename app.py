import sys
import os
import re
import json
import requests
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Ensure UTF-8 output encoding on Windows console to avoid charmap UnicodeEncodeErrors
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Load local .env if present
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload
UPLOAD_FOLDER = Path(__file__).parent / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)

def robust_parse_json(text):
    """Robustly parse JSON strings from Gemini, handling unescaped LaTeX backslashes."""
    if not text:
        raise ValueError("Respuesta vacía de la IA.")
        
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        text = text[start:end+1]

    # Try standard strict=False first
    try:
        return json.loads(text, strict=False)
    except Exception:
        pass

    # Regex repair for unescaped LaTeX macros (\frac, \Delta, \sigma, etc.)
    def fix_escapes(match):
        following = match.group(1)
        if following in ['"', '\\', '/']:
            return match.group(0)
        if following in ['n', 't', 'r', 'b']:
            after = match.group(2)
            if after and after.isalpha():
                return r'\\' + following + after
            return match.group(0)
        return r'\\' + match.group(0)[1:]

    fixed = re.sub(r'\\(.)([a-zA-Z]?)', fix_escapes, text)
    try:
        return json.loads(fixed, strict=False)
    except Exception:
        pass

    # Fallback: escape all backslashes that are not followed by " or \
    fixed2 = re.sub(r'\\(?![/"\\])', r'\\\\', text)
    return json.loads(fixed2, strict=False)

class GeminiConfig:
    """Configuración centralizada de modelos Gemini y orden de intento según cuota disponible.
    1. Principal: gemini-3.8-flash (con margen de cuota disponible)
    2. Fallback: gemini-3.5-flash-lite (500 RPD diarios, máxima disponibilidad)
    3. Último recurso: gemini-3.7-flash y gemini-3.6-flash (solo si los anteriores fallan por motivos distintos a cuota)
    """
    PRIMARY_MODEL = "gemini-3.8-flash"
    FALLBACK_MODEL = "gemini-3.5-flash-lite"
    LAST_RESORT_MODELS = ["gemini-3.7-flash", "gemini-3.6-flash"]
    ACTIVE_MODELS = [PRIMARY_MODEL, FALLBACK_MODEL]
    MODELS = ACTIVE_MODELS + LAST_RESORT_MODELS

    @classmethod
    def get_primary_chain(cls):
        return list(cls.ACTIVE_MODELS)

    @classmethod
    def get_last_resort_chain(cls):
        return list(cls.LAST_RESORT_MODELS)

class GeminiQuotaExceeded(Exception):
    """Excepción específica cuando se agota la cuota gratuita (429 / RESOURCE_EXHAUSTED)."""
    pass

def is_quota_error(exc):
    """Detecta si un error corresponde a límite de cuota (HTTP 429 o RESOURCE_EXHAUSTED)."""
    if not exc:
        return False
    msg = str(exc).lower()
    code = getattr(exc, 'code', None)
    status_code = getattr(exc, 'status_code', None)
    if code == 429 or status_code == 429:
        return True
    keywords = ["429", "resource_exhausted", "quota", "ratelimit", "rate limit", "exceeded your current quota"]
    return any(k in msg for k in keywords)


def is_model_not_found_error(exc):
    """Detecta si un error corresponde a modelo no encontrado o deprecado (HTTP 404 o NOT_FOUND)."""
    if not exc:
        return False
    msg = str(exc).lower()
    code = getattr(exc, 'code', None)
    status_code = getattr(exc, 'status_code', None)
    if code == 404 or status_code == 404:
        return True
    keywords = ["404", "not_found", "not found", "is not supported for this api version", "deprecated", "does not exist"]
    return any(k in msg for k in keywords)


def is_token_limit_error(exc):
    """Detecta si un error corresponde a límite de tokens o contexto excedido (HTTP 400/413)."""
    if not exc:
        return False
    msg = str(exc).lower()
    code = getattr(exc, 'code', None)
    status_code = getattr(exc, 'status_code', None)
    token_keywords = [
        "token", "context length", "maximum context", "payload too large",
        "too many tokens", "exceeds the limit", "request payload",
        "input length", "max tokens", "too large"
    ]
    has_token_indication = any(k in msg for k in token_keywords)
    is_bad_req = code in (400, 413) or status_code in (400, 413) or "400" in msg or "413" in msg or "invalid_argument" in msg
    return has_token_indication and (is_bad_req or "exceed" in msg or "limit" in msg)


def handle_gemini_error(exc):
    """Centraliza la clasificación y respuesta HTTP para errores de Google Gemini:
    - 429: Cuota gratuita agotada (RESOURCE_EXHAUSTED / RATE_LIMIT).
    - 404: Modelo no encontrado o deprecado por Google.
    - 400: Límite de tokens o longitud de contexto excedido.
    - 500: Error interno o inesperado de la API.
    """
    if isinstance(exc, GeminiQuotaExceeded) or is_quota_error(exc):
        return jsonify({
            "success": False,
            "error": "Se alcanzó el límite de uso gratuito de Gemini por ahora. Esperá unos minutos y probá de nuevo, o probá con menos videos a la vez."
        }), 429

    if is_model_not_found_error(exc):
        return jsonify({
            "success": False,
            "error": "El modelo de IA solicitado no está disponible o ha sido discontinuado por Google Gemini. Por favor verifica la configuración de modelos."
        }), 404

    if is_token_limit_error(exc):
        return jsonify({
            "success": False,
            "error": "El contenido ingresado supera el límite máximo de tokens o contexto permitido por la IA. Intenta con videos más cortos o con menos documentos simultáneos."
        }), 400

    safe_msg = str(exc)
    try:
        print(f"Error calling Gemini API: {safe_msg}")
    except Exception:
        pass
    return jsonify({
        "success": False,
        "error": f"Error al generar el apunte con Gemini: {safe_msg}"
    }), 500

def call_gemini_with_fallback(client, contents, system_instruction=None, response_mime_type=None, models=None, thinking_budget=0):
    """
    Ejecuta llamadas a Gemini siguiendo la jerarquía configurada en GeminiConfig:
    1. "gemini-3.8-flash" como modelo principal.
    2. "gemini-3.5-flash-lite" como fallback (500 RPD).
    3. "gemini-3.7-flash" y "gemini-3.6-flash" como último recurso, solo si los anteriores fallan por razones distintas a 429.

    Si un modelo devuelve 429 (cuota agotada), pasa automáticamente al siguiente modelo sin reintentos innecesarios.
    thinking_budget=0 desactiva la fase de razonamiento previo de Gemini, acelerando la respuesta entre un 50% y 75%.
    """
    from google.genai import types
    import time

    if models is not None:
        primary_chain = models
        last_resort_chain = []
    else:
        primary_chain = GeminiConfig.ACTIVE_MODELS
        last_resort_chain = GeminiConfig.LAST_RESORT_MODELS

    config = types.GenerateContentConfig(
        temperature=0.3
    )
    if system_instruction:
        config.system_instruction = system_instruction
    if response_mime_type:
        config.response_mime_type = response_mime_type
    if thinking_budget is not None:
        try:
            config.thinking_config = types.ThinkingConfig(thinking_budget=thinking_budget)
        except Exception:
            pass

    last_error = None
    all_quota_exhausted = True

    # 1. Intentar la cadena activa (gemini-3.8-flash -> gemini-3.5-flash-lite)
    for model_name in primary_chain:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config
            )
            if response and response.text:
                print(f"[Gemini] Respondio exitosamente el modelo: {model_name}")
                return response.text.strip(), model_name
        except Exception as merr:
            last_error = merr
            err_str = str(merr)
            print(f"[Gemini] Modelo {model_name} falló: {err_str[:140]}")

            # Si el modelo falló por incompatibilidad con thinking_config, reintentar de inmediato sin él
            if "thinking" in err_str.lower() and getattr(config, 'thinking_config', None) is not None:
                try:
                    cfg_no_thinking = config.model_copy(update={'thinking_config': None})
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=cfg_no_thinking
                    )
                    if response and response.text:
                        print(f"[Gemini] Respondio exitosamente (sin thinking_config) el modelo: {model_name}")
                        return response.text.strip(), model_name
                except Exception as nerr:
                    last_error = nerr
                    err_str = str(nerr)

            if is_quota_error(merr):
                # 429: No reintentar el mismo modelo. Pasar inmediatamente al siguiente modelo de la lista
                print(f"[Gemini] Cuota agotada (429) en {model_name}. Pasando inmediatamente al siguiente modelo...")
                continue
            elif is_model_not_found_error(merr):
                # 404: Modelo no disponible o deprecado. Pasar inmediatamente al siguiente modelo
                all_quota_exhausted = False
                print(f"[Gemini] Modelo {model_name} no disponible (404/deprecado). Pasando al siguiente modelo...")
                continue
            else:
                # El fallo NO fue por cuota (ej. sobrecarga temporal 503)
                all_quota_exhausted = False
                if "503" in err_str or "high demand" in err_str or "unavailable" in err_str.lower():
                    try:
                        time.sleep(2)
                        response = client.models.generate_content(
                            model=model_name,
                            contents=contents,
                            config=config
                        )
                        if response and response.text:
                            print(f"[Gemini] Respondio exitosamente en reintento el modelo: {model_name}")
                            return response.text.strip(), model_name
                    except Exception as retry_err:
                        last_error = retry_err
                        print(f"[Gemini] Reintento en {model_name} falló: {str(retry_err)[:140]}")
                        if is_quota_error(retry_err):
                            continue

    # Si ambos modelos activos (3.8-flash y 3.5-flash-lite) fallaron por CUOTA AGOTADA (429):
    # No quemar gemini-3.7-flash ni gemini-3.6-flash, ya que su cuota diaria ya está agotada.
    if all_quota_exhausted:
        raise GeminiQuotaExceeded(
            "Se alcanzó el límite de uso gratuito de Gemini por ahora. "
            "Esperá unos minutos y probá de nuevo, o probá con menos videos a la vez."
        )

    # 2. Si fallaron por un motivo distinto a cuota agotada, probar último recurso (3.7 y 3.6)
    for model_name in last_resort_chain:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config
            )
            if response and response.text:
                print(f"[Gemini] Respondio exitosamente (último recurso) el modelo: {model_name}")
                return response.text.strip(), model_name
        except Exception as merr:
            last_error = merr
            err_str = str(merr)
            print(f"[Gemini] Último recurso {model_name} falló: {err_str[:140]}")

            if "thinking" in err_str.lower() and getattr(config, 'thinking_config', None) is not None:
                try:
                    cfg_no_thinking = config.model_copy(update={'thinking_config': None})
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=cfg_no_thinking
                    )
                    if response and response.text:
                        print(f"[Gemini] Respondio exitosamente (último recurso, sin thinking_config) el modelo: {model_name}")
                        return response.text.strip(), model_name
                except Exception as nerr:
                    last_error = nerr

            if is_quota_error(merr) or is_model_not_found_error(merr):
                continue

    if is_quota_error(last_error):
        raise GeminiQuotaExceeded(
            "Se alcanzó el límite de uso gratuito de Gemini por ahora. "
            "Esperá unos minutos y probá de nuevo, o probá con menos videos a la vez."
        )

    raise last_error or Exception("No se obtuvo respuesta de ninguno de los modelos de Gemini.")


def get_api_key(request_data=None):
    """Retrieve Gemini API key from request, environment, or .env file."""
    if request_data and request_data.get('apiKey'):
        return request_data.get('apiKey').strip()
    
    header_key = request.headers.get('X-Gemini-Api-Key')
    if header_key:
        return header_key.strip()
        
    env_key = os.environ.get('GEMINI_API_KEY')
    if env_key:
        return env_key.strip()
        
    return None

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

def get_youtube_duration_seconds(video_id):
    """Retrieve video duration in seconds using official YouTube player endpoint or fallback."""
    try:
        url = "https://www.youtube.com/youtubei/v1/player?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
        payload = {
            "context": {"client": {"clientName": "ANDROID", "clientVersion": "20.10.38", "androidSdkVersion": 34, "hl": "es"}},
            "videoId": video_id
        }
        headers = {"User-Agent": "com.google.android.youtube/20.10.38 (Linux; U; Android 14)", "Content-Type": "application/json"}
        resp = requests.post(url, json=payload, headers=headers, timeout=5)
        if resp.status_code == 200:
            sec = resp.json().get("videoDetails", {}).get("lengthSeconds")
            if sec and int(sec) > 0:
                return int(sec)
    except Exception:
        pass
    return 3600

def get_youtube_transcript(video_id):
    """Extract transcript with timestamps from YouTube supporting modern and legacy APIs."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        raw_data = None

        # 1. Try modern v1.x API (instance based)
        try:
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)
            target_transcript = None
            
            # Look for Spanish or preferred languages
            try:
                target_transcript = transcript_list.find_transcript(['es', 'es-419', 'es-ES', 'es-AR'])
            except Exception:
                pass
                
            # If not found directly, look for any transcript and translate to Spanish if translatable
            if not target_transcript:
                for t in transcript_list:
                    target_transcript = t
                    if hasattr(t, 'is_translatable') and t.is_translatable and t.language_code not in ['es', 'es-419', 'es-ES']:
                        try:
                            target_transcript = t.translate('es')
                        except Exception:
                            pass
                    break
                    
            if target_transcript:
                fetched = target_transcript.fetch()
                if hasattr(fetched, 'to_raw_data'):
                    raw_data = fetched.to_raw_data()
                else:
                    raw_data = fetched
            else:
                fetched = api.fetch(video_id, languages=['es', 'es-419', 'es-ES', 'en'])
                if hasattr(fetched, 'to_raw_data'):
                    raw_data = fetched.to_raw_data()
                else:
                    raw_data = fetched
        except Exception as e1:
            # 2. Try legacy v0.x API (class-based)
            try:
                if hasattr(YouTubeTranscriptApi, 'list_transcripts'):
                    tl = YouTubeTranscriptApi.list_transcripts(video_id)
                    t = None
                    try:
                        t = tl.find_transcript(['es', 'es-419', 'es-ES', 'en'])
                    except Exception:
                        for item in tl:
                            t = item
                            break
                    if t:
                        raw_data = t.fetch()
                if not raw_data and hasattr(YouTubeTranscriptApi, 'get_transcript'):
                    raw_data = YouTubeTranscriptApi.get_transcript(video_id, languages=['es', 'es-419', 'es-ES', 'en'])
            except Exception:
                raise e1

        if not raw_data:
            return {
                "success": False,
                "error": "No se encontraron subtítulos ni transcripción disponible para este video en YouTube. Asegúrate de que el video tenga subtítulos activados (CC)."
            }

        full_text_pieces = []
        timed_snippets = []
        
        for item in raw_data:
            text = (item.get('text') if isinstance(item, dict) else getattr(item, 'text', '')).strip()
            start = int(item.get('start') if isinstance(item, dict) else getattr(item, 'start', 0))
            minutes = start // 60
            seconds = start % 60
            timestamp = f"{minutes:02d}:{seconds:02d}"
            
            if text:
                full_text_pieces.append(text)
                timed_snippets.append(f"[{timestamp}] {text}")
                
        if not full_text_pieces:
            return {
                "success": False,
                "error": "La transcripción del video está vacía."
            }

        last_start = raw_data[-1].get('start', 0) if isinstance(raw_data[-1], dict) else getattr(raw_data[-1], 'start', 0)
        return {
            "success": True,
            "full_text": " ".join(full_text_pieces),
            "timed_text": "\n".join(timed_snippets),
            "duration_seconds": int(last_start)
        }
    except Exception as e:
        error_msg = str(e)
        if "TranscriptsDisabled" in error_msg or "Subtitles are disabled" in error_msg:
            return {
                "success": False,
                "error": "El autor de este video tiene desactivados los subtítulos en YouTube. Si tienes diapositivas o apuntes de la clase en PDF, súbelos aquí y la IA generará el apunte completo."
            }
        if "NoTranscriptFound" in error_msg:
            return {
                "success": False,
                "error": "No se encontró una transcripción en español o inglés para este video. Asegúrate de que el video cuente con subtítulos o transcripción automática generada por YouTube."
            }
        return {
            "success": False,
            "error": f"No se pudo extraer la transcripción del video ({error_msg}). Asegúrate de que el video tenga subtítulos o transcripción activada en YouTube."
        }

def extract_pdf_text(filepath):
    """Extract text and metadata from PDF using pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(filepath)
        total_pages = len(reader.pages)
        pages_content = []
        full_text = []
        
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            page_text = page_text.strip()
            if page_text:
                pages_content.append(f"--- PÁGINA {i+1} ---\n{page_text}")
                full_text.append(page_text)
                
        return {
            "success": True,
            "pages": total_pages,
            "content": "\n\n".join(pages_content),
            "raw_text": "\n".join(full_text)
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error al procesar el archivo PDF: {str(e)}"
        }

SYSTEM_INSTRUCTION = """
Eres un pedagogo experto y creador de apuntes de estudio universitarios de máxima calidad técnica y didáctica.
Tu misión es transformar el material fuente proporcionado (video de YouTube, documento PDF o ambos) en un **Apunte de Estudio Maestro** claro, profundo, estructurado y enfocado directamente en el contenido.

REQUISITOS FUNDAMENTALES:
1. Concéntrate EXCLUSIVAMENTE en generar el APUNTE y sus desarrollos temáticos. NO generes flashcards, quizzes, preguntas de prueba ni glosarios secundarios. Todo el esfuerzo y tokens deben estar en las explicaciones, demostraciones y fórmulas del apunte.
2. FÓRMULAS Y RECORTES VISUALES DEL VIDEO:
   - Si el material proviene de videos de YouTube, identifica las fórmulas matemáticas, físicas o químicas, deducciones y esquemas que el docente explica o muestra en la pizarra o pantalla.
   - Transcribe con exactitud las fórmulas utilizadas en el video usando formato LaTeX ($...$ para fórmulas en línea o $$...$$ para bloques de ecuaciones).
   - Para cada fórmula o concepto visual clave del video, asigna la marca de tiempo exacta del video (en segundos 'timestamp_seconds' y formateada 'timestamp_display' ej. "04:15") y una descripción breve de lo que se observa en la pizarra/pantalla ('description'), para que el estudiante pueda ver el recorte / momento visual exacto del video.

Debes responder ÚNICAMENTE con un objeto JSON válido (sin bloques de código markdown fuera del JSON, solo el JSON puro) con la siguiente estructura:

{
  "title": "Título Claro y Profesional del Tema Principal",
  "topic_overview": "Breve sinopsis (2-3 oraciones) de lo que abarca este apunte",
  "estimated_study_time": "ej. 20 min",
  "key_takeaways": [
    {
      "type": "critical" | "rule" | "warning" | "tip",
      "title": "Título de la idea clave o regla de oro",
      "description": "Explicación concisa y contundente del concepto clave que no puede olvidarse."
    }
  ],
  "general_diagram": {
    "title": "Mapa Conceptual o Flujo Global del Tema",
    "mermaid_code": "Código Mermaid.js completo y sintácticamente válido (ej: graph TD\\n    A[Concepto Central] --> B[Rama 1]\\n    ...)"
  },
  "developments": [
    {
      "unit_number": 1,
      "title": "Título de la Sección / Unidad Temática",
      "timestamp_display": "ej. 03:20",
      "timestamp_seconds": 200,
      "content_markdown": "Desarrollo profundo y exhaustivo de esta sección. Explica el qué, el porqué y el cómo paso a paso con rigor pedagógico. Usa subtítulos (###), listas ordenadas y ejemplos.",
      "formulas": [
        {
          "latex": "$$f(x) = \\int_a^b g(t) dt$$",
          "explanation": "Significado de la ecuación y variables",
          "timestamp_display": "03:45",
          "timestamp_seconds": 225
        }
      ],
      "video_snapshot": {
        "has_visual": true,
        "timestamp_display": "03:20",
        "timestamp_seconds": 200,
        "description": "Fórmula y gráfico dibujado en la pizarra durante la explicación"
      },
      "mermaid_diagram": "Código Mermaid.js si esta sección se beneficia de un diagrama conceptual de flujo o estructura. Si no aplica, dejar string vacío \"\"."
    }
  ]
}

REGLAS DE ORO:
1. El contenido de 'developments' debe ser profundo, pedagógico y riguroso. Desarrolla los temas paso a paso.
2. Si hay fórmulas matemáticas, físicas o químicas, exprésalas siempre en LaTeX ($...$ o $$...$$) y vinculalas al momento del video en que aparecen.
3. Asegúrate de que los diagramas Mermaid tengan sintaxis perfectamente válida.
4. NO generes flashcards ni quizzes.
5. Devuelve EXCLUSIVAMENTE el JSON.
"""

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status', methods=['GET'])
def check_status():
    api_key = get_api_key()
    return jsonify({
        "status": "ready",
        "has_api_key": bool(api_key),
        "key_preview": f"{api_key[:6]}...{api_key[-4:]}" if api_key and len(api_key) > 10 else None
    })

@app.route('/api/save-key', methods=['POST'])
def save_key():
    data = request.get_json() or {}
    key = data.get('apiKey', '').strip()
    if not key:
        return jsonify({"success": False, "error": "La clave no puede estar vacía"}), 400
        
    try:
        # Save to .env
        env_lines = []
        if env_path.exists():
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.startswith("GEMINI_API_KEY="):
                        env_lines.append(line)
        env_lines.append(f"GEMINI_API_KEY={key}\n")
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(env_lines)
            
        os.environ['GEMINI_API_KEY'] = key
        return jsonify({"success": True, "message": "Clave guardada exitosamente"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/youtube-preview', methods=['POST'])
def youtube_preview():
    data = request.get_json() or {}
    url = data.get('url', '')
    video_id = extract_youtube_id(url)
    if not video_id:
        return jsonify({"success": False, "error": "Enlace de YouTube no válido"}), 400
        
    meta = get_youtube_metadata(video_id)
    meta["video_id"] = video_id
    meta["success"] = True
    return jsonify(meta)

@app.route('/api/generate-notes', methods=['POST'])
def generate_notes():
    api_key = get_api_key(request.form)
    if not api_key:
        return jsonify({
            "success": False, 
            "error": "Se requiere una clave de API de Gemini (GEMINI_API_KEY). Puedes ingresarla en el menú de configuración de la app o guardarla en el archivo .env."
        }), 400

    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
    except Exception as ie:
        return jsonify({"success": False, "error": f"Error al inicializar cliente de Gemini: {str(ie)}"}), 500

    youtube_url = request.form.get('youtubeUrl', '').strip()
    custom_instructions = request.form.get('instructions', '').strip()
    depth_level = request.form.get('depth', 'completo')  # 'conciso', 'completo', 'exhaustivo'
    
    collected_sources = []
    source_texts = []
    video_metadata = None

    # 1. Process YouTube videos if provided (supports multiple URLs)
    raw_urls = request.form.getlist('youtubeUrls')
    single_url = request.form.get('youtubeUrl', '').strip()
    if single_url and single_url not in raw_urls:
        raw_urls.append(single_url)

    cleaned_urls = []
    for u in raw_urls:
        u = u.strip()
        if u and u not in cleaned_urls:
            cleaned_urls.append(u)

    try:
        # Pre-extracción concurrente de metadatos y transcripciones para acelerar múltiples URLs
        video_items = []
        if cleaned_urls:
            import concurrent.futures

            def _fetch_yt_info(entry):
                idx, url = entry
                vid = extract_youtube_id(url)
                if not vid:
                    return {"idx": idx, "url": url, "error": f"El enlace '{url}' no es un video de YouTube válido."}
                meta = get_youtube_metadata(vid)
                trans = get_youtube_transcript(vid)
                dur = None
                if not trans.get("success"):
                    dur = get_youtube_duration_seconds(vid)
                return {
                    "idx": idx,
                    "url": url,
                    "video_id": vid,
                    "meta": meta,
                    "transcript": trans,
                    "duration_sec": dur
                }

            if len(cleaned_urls) == 1:
                video_items = [_fetch_yt_info((0, cleaned_urls[0]))]
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(cleaned_urls), 4)) as executor:
                    video_items = list(executor.map(_fetch_yt_info, enumerate(cleaned_urls)))

            for item in video_items:
                if "error" in item:
                    return jsonify({"success": False, "error": item["error"]}), 400

            video_items = sorted(video_items, key=lambda x: x["idx"])

        # Procesamiento secuencial: cada video sin subtítulos se analiza en su propia llamada individual
        for item in video_items:
            idx = item["idx"]
            video_id = item["video_id"]
            v_meta = item["meta"]
            transcript_res = item["transcript"]

            if transcript_res.get("success"):
                collected_sources.append({
                    "type": "youtube",
                    "title": v_meta["title"],
                    "id": video_id,
                    "thumbnail": v_meta["thumbnail"],
                    "has_captions": True,
                    "order": idx + 1
                })
                source_texts.append(
                    f"=== FUENTE VIDEO DE YOUTUBE #{idx+1}: '{v_meta['title']}' ===\n"
                    f"Transcripción con marcas de tiempo:\n{transcript_res['timed_text']}"
                )
            else:
                # Video sin subtítulos: procesamiento audiovisual multimodal individual
                # FPS optimizado: 0.2 fps para videos <= 5 min, 0.1 fps para 5-25 min, 0.05 fps para > 25 min
                duration_sec = item["duration_sec"] or 600
                if duration_sec <= 300:
                    fps = 0.2
                elif duration_sec <= 1500:
                    fps = 0.1
                else:
                    fps = 0.05

                video_part = types.Part(
                    file_data=types.FileData(file_uri=f"https://www.youtube.com/watch?v={video_id}"),
                    video_metadata=types.VideoMetadata(fps=fps)
                )

                extract_prompt = f"""Analiza exhaustivamente este video de YouTube ('{v_meta['title']}').
Extrae con máximo rigor pedagógico todo su contenido académico y formativo:
1. Temas, conceptos teóricos y explicaciones brindadas por el docente u orador.
2. Fórmulas matemáticas, ecuaciones, expresiones o cálculos en pantalla o pizarra (escríbelas siempre en formato LaTeX $...$ o $$...$$).
3. Diapositivas, diagramas, esquemas o gráficos visuales explicados.
4. Ejemplos resueltos, demostraciones paso a paso y conclusiones clave.

Escribe un desarrollo analítico muy detallado, exhaustivo y estructurado cronológicamente con todo el contenido del video."""

                print(f"[Proceso Secuencial] Analizando video #{idx+1} ('{v_meta['title']}') individualmente con Gemini (FPS={fps})...")
                video_summary, video_model = call_gemini_with_fallback(
                    client=client,
                    contents=[video_part, extract_prompt]
                )

                # Liberar memoria del video inmediatamente
                del video_part
                import gc
                gc.collect()

                collected_sources.append({
                    "type": "youtube",
                    "title": v_meta["title"],
                    "id": video_id,
                    "thumbnail": v_meta["thumbnail"],
                    "has_captions": False,
                    "mode": "multimodal_vision",
                    "model_used": video_model,
                    "order": idx + 1
                })
                source_texts.append(
                    f"=== FUENTE VIDEO DE YOUTUBE #{idx+1} (ANÁLISIS MULTIMODAL - MODELO {video_model}): '{v_meta['title']}' (ID: {video_id}) ===\n"
                    f"{video_summary}"
                )

                # Pausa breve entre videos consecutivos para respetar los límites de tasa (RPM)
                if idx < len(video_items) - 1:
                    import time
                    time.sleep(1)

        # 2. Process uploaded PDF files if provided
        uploaded_files = request.files.getlist('pdfFiles')
        for file in uploaded_files:
            if file and file.filename and file.filename.lower().endswith('.pdf'):
                safe_name = secure_filename(file.filename)
                save_path = UPLOAD_FOLDER / safe_name
                file.save(save_path)
                
                pdf_res = extract_pdf_text(str(save_path))
                try:
                    if save_path.exists():
                        save_path.unlink()
                except Exception:
                    pass

                if pdf_res["success"]:
                    collected_sources.append({
                        "type": "pdf",
                        "filename": safe_name,
                        "pages": pdf_res["pages"]
                    })
                    source_texts.append(
                        f"=== FUENTE DOCUMENTO PDF '{safe_name}' ({pdf_res['pages']} páginas) ===\n"
                        f"{pdf_res['content']}"
                    )
                else:
                    return jsonify({"success": False, "error": pdf_res["error"]}), 400

        if not source_texts:
            return jsonify({"success": False, "error": "Debes proporcionar al menos un enlace de YouTube o un archivo PDF."}), 400

        # Assemble User Prompt for Final Synthesis (Lightweight Text-Only Call)
        depth_instructions = {
            "conciso": "Nivel de profundidad: RESUMEN CONCISO. Enfócate en las ideas centrales, esquemas y conceptos primordiales.",
            "completo": "Nivel de profundidad: APUNTE COMPLETO UNIVERSITARIO. Desarrolla todos los temas con rigor, explicaciones paso a paso, ejemplos y fundamentos.",
            "exhaustivo": "Nivel de profundidad: GUÍA EXHAUSTIVA DE ESTUDIO. Máximo nivel de detalle pedagógico, desglosando cada subtema, fórmula, demostración y casos prácticos."
        }.get(depth_level, "Nivel de profundidad: APUNTE COMPLETO UNIVERSITARIO.")

        multi_source_hint = f"\nNOTA PEDAGÓGICA: Has recibido {len(collected_sources)} fuentes distintas (pueden ser partes consecutivas de una clase o serie, o documentos complementarios). Sintetiza y unifica todo el material en un único Apunte Maestro armónico, integrando ordenadamente los contenidos de todas las partes sin redundancias.\n" if len(collected_sources) > 1 else ""

        user_prompt = f"""
{depth_instructions}
{multi_source_hint}
{f"INSTRUCCIONES Y ENFOQUE ESPECIAL DEL ESTUDIANTE: {custom_instructions}" if custom_instructions else ""}

A continuación tienes el material fuente analizado para sintetizar:

{"\n\n---\n\n".join(source_texts)}

Genera el Apunte Maestro siguiendo estrictamente el esquema JSON especificado.
"""

        print("[Proceso Síntesis] Generando Apunte Maestro final en formato JSON...")
        raw_response, synth_model = call_gemini_with_fallback(
            client=client,
            contents=user_prompt,
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json"
        )

        # Clean potential markdown wrapping if present
        if raw_response.startswith("```json"):
            raw_response = raw_response[7:]
        if raw_response.startswith("```"):
            raw_response = raw_response[3:]
        if raw_response.endswith("```"):
            raw_response = raw_response[:-3]
        raw_response = raw_response.strip()

        try:
            result_data = robust_parse_json(raw_response)
        except Exception as pe:
            try:
                print(f"Error parsing JSON from Gemini: {pe}")
            except Exception:
                pass
            return jsonify({
                "success": False,
                "error": f"La IA generó una respuesta pero ocurrió un problema al estructurar los datos ({str(pe)}). Intenta nuevamente.",
                "raw": raw_response[:400]
            }), 500

        # Enriquecer desarrollos y fórmulas con video_id para recortes visuales
        primary_video_id = None
        for s in collected_sources:
            if s.get("type") == "youtube" and s.get("id"):
                primary_video_id = s.get("id")
                break

        if "developments" in result_data and isinstance(result_data["developments"], list):
            for dev in result_data["developments"]:
                if primary_video_id and not dev.get("video_id"):
                    dev["video_id"] = primary_video_id
                if "video_snapshot" in dev and isinstance(dev["video_snapshot"], dict):
                    if primary_video_id and not dev["video_snapshot"].get("video_id"):
                        dev["video_snapshot"]["video_id"] = primary_video_id
                if "formulas" in dev and isinstance(dev["formulas"], list):
                    for f in dev["formulas"]:
                        if primary_video_id and not f.get("video_id"):
                            f["video_id"] = primary_video_id

        # Asegurar claves vacías para compatibilidad retroactiva
        result_data.setdefault("flashcards", [])
        result_data.setdefault("quiz", [])
        result_data.setdefault("exam_tips", [])
        result_data.setdefault("glossary", [])

        result_data["sources"] = collected_sources
        result_data["video_metadata"] = video_metadata
        result_data["model_used"] = synth_model
        
        return jsonify({
            "success": True,
            "model_used": synth_model,
            "data": result_data
        })

    except Exception as e:
        return handle_gemini_error(e)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"Iniciando ApuntesIA en http://localhost:{port} ...")
    app.run(host='0.0.0.0', port=port, debug=True)
