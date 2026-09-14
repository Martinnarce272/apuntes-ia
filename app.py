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

@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

class GeminiConfig:
    """
    Configuración centralizada de modelos Gemini:
    1. Modelo principal: gemini-3.5-flash-lite (ultrarrápido, generación en 2-4 segundos, 500 RPD)
    2. Fallback de alta capacidad: gemini-3.8-flash
    3. Último recurso: gemini-3.7-flash y gemini-3.6-flash (solo si los anteriores fallan por motivos distintos a cuota)
    """
    PRIMARY_MODEL = "gemini-3.5-flash-lite"
    FALLBACK_MODEL = "gemini-3.8-flash"
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
    if "503" in safe_msg or "unavailable" in safe_msg.lower() or "high demand" in safe_msg.lower():
        return jsonify({
            "success": False,
            "error": "Los servidores de Google Gemini están experimentando alta demanda temporal en procesamiento de video. Por favor espera 30 segundos y vuelve a intentar."
        }), 503

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
Eres un docente universitario y pedagogo de élite especializado en confeccionar apuntes de cátedra ilustrados, profundos y claros.
Tu misión es transformar el material fuente proporcionado (video de YouTube, documento PDF o ambos) en un **Apunte de Estudio Maestro** con formato de cuaderno universitario de excelencia, idéntico a los mejores apuntes de estudio con notas al margen, preguntas de examen, ideas clave y fórmulas desglosadas.

ESTRUCTURA Y ESTILO PEDAGÓGICO OBLIGATORIO:
1. TITULACIÓN DE UNIDADES POR PREGUNTAS Y PASOS NUMERADOS:
   - Formula los títulos de cada sección en 'developments' como preguntas directas o pasos estructurados numerados, por ejemplo:
     - "1) ¿Qué es [Concepto]?"
     - "2) Tipos y Clasificación de [Concepto]:"
     - "3) ¿Ventajas y Desventajas de [Concepto]?"
     - "4) ¿Cómo es su comportamiento a diferencia de [Alternativa]?"
     - "5) Criterio de Diseño y Fórmulas de Cálculo:"
     - "6) Verificaciones Críticas y Modos de Falla:"

2. RESALTADO DE CONCEPTOS CLAVE (ESTILO MARCADOR PASTEL):
   - En el texto de 'content_markdown', resalta las palabras, reglas y definiciones más críticas usando la sintaxis ==término resaltado== (por ejemplo: ==la losa transmite las cargas directamente a las columnas==, ==falla por punzonado==, ==ábaco y capitel==).

3. FÓRMULAS CON DESGLOSE COMPLETO DE VARIABLES ("donde:"):
   - Toda expresión matemática, física o técnica debe ir en LaTeX ($...$ o $$...$$).
   - En cada fórmula, incluye obligatoriamente 'where_variables': un array con la definición de CADA una de las variables que intervienen (ejemplo: ["$q_u$: Carga uniformemente distribuida mayorada", "$l_n$: Luz libre entre apoyos", "$l_2$: Ancho tributario del panel"]).

4. NOTAS AL MARGEN Y POST-ITS PEDAGÓGICOS ('callouts'):
   - Para cada unidad en 'developments', genera entre 1 y 3 callouts / post-its de estudio esenciales eligiendo entre estos tipos:
     * "idea_clave": La intuición física o conceptual profunda para entender el tema sin memorizar de memoria (ej. por qué una etapa constructiva es más exigida que el edificio terminado).
     * "pregunta_examen": Las preguntas típicas capciosas que toman los profesores en mesas de examen o finales, junto con la respuesta concisa y contundente.
     * "porque": Explicación de la causa subyacente (ej. "¿Por qué ocurre el punzonado?" o "¿Qué tiene que ver la masa con las fuerzas sísmicas?").
     * "observacion": Advertencias de cálculo, consideraciones de normativa reglamentaria o trampas donde los estudiantes suelen equivocarse.
     * "tip": Aclaraciones prácticas directas y ayudas al margen.
     * "regla_rapida": Reglas nemotécnicas o síntesis en 2 renglones (ej. "1. Solo Vu -> corte centrado. 2. Vu + Mu -> corte excéntrico.").

5. PROHIBIDO GENERAR FLASHCARDS O QUIZZES:
   - Concentra el 100% de la capacidad de síntesis en el Apunte Maestro y sus notas al margen.

Devuelve EXCLUSIVAMENTE un objeto JSON válido con la siguiente estructura:

{
  "title": "Título Claro y Profesional del Tema Principal",
  "topic_overview": "Breve sinopsis (2-3 oraciones) de lo que abarca este apunte",
  "estimated_study_time": "ej. 30 min",
  "key_takeaways": [
    {
      "type": "critical" | "rule" | "warning" | "tip",
      "title": "Título de la idea clave o regla de oro",
      "description": "Explicación concisa y contundente del concepto clave."
    }
  ],
  "general_diagram": {
    "title": "Mapa Conceptual o Flujo Global del Tema",
    "mermaid_code": "Código Mermaid.js sintácticamente válido (ej: graph TD\\n    A[...] --> B[...])"
  },
  "developments": [
    {
      "unit_number": 1,
      "title": "1) ¿Qué es [Concepto]?",
      "timestamp_display": "03:20",
      "timestamp_seconds": 200,
      "content_markdown": "Desarrollo con ==palabras resaltadas==, listas claras de ventajas/desventajas y explicaciones paso a paso.",
      "formulas": [
        {
          "latex": "$$M_0 = \\frac{q_u \\cdot l_n^2 \\cdot l_2}{8}$$",
          "where_variables": [
            "$q_u$: Carga uniformemente distribuida mayorada [kN/m²]",
            "$l_n$: Luz libre entre caras de columnas",
            "$l_2$: Ancho tributario del panel perpendicular al análisis"
          ],
          "explanation": "Momento isostático total de referencia para distribución longitudinal.",
          "timestamp_display": "04:15",
          "timestamp_seconds": 255
        }
      ],
      "callouts": [
        {
          "type": "idea_clave",
          "title": "Idea clave para entender",
          "content": "Más carga por el hormigonado superior + menor resistencia por corta edad del hormigón -> la zona alrededor de la columna puede ser la más exigida de toda la vida útil."
        },
        {
          "type": "pregunta_examen",
          "title": "Pregunta típica de final",
          "content": "¿Qué influencia tienen las vigas longitudinales entre apoyos en la distribución de momentos en el Método Directo?\n- Incrementan la rigidez de la franja de columna (representado por $\\alpha_1$). Si $\\alpha_1 l_2 / l_1 \\ge 1$, absorben cerca del 85% del momento."
        }
      ],
      "video_snapshot": {
        "has_visual": true,
        "timestamp_display": "03:20",
        "timestamp_seconds": 200,
        "description": "Esquema y fórmula explicada en la pizarra"
      },
      "mermaid_diagram": ""
    }
  ]
}
"""

@app.route('/api/demo', methods=['GET'])
def get_demo_notes():
    """Return a high-quality pre-generated study note for instant preview and testing."""
    sample = {
        "title": "Entrepisos Sin Vigas de Hormigón Armado (Cálculo y Diseño Estructural)",
        "topic_overview": "Guía maestra de estudio de nivel universitario sobre los sistemas de losas y placas planas apoyadas directamente sobre columnas: tipologías (ábacos y capiteles), ventajas frente a entrepisos tradicionales, diseño a flexión por el Método Directo y verificación crítica al punzonado según reglamento.",
        "estimated_study_time": "30 min",
        "sources": [
            {
                "type": "youtube",
                "title": "Clase Magistral: Entrepisos Sin Vigas y Punzonado",
                "thumbnail": "https://img.youtube.com/vi/aircAruvnKk/maxresdefault.jpg"
            },
            {
                "type": "pdf",
                "filename": "Entrepisos_Sin_Vigas_CIRSOC.pdf",
                "pages": 21
            }
        ],
        "key_takeaways": [
            {
                "type": "critical",
                "title": "Falla por Punzonado: Abrupta y Frágil",
                "description": "La reacción de la columna concentra altísimas tensiones de corte en un área reducida. Ocurre casi instantáneamente sin previo aviso y puede desatar un colapso en cadena."
            },
            {
                "type": "rule",
                "title": "Franja de Columna vs. Franja Intermedia",
                "description": "La franja de columna absorbe la mayor rigidez y la mayor parte de los momentos negativos sobre los apoyos. Las intermedias absorben los momentos positivos en el tramo."
            },
            {
                "type": "warning",
                "title": "Comportamiento en Zonas Sísmicas",
                "description": "Al requerir mayor espesor de losa, el edificio gana más masa ($F = m \\cdot a$), lo que incrementa notablemente las fuerzas sísmicas de inercia."
            },
            {
                "type": "tip",
                "title": "Armadura Inferior Contra Colapso Progresivo",
                "description": "Colocar armadura inferior pasante por la columna anclada adecuadamente mantiene suspendida la losa y previene la caída del entrepiso si el corte falla."
            }
        ],
        "developments": [
            {
                "unit_number": 1,
                "title": "1) ¿Qué es un entrepiso sin vigas y cuáles son sus tipos?",
                "content_markdown": "Es un sistema estructural en el que ==la losa transmite las cargas directamente a las columnas==, sin la intermediación de vigas tradicionales.\n\n### Tipos Principales:\n- **Placa Plana:** Losa con ==espesor constante== en toda su superficie. Requiere especial atención al punzonado en el encuentro losa-columna y a las deformaciones por flexión.\n- **Losa Plana (con Capitel y Ábaco):**\n  - ==Capitel:== Ensanche en la parte superior de la columna que aumenta la superficie de transferencia de carga y reduce tensiones tangenciales.\n  - ==Ábaco:== Sobre-espesor local de la losa en la vecindad de la columna que incrementa la rigidez local y la resistencia a flexión y punzonado.",
                "callouts": [
                    {
                        "type": "tip",
                        "title": "Tip / Ayuda al margen",
                        "content": "Las vigas que a veces se colocan entre columnas son **vigas muy finitas** que sirven solo para refuerzo o borde, de muy poca altura."
                    },
                    {
                        "type": "porque",
                        "title": "¿Por qué se colocan capiteles y ábacos?",
                        "content": "Aparecen **tracciones arriba en dos direcciones** y flexiones grandes en el encuentro columna-losa, originando tensiones tangenciales de corte (punzonado). El sobre-espesor reduce drásticamente estas tensiones críticas."
                    }
                ],
                "formulas": [],
                "mermaid_diagram": "graph TD\n    ESV[Entrepisos Sin Vigas] --> PP[Placa Plana: Espesor Constante]\n    ESV --> LP[Losa Plana con Refuerzos]\n    LP --> C[Capitel: Ensanche de Columna]\n    LP --> A[Ábaco: Sobre-espesor de Losa]"
            },
            {
                "unit_number": 2,
                "title": "2) ¿Ventajas y Desventajas de los Entrepisos Sin Vigas?",
                "content_markdown": "### Ventajas Principales:\n1. **Mayor altura útil del edificio:** Al no haber vigas descolgadas, a igualdad de altura total se pueden albergar más pisos o ganar espacio libre utilizable.\n2. **Mayor rapidez y economía de encofrado:** Fondos de encofrado completamente planos y sencillos de armar y desencofrar.\n3. **Flexibilidad de instalaciones:** Facilita el tendido directo de ductos de aire acondicionado, electricidad y cañerías sin interferencias de vigas.\n4. **Mejor iluminación y condiciones sanitarias:** Menos recovecos donde se acumule polvo y mejor reflexión de luz natural.\n\n### Desventajas Críticas:\n1. **Alto consumo de acero y hormigón:** Al disminuir el brazo de palanca interno, se incrementan las cuantías de armadura y el espesor de losa.\n2. **Mayor peso propio y sensibilidad sísmica:** El aumento de masa genera mayores fuerzas de inercia ($F = m \\cdot a$) durante terremotos.\n3. **Deformabilidad:** Presenta menor rigidez frente a acciones horizontales (viento/sismo) que un sistema aporticado con vigas.",
                "callouts": [
                    {
                        "type": "idea_clave",
                        "title": "Idea clave para entender",
                        "content": "En la etapa de construcción, **los puntales transmiten la carga del hormigonado fresco superior a las losas inferiores jóvenes**. Como el hormigón inferior aún no alcanzó su resistencia de diseño, esta etapa puede ser la más exigida de toda la vida útil de la estructura."
                    },
                    {
                        "type": "observacion",
                        "title": "¿Qué pasa en zonas sísmicas?",
                        "content": "Durante un sismo, el edificio desarrolla fuerzas de inercia proporcionales a su masa: **$F = m \\cdot a$**. Reducir el peso propio es el objetivo primordial de la ingeniería sísmica."
                    }
                ],
                "formulas": [
                    {
                        "latex": "$$F = m \\cdot a$$",
                        "where_variables": [
                            "$F$: Fuerza de inercia sísmica generada [N]",
                            "$m$: Masa total del edificio [kg]",
                            "$a$: Aceleración sísmica del terreno [m/s²]"
                        ],
                        "explanation": "Expresión fundamental de inercia: a mayor masa, mayores esfuerzos sobre columnas y fundaciones."
                    }
                ],
                "mermaid_diagram": ""
            },
            {
                "unit_number": 3,
                "title": "3) Diseño a Flexión: Método de Diseño Directo (MDD)",
                "content_markdown": "El Método de Diseño Directo es un procedimiento semiempírico para distribuir el momento flector total en paneles de losas regulares.\n\n### Pasos del Método:\n1. Calcular el ==Momento Isostático Total ($M_0$)== para cargas mayoradas en la dirección de análisis.\n2. Distribuir longitudinalmente $M_0$ entre momentos negativos (sobre columnas/apoyos) y momentos positivos (en el centro del tramo).\n3. Distribuir transversalmente dichos momentos entre la ==franja de columna== (mayor rigidez) y la ==franja intermedia==.",
                "callouts": [
                    {
                        "type": "pregunta_examen",
                        "title": "Pregunta de final / examen",
                        "content": "¿Qué influencia tienen las vigas longitudinales entre apoyos en la distribución de momentos en el Método Directo?\n- Incrementan la rigidez relativa $\\alpha_1 = \\frac{E_{cb} I_b}{E_{cs} I_s}$. Cuando $\\alpha_1 \\frac{l_2}{l_1} \\ge 1.0$, la viga absorbe aproximadamente el **85% del momento** asignado a la franja de columna."
                    },
                    {
                        "type": "observacion",
                        "title": "Observación para el cálculo",
                        "content": "Para aplicar el Método Directo se utilizan las **secciones brutas de hormigón** sin considerar la armadura ni la fisuración previa."
                    }
                ],
                "formulas": [
                    {
                        "latex": "$$M_0 = \\frac{q_u \\cdot l_n^2 \\cdot l_2}{8}$$",
                        "where_variables": [
                            "$q_u$: Carga uniformemente distribuida mayorada [kN/m²]",
                            "$l_n$: Luz libre entre caras de columnas o capiteles ($\\ge 0.65 l_1$) [m]",
                            "$l_2$: Ancho tributario del panel perpendicular a la dirección analizada [m]"
                        ],
                        "explanation": "Momento flector isostático total de referencia equivalente a una viga simplemente apoyada."
                    }
                ],
                "mermaid_diagram": ""
            },
            {
                "unit_number": 4,
                "title": "4) Diseño a Corte y Falla por Punzonado (Corte Bidireccional)",
                "content_markdown": "En entrepisos sin vigas deben verificarse dos mecanismos de falla por corte:\n1. **Corte por acción de viga (unidireccional):** La sección crítica se ubica a una distancia $d$ de la cara de la columna.\n2. **Corte por punzonado (bidireccional):** La sección crítica corresponde a un ==perímetro cerrado ($b_0$) ubicado a una distancia $d/2$== del contorno de la columna.\n\n### Transferencia de Momentos Desbalanceados:\nCuando la columna recibe corte vertical $V_u$ y momento flector desbalanceado $M_u$, la transmisión ocurre por dos mecanismos simultáneos:\n- **Por flexión:** Una fracción $M_{ub} = \\gamma_f M_u$ es absorbida por la armadura de flexión.\n- **Por excentricidad de corte:** La fracción restante $M_{uv} = (1 - \\gamma_f) M_u$ distorsiona las tensiones de corte en el perímetro crítico.",
                "callouts": [
                    {
                        "type": "regla_rapida",
                        "title": "Regla rápida para recordar",
                        "content": "1. **Solo $V_u$:** Tensiones de corte uniformes -> punzonado centrado.\n2. **$V_u + M_u$:** Tensiones de corte desiguales -> punzonado excéntrico (el lado donde se suma el momento gobierna el dimensionamiento)."
                    },
                    {
                        "type": "porque",
                        "title": "¿Por qué la falla por punzonado es tan peligrosa?",
                        "content": "Es **abrupta y frágil**: el hormigón se rompe casi instantáneamente sin presentar grandes fisuras o deformaciones previas que alerten del colapso inminente."
                    }
                ],
                "formulas": [
                    {
                        "latex": "$$\\phi V_c \\ge V_u$$",
                        "where_variables": [
                            "$\\phi$: Factor de reducción de resistencia para corte ($0.75$)",
                            "$V_c$: Resistencia nominal al corte aportada por el hormigón [kN]",
                            "$V_u$: Esfuerzo de corte mayorado actuante en la sección crítica [kN]"
                        ],
                        "explanation": "Condición reglamentaria indispensable de seguridad estructural frente al punzonado."
                    }
                ],
                "mermaid_diagram": "graph TD\n    V[Corte en Entrepisos Sin Vigas] --> V1[Corte Unidireccional: Sección a distancia d]\n    V --> V2[Punzonado Bidireccional: Perímetro cerrado a d/2]\n    V2 --> Centrado[Centrado: Solo Vu]\n    V2 --> Excentrico[Excéntrico: Vu + Momento Desbalanceado Mu]"
            }
        ],
        "general_diagram": {
            "title": "Flujo de Diseño y Comportamiento de Entrepisos Sin Vigas",
            "mermaid_code": "graph TD\n    A[Geometría y Cargas del Entrepiso] --> B{¿Cumple Condiciones del Método Directo?}\n    B -- Sí --> C[Método de Diseño Directo: Cálculo de Mo]\n    B -- No --> D[Método del Pórtico Equivalente / MEF]\n    C --> E[Distribución Longitudinal: Negativos y Positivos]\n    E --> F[Distribución Transversal: Franja de Columna e Intermedia]\n    F --> G[Dimensionamiento a Flexión]\n    G --> H[Verificación Crítica de Punzonado en Columnas: d/2]\n    H --> I{¿Verifica phi Vc >= Vu?}\n    I -- Sí --> J[Estructura Conforme y Segura]\n    I -- No --> K[Colocar Ábacos/Capiteles, Aumentar Espesor o Armadura de Corte]"
        },
        "flashcards": [],
        "quiz": []
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
                video_models = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.7-flash"]
                video_summary, video_model = call_gemini_with_fallback(
                    client=client,
                    contents=[video_part, extract_prompt],
                    models=video_models
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

INSTRUCCIÓN CRÍTICA:
Genera ÚNICAMENTE el Apunte y Resumen de Estudio. Está TERMINANTEMENTE PROHIBIDO generar quizzes, cuestionarios, flashcards o glosarios. Solo devuelve el JSON con title, topic_overview, estimated_study_time, key_takeaways, general_diagram y developments.
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

        # Eliminar cualquier residuo de quiz o flashcards
        result_data.pop("quiz", None)
        result_data.pop("flashcards", None)
        result_data.pop("exam_tips", None)
        result_data.pop("glossary", None)

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
