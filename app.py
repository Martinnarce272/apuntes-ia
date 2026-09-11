import sys
import os
import re
import json
import requests
from pathlib import Path
from flask import Flask, render_template, request, jsonify

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

def get_youtube_caption_tracks(video_id):
    """Retrieve available subtitle tracks and signed baseUrls via YouTube Android Player API without scraping."""
    debug_info = {}
    try:
        url = "https://www.youtube.com/youtubei/v1/player?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
        payload = {
            "context": {
                "client": {
                    "clientName": "ANDROID",
                    "clientVersion": "20.10.38"
                }
            },
            "videoId": video_id
        }
        headers = {
            "User-Agent": "com.google.android.youtube/20.10.38 (Linux; U; Android 14)",
            "Content-Type": "application/json"
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=8)
        debug_info["status_code"] = resp.status_code
        if resp.status_code == 200:
            data = resp.json()
            raw_tracks = data.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
            debug_info["raw_tracks_count"] = len(raw_tracks)
            tracks = []
            for t in raw_tracks:
                name = t.get("name", {}).get("runs", [{}])[0].get("text", "Subtítulos")
                tracks.append({
                    "name": name,
                    "language_code": t.get("languageCode", "es"),
                    "base_url": t.get("baseUrl", ""),
                    "is_auto": t.get("kind") == "asr" or "auto" in name.lower()
                })
            return tracks, debug_info
        else:
            debug_info["resp_text"] = resp.text[:200]
    except Exception as e:
        debug_info["exception"] = str(e)
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
        
    meta = get_youtube_metadata(video_id)
    tracks, debug_info = get_youtube_caption_tracks(video_id)
    meta["video_id"] = video_id
    meta["success"] = True
    meta["caption_tracks"] = tracks
    meta["has_captions"] = len(tracks) > 0
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
        
    meta = get_youtube_metadata(video_id)
    tracks, debug_info = get_youtube_caption_tracks(video_id)
    return jsonify({
        "success": True,
        "video_id": video_id,
        "title": meta.get("title", f"Video {video_id}"),
        "thumbnail": meta.get("thumbnail", ""),
        "has_captions": len(tracks) > 0,
        "caption_tracks": tracks,
        "debug": debug_info
    })



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
