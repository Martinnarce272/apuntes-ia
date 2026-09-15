import sys
import os
import re
import json
import requests
import tempfile
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
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "apuntes-ia-google-auth-secret-key-2026")
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

# Instancia global del modelo faster-whisper para reutilizar en memoria
whisper_model = None

def get_whisper_model():
    """Carga de forma perezosa y reutiliza el modelo faster-whisper 'base' en CPU."""
    global whisper_model
    if whisper_model is None:
        print("[Whisper] Inicializando modelo faster-whisper 'base' en CPU...")
        from faster_whisper import WhisperModel
        whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    return whisper_model

def transcribe_youtube_audio_with_whisper(video_id):
    """
    Descarga el audio del video de YouTube usando yt-dlp y lo transcribe localmente con faster-whisper.
    Se utiliza como fallback cuando un video no cuenta con subtítulos oficiales ni automáticos en YouTube.
    """
    import yt_dlp

    with tempfile.TemporaryDirectory() as temp_dir:
        output_template = os.path.join(temp_dir, f"{video_id}.%(ext)s")
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True
        }

        print(f"[Whisper] Descargando audio de video {video_id} con yt-dlp...")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        except Exception as yerr:
            print(f"[Whisper] Error descargando audio con yt-dlp: {yerr}")
            return {
                "success": False,
                "error": f"No se pudo descargar el audio del video ({str(yerr)})."
            }

        downloaded_files = list(Path(temp_dir).glob(f"{video_id}.*"))
        if not downloaded_files:
            return {
                "success": False,
                "error": f"No se encontró el archivo de audio descargado para el video {video_id}."
            }

        audio_path = str(downloaded_files[0])
        print(f"[Whisper] Transcribiendo audio de {audio_path} con faster-whisper...")
        try:
            model = get_whisper_model()
            segments, info = model.transcribe(audio_path, beam_size=5)

            timed_lines = []
            full_texts = []
            for seg in segments:
                m, s = divmod(int(seg.start), 60)
                h, m = divmod(m, 60)
                time_str = f"[{h:02d}:{m:02d}:{s:02d}]" if h > 0 else f"[{m:02d}:{s:02d}]"
                text = seg.text.strip()
                if text:
                    timed_lines.append(f"{time_str} {text}")
                    full_texts.append(text)

            if not full_texts:
                return {
                    "success": False,
                    "error": "La transcripción de audio resultó vacía."
                }

            return {
                "success": True,
                "timed_text": "\n".join(timed_lines),
                "full_text": " ".join(full_texts),
                "duration_seconds": getattr(info, 'duration', 0)
            }
        except Exception as werr:
            print(f"[Whisper] Error transcribiendo audio con faster-whisper: {werr}")
            return {
                "success": False,
                "error": f"Error en la transcripción local con Whisper: {str(werr)}"
            }

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
    """Indica que el backend está listo para procesar fuentes y delegar a Puter.js."""
    return jsonify({
        "status": "ready",
        "engine": "puter.js",
        "puter_ready": True
    })

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
    """
    Extrae fuentes (YouTube con subtítulos o Whisper, documentos PDF) y construye el prompt pedagógico.
    Devuelve los prompts estructurados para que Puter.js ejecute la inferencia directamente en el navegador del usuario.
    """
    custom_instructions = request.form.get('instructions', '').strip()
    depth_level = request.form.get('depth', 'completo')  # 'conciso', 'completo', 'exhaustivo'

    collected_sources = []
    source_texts = []

    # 1. Procesar videos de YouTube (soporta múltiples URLs)
    raw_urls = request.form.getlist('youtubeUrls')
    single_url = request.form.get('youtubeUrl', '').strip()
    if single_url and single_url not in raw_urls:
        raw_urls.append(single_url)

    cleaned_urls = []
    for u in raw_urls:
        u = u.strip()
        if u and u not in cleaned_urls:
            cleaned_urls.append(u)

    if cleaned_urls:
        for idx, url in enumerate(cleaned_urls):
            video_id = extract_youtube_id(url)
            if not video_id:
                return jsonify({"success": False, "error": f"El enlace '{url}' no es un video de YouTube válido."}), 400

            v_meta = get_youtube_metadata(video_id)
            transcript_res = get_youtube_transcript(video_id)

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
                # Video sin subtítulos: descargar audio con yt-dlp y transcribir con faster-whisper
                print(f"[Extracción] Video #{idx+1} '{v_meta['title']}' no tiene subtítulos. Transcribiendo audio con faster-whisper...")
                whisper_res = transcribe_youtube_audio_with_whisper(video_id)

                if whisper_res.get("success"):
                    collected_sources.append({
                        "type": "youtube",
                        "title": v_meta["title"],
                        "id": video_id,
                        "thumbnail": v_meta["thumbnail"],
                        "has_captions": False,
                        "mode": "whisper_audio",
                        "order": idx + 1
                    })
                    source_texts.append(
                        f"=== FUENTE VIDEO DE YOUTUBE #{idx+1} (AUDIO TRANSCRIPCIÓN WHISPER): '{v_meta['title']}' (ID: {video_id}) ===\n"
                        f"Transcripción con marcas de tiempo:\n{whisper_res['timed_text']}"
                    )
                else:
                    return jsonify({
                        "success": False,
                        "error": f"No se pudo extraer contenido para el video '{v_meta['title']}': {whisper_res.get('error', 'Error de transcripción')}"
                    }), 400

    # 2. Procesar documentos PDF subidos
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

    # Ensamblar Prompt de Usuario para Puter.js
    depth_instructions = {
        "conciso": "Nivel de profundidad: RESUMEN CONCISO. Enfócate en las ideas centrales, esquemas y conceptos primordiales.",
        "completo": "Nivel de profundidad: APUNTE COMPLETO UNIVERSITARIO. Desarrolla todos los temas con rigor, explicaciones paso a paso, ejemplos y fundamentos.",
        "exhaustivo": "Nivel de profundidad: GUÍA EXHAUSTIVA DE ESTUDIO. Máximo nivel de detalle pedagógico, desglosando cada subtema, fórmula, demostración y casos prácticos."
    }.get(depth_level, "Nivel de profundidad: APUNTE COMPLETO UNIVERSITARIO.")

    multi_source_hint = f"\nNOTA PEDAGÓGICA: Has recibido {len(collected_sources)} fuentes distintas (pueden ser partes consecutivas de una clase o serie, o documentos complementarios). Sintetiza y unifica todo el material en un único Apunte Maestro armónico, integrando ordenadamente los contenidos de todas las partes sin redundancias.\n" if len(collected_sources) > 1 else ""
    custom_inst_text = f"INSTRUCCIONES Y ENFOQUE ESPECIAL DEL ESTUDIANTE: {custom_instructions}" if custom_instructions else ""
    joined_sources = "\n\n---\n\n".join(source_texts)

    user_prompt = f"""{depth_instructions}
{multi_source_hint}
{custom_inst_text}

A continuación tienes el material fuente analizado para sintetizar:

{joined_sources}

INSTRUCCIÓN CRÍTICA:
Genera ÚNICAMENTE el Apunte y Resumen de Estudio. Está TERMINANTEMENTE PROHIBIDO generar quizzes, cuestionarios, flashcards o glosarios. Solo devuelve el JSON con title, topic_overview, estimated_study_time, key_takeaways, general_diagram y developments.
Responde ÚNICAMENTE con el objeto JSON, sin texto introductorio ni bloques de formato markdown adicionales."""

    return jsonify({
        "success": True,
        "system_instruction": SYSTEM_INSTRUCTION,
        "user_prompt": user_prompt,
        "sources": collected_sources
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"Iniciando ApuntesIA en http://localhost:{port} ...")
    app.run(host='0.0.0.0', port=port, debug=True)
