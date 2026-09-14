# SintesisAI (ApuntesIA) — Generador Inteligente de Apuntes con IA

Aplicación web full-stack para transformar videos de YouTube (con o sin subtítulos) y documentos PDF en **Apuntes de Estudio Maestros** interactivos, estructurados con fórmulas LaTeX, diagramas conceptuales Mermaid.js, flashcards 3D y exámenes de autoevaluación interactivos, potenciada por **Google Gemini API**.

---

## 🌟 Características Principales

- **Multi-fuente Simultánea:** Admite múltiples videos de YouTube y documentos PDF en una única consulta para generar un apunte maestro consolidado sin redundancias.
- **Videos con Subtítulos:** Extracción ultrarrápida de transcripciones oficiales o autogeneradas con marcas de tiempo `[MM:SS]` vía `youtube-transcript-api`.
- **Videos sin Subtítulos (Multimodal Vision):** Análisis audiovisual nativo con la API de Google Gemini (`google-genai`), con muestreo de FPS adaptativo según la duración y procesamiento secuencial para optimizar memoria RAM.
- **Documentos PDF:** Procesamiento y limpieza de texto página por página con `pypdf`.
- **Salida Pedagógica Estructurada:**
  - Resumen ejecutivo y conceptos clave.
  - Desarrollos temáticos profundos con fórmulas matemáticas en LaTeX ($\LaTeX$) y diagramas Mermaid.js.
  - Flashcards interactivas con animación 3D de volteo.
  - Examen tipo test (Quiz) con retroalimentación instantánea.
  - Glosario técnico y consejos de examen.
- **Exportación:** Copia directa a Markdown y vista de impresión optimizada para guardar como PDF.

---

## 🧠 Configuración y Cadena de Modelos de IA

La selección y jerarquía de modelos está centralizada en la clase `GeminiConfig` dentro de `app.py`, garantizando un único punto de verdad para toda la aplicación.

### Jerarquía de Inferencia:

1. **Modelo Principal (`PRIMARY_MODEL`):**
   - **`gemini-3.8-flash`**
   - Utilizado por defecto para todas las consultas debido a su alta velocidad, amplia ventana de contexto y soporte multimodal completo.
2. **Modelo de Fallback Primario (`FALLBACK_MODEL`):**
   - **`gemini-3.5-flash-lite`**
   - Modelo de alta disponibilidad con cuota extendida (500 solicitudes por día - RPD). Si el modelo principal agota su cuota (HTTP 429), la aplicación conmuta inmediatamente a este modelo sin reintentos redundantes.
3. **Modelos de Último Recurso (`LAST_RESORT_MODELS`):**
   - **`gemini-3.7-flash`** y **`gemini-3.6-flash`**
   - Se activan exclusivamente si los modelos anteriores fallan por razones distintas a cuota agotada (ej. errores 5xx de servidor, 503 sobrecarga temporal o 404 modelo discontinuado). Esto evita consumir cuota en modelos de reserva cuando el problema de fondo es saturación de tasa (429).

### Cómo actualizar modelos deprecados:

Si Google Gemini discontinúa o lanza nuevas versiones de modelos, basta con editar las constantes en `GeminiConfig` en `app.py`:

```python
class GeminiConfig:
    PRIMARY_MODEL = "gemini-3.8-flash"
    FALLBACK_MODEL = "gemini-3.5-flash-lite"
    LAST_RESORT_MODELS = ["gemini-3.7-flash", "gemini-3.6-flash"]
    ACTIVE_MODELS = [PRIMARY_MODEL, FALLBACK_MODEL]
    MODELS = ACTIVE_MODELS + LAST_RESORT_MODELS
```

La lógica de reintento y salto ante 404/429 se adapta automáticamente a los modelos definidos en esta configuración.

---

## 🎥 Manejo de Videos de YouTube (Con y Sin Subtítulos)

La aplicación detecta de forma automática la presencia de subtítulos para optimizar velocidad y consumo de recursos:

1. **Videos con Subtítulos:**
   - La función `get_youtube_transcript(video_id)` consulta las pistas disponibles con `youtube-transcript-api`.
   - Prioriza pistas en español (`es`, `es-419`, `es-ES`, etc.). Si solo existen pistas en otros idiomas (ej. inglés), las traduce automáticamente a español si son traducibles.
   - Estructura el texto con marcas de tiempo cronológicas `[MM:SS] Texto`.
   - El procesamiento es 100% textual y no consume cuota multimodal de video.

2. **Videos sin Subtítulos (Visión Multimodal Nativa):**
   - Si el video carece de subtítulos, la app recurre a la visión artificial nativa de Gemini enviando la URL del video mediante `types.Part(file_data=types.FileData(file_uri=...))`.
   - **FPS Adaptativo:** Para videos de hasta 20 minutos se muestrea a `0.5 fps` (1 cuadro cada 2 segundos); para videos más largos (>20 min), se reduce automáticamente a `0.1 fps` (1 cuadro cada 10 segundos) para no desbordar el presupuesto de tokens.
   - **Procesamiento Secuencial:** Cada video sin subtítulos se analiza individualmente en una llamada dedicada previa. Tras obtener el resumen estructurado de cada video, se libera la referencia en memoria y se fuerza la recolección de basura con `gc.collect()`. Esto asegura estabilidad en servidores con memoria limitada (como los 512 MB de la capa gratuita de Render).
   - Finalmente, todos los textos extraídos se unen en un único prompt ligero de texto para generar el Apunte Maestro JSON.

---

## 🔑 Configuración de `GEMINI_API_KEY`

La aplicación soporta tres métodos de configuración para la clave de API:

### 1. Archivo `.env` (Recomendado para desarrollo local)
Crea o edita un archivo `.env` en la raíz del proyecto con el siguiente contenido:
```env
GEMINI_API_KEY=AIzaSyTuClaveDeGoogleAIStudio...
```

### 2. Variable de Entorno del Sistema / Plataforma
Configura la variable de entorno en tu terminal o en el panel de tu proveedor de hosting (ej. Render, Railway, Heroku):
```bash
# Linux / macOS
export GEMINI_API_KEY="AIzaSyTuClaveDeGoogleAIStudio..."

# Windows PowerShell
$env:GEMINI_API_KEY="AIzaSyTuClaveDeGoogleAIStudio..."
```

### 3. Interfaz Web (Modal de Configuración)
En la barra superior de la app, haz clic en el botón **"Configurar API Key"**:
- Puedes ingresar tu clave directamente en la interfaz.
- La app verificará la clave contra el backend (`/api/save-key`) y la persistirá localmente en el archivo `.env` del servidor.
- También se enviará como header `X-Gemini-Api-Key` en las solicitudes de generación.

> **¿Cómo obtener una clave gratuita?**
> Ingresa a [Google AI Studio](https://aistudio.google.com/app/apikey), inicia sesión con tu cuenta de Google y presiona **"Create API key"**. Es 100% gratuita.

---

## 🛡️ Manejo Centralizado de Errores

El backend cuenta con la función `handle_gemini_error(exc)` en `app.py`, que clasifica los errores de la API y responde con códigos de estado HTTP y mensajes claros:

| Código HTTP | Causa | Mensaje al Usuario |
|---|---|---|
| **429** | Cuota gratuita agotada (`RESOURCE_EXHAUSTED` / `rate limit`) | *"Se alcanzó el límite de uso gratuito de Gemini por ahora. Esperá unos minutos y probá de nuevo, o probá con menos videos a la vez."* |
| **404** | Modelo no encontrado o deprecado por Google | *"El modelo de IA solicitado no está disponible o ha sido discontinuado por Google Gemini. Por favor verifica la configuración de modelos."* |
| **400** | Límite de tokens o contexto excedido | *"El contenido ingresado supera el límite máximo de tokens o contexto permitido por la IA. Intenta con videos más cortos o con menos documentos simultáneos."* |
| **500** | Error interno o inesperado | *"Error al generar el apunte con Gemini: {detalle}"* |

---

## 🚀 Instalación y Ejecución

### Requisitos Previos:
- Python 3.10 o superior instalado.
- Google Chrome / Navegador web moderno.

### Instalación:
```bash
# 1. Clonar el repositorio
git clone https://github.com/Martinnarce272/apuntes-ia.git
cd apuntes-ia

# 2. Instalar dependencias
pip install -r requirements.txt
```

### Ejecutar Localmente:
```bash
python app.py
```
La aplicación estará disponible en: [http://localhost:5001](http://localhost:5001)

*(En Windows, también puedes hacer doble clic en `iniciar_apuntes_ia.bat`)*

### Compartir con Amigos (Túnel Público Gratuito):
Ejecuta el script incluido:
```bash
compartir_con_amigos.bat
```
Generará un enlace temporal público `https://xxxx.trycloudflare.com` para que amigos puedan probar la app desde cualquier dispositivo sin abrir puertos de red.

---

## 🧪 Pruebas Automatizadas

La aplicación cuenta con una suite integral de pruebas unitarias y de integración que cubren extracción de IDs, fallbacks de modelos, visión multimodal, procesamiento secuencial y manejo de errores:

```bash
python test_suite.py
```

Para correr las pruebas en modo detallado:
```bash
python -m unittest test_suite.py -v
```
