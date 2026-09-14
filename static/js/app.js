/**
 * ApuntesIA - Application Core JavaScript
 * Handles YouTube & PDF ingestion, Gemini AI interaction,
 * Mermaid.js diagramming, KaTeX formulas, 3D Flashcards, and Quizzes.
 */

document.addEventListener('DOMContentLoaded', () => {
    // State management
    const state = {
        activeTab: 'tab-notes',
        selectedVideos: [],
        selectedFiles: [],
        selectedAudios: [],
        currentResult: null,
        flashcards: [],
        currentFlashcardIndex: 0,
        quizAnswers: {},
        quizScore: 0
    };

    // DOM Elements
    const elements = {
        // Views
        inputView: document.getElementById('input-view'),
        loadingView: document.getElementById('loading-view'),
        resultsView: document.getElementById('results-view'),

        // Nav & Theme
        btnThemeToggle: document.getElementById('btn-theme-toggle'),

        // Form & Inputs
        generatorForm: document.getElementById('generator-form'),
        youtubeUrl: document.getElementById('youtube-url'),
        btnAddYt: document.getElementById('btn-add-yt'),
        ytCountBadge: document.getElementById('yt-count-badge'),
        btnClearYt: document.getElementById('btn-clear-yt'),
        ytVideosList: document.getElementById('yt-videos-list'),
        ytFallbackBanner: document.getElementById('yt-fallback-banner'),
        btnFallbackAudio: document.getElementById('btn-fallback-audio'),
        btnFallbackPdf: document.getElementById('btn-fallback-pdf'),
        btnFallbackNotes: document.getElementById('btn-fallback-notes'),
        audioCard: document.getElementById('audio-card'),
        audioDropzone: document.getElementById('audio-dropzone'),
        audioFileInput: document.getElementById('audio-files'),
        audioCountBadge: document.getElementById('audio-count-badge'),
        btnClearAudio: document.getElementById('btn-clear-audio'),
        audioList: document.getElementById('audio-list'),
        pdfDropzone: document.getElementById('pdf-dropzone'),
        pdfFileInput: document.getElementById('pdf-files'),
        pdfCountBadge: document.getElementById('pdf-count-badge'),
        btnClearPdf: document.getElementById('btn-clear-pdf'),
        fileList: document.getElementById('file-list'),
        manualTextInput: document.getElementById('manual-text'),
        instructionsInput: document.getElementById('instructions'),
        btnGenerate: document.getElementById('btn-generate'),

        // Loading
        loadingStatusTitle: document.getElementById('loading-status-title'),
        loadingStatusDesc: document.getElementById('loading-status-desc'),
        progressBar: document.getElementById('progress-bar'),
        step1: document.getElementById('step-1'),
        step2: document.getElementById('step-2'),
        step3: document.getElementById('step-3'),

        // Results Toolbar
        btnBackToInput: document.getElementById('btn-back-to-input'),
        docTitleBadge: document.getElementById('doc-title-badge'),
        btnCopyMarkdown: document.getElementById('btn-copy-markdown'),
        btnExportPdf: document.getElementById('btn-export-pdf'),
        tabButtons: document.querySelectorAll('.tab-btn'),
        tabPanes: document.querySelectorAll('.tab-pane'),

        // Document Tab
        noteMainTitle: document.getElementById('note-main-title'),
        noteOverview: document.getElementById('note-overview'),
        noteEstTime: document.getElementById('note-est-time'),
        sourceChipsContainer: document.getElementById('source-chips-container'),
        keyTakeawaysGrid: document.getElementById('key-takeaways-grid'),
        developmentsContainer: document.getElementById('developments-container'),
        examTipsList: document.getElementById('exam-tips-list'),
        glossaryGrid: document.getElementById('glossary-grid'),

        // Flashcards Tab
        flashcardsCountBadge: document.getElementById('flashcards-count'),
        currentCardNum: document.getElementById('current-card-num'),
        totalCardsNum: document.getElementById('total-cards-num'),
        activeFlashcard: document.getElementById('active-flashcard'),
        cardTopicFront: document.getElementById('card-topic-front'),
        cardQuestionText: document.getElementById('card-question-text'),
        cardAnswerText: document.getElementById('card-answer-text'),
        btnPrevCard: document.getElementById('btn-prev-card'),
        btnFlipCard: document.getElementById('btn-flip-card'),
        btnNextCard: document.getElementById('btn-next-card'),

        // Quiz Tab
        quizCountBadge: document.getElementById('quiz-count'),
        quizContainer: document.getElementById('quiz-container'),
        quizScoreBadge: document.getElementById('quiz-score-badge'),
        quizScoreValue: document.getElementById('quiz-score-value'),
        quizTotalValue: document.getElementById('quiz-total-value'),
        btnResetQuiz: document.getElementById('btn-reset-quiz'),

        // Diagram Tab
        diagramTitle: document.getElementById('diagram-title'),
        mermaidGlobalContainer: document.getElementById('mermaid-global-container'),

        // Toast
        toast: document.getElementById('toast'),
        toastMsg: document.getElementById('toast-msg')
    };

    // Initialize Mermaid
    if (window.mermaid) {
        mermaid.initialize({
            startOnLoad: false,
            theme: 'dark',
            securityLevel: 'loose',
            fontFamily: 'Inter, sans-serif'
        });
    }

    // --------------------------------------------------------------------------
    // 1. Google Gemini API Key Management & Configuration
    // --------------------------------------------------------------------------
    const API_KEY_STORAGE_KEY = 'gemini_api_key';

    function getStoredApiKey() {
        return (localStorage.getItem(API_KEY_STORAGE_KEY) || '').trim();
    }

    function setStoredApiKey(key) {
        if (!key) {
            localStorage.removeItem(API_KEY_STORAGE_KEY);
        } else {
            localStorage.setItem(API_KEY_STORAGE_KEY, key.trim());
        }
        updateApiKeyUI();
    }

    async function checkApiKeyStatus() {
        try {
            const storedKey = getStoredApiKey();
            const res = await fetch('/api/health-gemini', {
                headers: storedKey ? { 'X-Gemini-Api-Key': storedKey } : {}
            });
            const data = await res.json();
            const hasKey = !!storedKey || !!data.configured;
            updateApiKeyUI(hasKey);
        } catch (e) {
            updateApiKeyUI(!!getStoredApiKey());
        }
    }

    function updateApiKeyUI(isConfigured = null) {
        const key = getStoredApiKey();
        const btnKey = document.getElementById('btn-api-key');
        const statusText = document.getElementById('key-status-text');
        const indicator = document.getElementById('key-indicator');

        if (isConfigured === null) {
            isConfigured = key.length >= 20;
        }

        if (indicator) {
            if (isConfigured) {
                indicator.className = 'status-dot status-active';
                if (statusText) statusText.textContent = 'Gemini Lista';
                if (btnKey) btnKey.title = 'Tu API Key de Gemini está configurada. Haz clic para modificarla.';
            } else {
                indicator.className = 'status-dot status-inactive';
                if (statusText) statusText.textContent = 'Configurar Gemini';
                if (btnKey) btnKey.title = 'Configura tu clave gratuita de Gemini para generar apuntes.';
            }
        }
    }

    function openApiKeyModal() {
        const modal = document.getElementById('modal-api-key');
        const input = document.getElementById('input-api-key');
        const msgBox = document.getElementById('key-message-box');
        if (input) input.value = getStoredApiKey();
        if (msgBox) {
            msgBox.className = 'message-box hidden';
            msgBox.textContent = '';
        }
        if (modal) {
            modal.classList.remove('hidden');
        }
    }

    function closeApiKeyModal() {
        const modal = document.getElementById('modal-api-key');
        if (modal) modal.classList.add('hidden');
    }

    // Connect modal elements
    const btnApiKey = document.getElementById('btn-api-key');
    if (btnApiKey) btnApiKey.addEventListener('click', openApiKeyModal);

    const btnCloseModal = document.getElementById('btn-close-modal');
    if (btnCloseModal) btnCloseModal.addEventListener('click', closeApiKeyModal);

    const btnCancelKey = document.getElementById('btn-cancel-key');
    if (btnCancelKey) btnCancelKey.addEventListener('click', closeApiKeyModal);

    const modalApiKey = document.getElementById('modal-api-key');
    if (modalApiKey) {
        modalApiKey.addEventListener('click', (e) => {
            if (e.target === modalApiKey) closeApiKeyModal();
        });
    }

    const btnToggleVis = document.getElementById('btn-toggle-key-vis');
    if (btnToggleVis) {
        btnToggleVis.addEventListener('click', () => {
            const input = document.getElementById('input-api-key');
            if (input) {
                const isPass = input.type === 'password';
                input.type = isPass ? 'text' : 'password';
                btnToggleVis.querySelector('i').className = isPass ? 'fa-solid fa-eye-slash' : 'fa-solid fa-eye';
            }
        });
    }

    const btnSaveKey = document.getElementById('btn-save-key');
    if (btnSaveKey) {
        btnSaveKey.addEventListener('click', () => {
            const input = document.getElementById('input-api-key');
            const msgBox = document.getElementById('key-message-box');
            const val = (input ? input.value : '').trim();

            if (!val) {
                setStoredApiKey('');
                if (msgBox) {
                    msgBox.className = 'message-box error';
                    msgBox.textContent = 'Clave eliminada. Se utilizará la clave del servidor si está configurada.';
                    msgBox.classList.remove('hidden');
                }
                showToast('Clave eliminada.', 'info');
                setTimeout(closeApiKeyModal, 1000);
                return;
            }

            if (val.length < 20) {
                if (msgBox) {
                    msgBox.className = 'message-box error';
                    msgBox.textContent = 'La clave parece demasiado corta. Las claves de Gemini suelen tener más de 30 caracteres (empiezan con AIzaSy... o AQ...).';
                    msgBox.classList.remove('hidden');
                }
                return;
            }

            setStoredApiKey(val);
            if (msgBox) {
                msgBox.className = 'message-box success';
                msgBox.textContent = '¡Clave guardada con éxito en tu navegador!';
                msgBox.classList.remove('hidden');
            }
            showToast('¡Clave de Gemini guardada correctamente!', 'success');
            setTimeout(closeApiKeyModal, 800);
        });
    }

    // Check status on load
    checkApiKeyStatus();

    if (window.pdfjsLib) {
        pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
    }

    async function extractPdfTextInBrowser(file) {
        if (!window.pdfjsLib) {
            return { filename: file.name, pages: 1, text: '' };
        }
        try {
            const arrayBuffer = await file.arrayBuffer();
            const loadingTask = pdfjsLib.getDocument({ data: arrayBuffer });
            const pdf = await loadingTask.promise;
            const numPages = pdf.numPages;
            let fullText = '';
            
            for (let pageNum = 1; pageNum <= numPages; pageNum++) {
                const page = await pdf.getPage(pageNum);
                const textContent = await page.getTextContent();
                const pageStrings = textContent.items.map(item => item.str).join(' ');
                if (pageStrings.trim()) {
                    fullText += `\n--- [Página ${pageNum} / ${numPages}] ---\n${pageStrings}\n`;
                }
            }
            
            return {
                filename: file.name,
                pages: numPages,
                text: fullText.trim()
            };
        } catch (e) {
            console.warn(`Error al extraer texto en navegador de ${file.name}:`, e);
            return { filename: file.name, pages: 1, text: '' };
        }
    }

    class YouTubeCaptionError extends Error {
        constructor(code, message, details = {}) {
            super(message);
            this.name = 'YouTubeCaptionError';
            this.code = code;
            this.details = details;
        }
    }

    function parseYouTubeTranscriptXml(xmlText) {
        if (!xmlText) return { fullText: '', timedText: '', durationSeconds: 0, snippetCount: 0 };

        function decodeEntities(str) {
            return str
                .replace(/&amp;/g, '&')
                .replace(/&lt;/g, '<')
                .replace(/&gt;/g, '>')
                .replace(/&quot;/g, '"')
                .replace(/&#39;/g, "'")
                .replace(/&#x27;/g, "'")
                .replace(/\n/g, ' ')
                .trim();
        }

        const snippets = [];
        const fullTextPieces = [];
        let maxSeconds = 0;

        // Try standard browser DOMParser first
        try {
            if (typeof window !== 'undefined' && window.DOMParser) {
                const doc = new DOMParser().parseFromString(xmlText, 'text/xml');
                
                // Format 1 (<text start="0.0" dur="2.0">Hello</text>)
                const textNodes = doc.querySelectorAll('text');
                if (textNodes && textNodes.length > 0) {
                    textNodes.forEach(node => {
                        const start = parseFloat(node.getAttribute('start')) || 0;
                        const text = decodeEntities(node.textContent || '');
                        if (text) {
                            if (start > maxSeconds) maxSeconds = start;
                            const mm = String(Math.floor(start / 60)).padStart(2, '0');
                            const ss = String(Math.floor(start % 60)).padStart(2, '0');
                            snippets.push(`[${mm}:${ss}] ${text}`);
                            fullTextPieces.push(text);
                        }
                    });
                    if (fullTextPieces.length > 0) {
                        return {
                            fullText: fullTextPieces.join(' '),
                            timedText: snippets.join('\n'),
                            durationSeconds: Math.ceil(maxSeconds),
                            snippetCount: snippets.length
                        };
                    }
                }

                // Format 3 (ASR <p t="13900" d="5780"><s>bueno</s><s> buenas</s></p>)
                const pNodes = doc.querySelectorAll('p');
                if (pNodes && pNodes.length > 0) {
                    pNodes.forEach(node => {
                        const tMs = parseInt(node.getAttribute('t'), 10) || 0;
                        const startSec = tMs / 1000;
                        const sNodes = node.querySelectorAll('s');
                        let segText = '';
                        if (sNodes && sNodes.length > 0) {
                            segText = Array.from(sNodes).map(s => s.textContent || '').join('');
                        } else {
                            segText = node.textContent || '';
                        }
                        segText = decodeEntities(segText);
                        if (segText) {
                            if (startSec > maxSeconds) maxSeconds = startSec;
                            const mm = String(Math.floor(startSec / 60)).padStart(2, '0');
                            const ss = String(Math.floor(startSec % 60)).padStart(2, '0');
                            snippets.push(`[${mm}:${ss}] ${segText}`);
                            fullTextPieces.push(segText);
                        }
                    });
                    if (fullTextPieces.length > 0) {
                        return {
                            fullText: fullTextPieces.join(' '),
                            timedText: snippets.join('\n'),
                            durationSeconds: Math.ceil(maxSeconds),
                            snippetCount: snippets.length
                        };
                    }
                }
            }
        } catch (e) {
            console.warn('DOMParser fallback to Regex parser:', e);
        }

        // Regex fallback
        const reText = /<text\b[^>]*\bstart="([^"]*)"[^>]*>([\s\S]*?)<\/text>/g;
        const reP = /<p\b[^>]*\bt="(\d+)"[^>]*>([\s\S]*?)<\/p>/g;
        const reS = /<s[^>]*>([\s\S]*?)<\/s>/g;

        let match;
        let format1Found = false;
        while ((match = reText.exec(xmlText)) !== null) {
            format1Found = true;
            const startSec = parseFloat(match[1]) || 0;
            const text = decodeEntities(match[2].replace(/<[^>]+>/g, ''));
            if (text) {
                if (startSec > maxSeconds) maxSeconds = startSec;
                const mm = String(Math.floor(startSec / 60)).padStart(2, '0');
                const ss = String(Math.floor(startSec % 60)).padStart(2, '0');
                snippets.push(`[${mm}:${ss}] ${text}`);
                fullTextPieces.push(text);
            }
        }

        if (!format1Found) {
            while ((match = reP.exec(xmlText)) !== null) {
                const startMs = parseInt(match[1], 10) || 0;
                const startSec = startMs / 1000;
                const inner = match[2];
                let segmentText = '';

                const sMatches = [...inner.matchAll(reS)];
                if (sMatches.length > 0) {
                    segmentText = sMatches.map(m => m[1]).join('');
                } else {
                    segmentText = inner.replace(/<[^>]+>/g, '');
                }
                segmentText = decodeEntities(segmentText);

                if (segmentText) {
                    if (startSec > maxSeconds) maxSeconds = startSec;
                    const mm = String(Math.floor(startSec / 60)).padStart(2, '0');
                    const ss = String(Math.floor(startSec % 60)).padStart(2, '0');
                    snippets.push(`[${mm}:${ss}] ${segmentText}`);
                    fullTextPieces.push(segmentText);
                }
            }
        }

        return {
            fullText: fullTextPieces.join(' '),
            timedText: snippets.join('\n'),
            durationSeconds: Math.ceil(maxSeconds),
            snippetCount: snippets.length
        };
    }

    async function fetchYouTubeTranscript(video) {
        let tracks = video.caption_tracks || [];

        // If tracks were not loaded during preview, fetch them now
        if (!tracks || tracks.length === 0) {
            try {
                const resp = await fetch(`/api/youtube-tracks?videoId=${video.id || encodeURIComponent(video.url)}`);
                const data = await resp.json();
                if (data.success && data.caption_tracks) {
                    tracks = data.caption_tracks;
                }
            } catch (e) {
                console.warn('Error fetching tracks for video:', video.url, e);
            }
        }

        // 1. IF SUBTITLES EXIST: Try direct download from browser client
        if (tracks && tracks.length > 0) {
            const selectedTrack = tracks.find(t => 
                !t.is_api && (
                    t.language_code === 'es' || 
                    t.language_code.startsWith('es-') ||
                    (t.name && t.name.toLowerCase().includes('spanish')) ||
                    (t.name && t.name.toLowerCase().includes('español'))
                )
            ) || tracks.find(t => !t.is_api);

            if (selectedTrack && selectedTrack.base_url) {
                try {
                    const res = await fetch(selectedTrack.base_url);
                    if (res.ok) {
                        const xmlText = await res.text();
                        if (xmlText && xmlText.trim()) {
                            const parsed = parseYouTubeTranscriptXml(xmlText);
                            if (parsed.fullText && parsed.snippetCount > 0) {
                                return {
                                    title: video.title || 'Video de YouTube',
                                    videoId: video.id,
                                    thumbnail: video.thumbnail,
                                    fullText: parsed.fullText,
                                    timedText: parsed.timedText,
                                    hasCaptions: true
                                };
                            }
                        }
                    }
                } catch (fetchErr) {
                    console.warn('Fallo al descargar subtítulos directos XML en cliente:', fetchErr);
                }
            }
        }

        // 2. BACKEND TRANSCRIPT API FALLBACK: Retrieve direct subtitles without downloading media
        try {
            const tRes = await fetch(`/api/youtube-transcript?videoId=${video.id || encodeURIComponent(video.url)}`);
            if (tRes.ok) {
                const tData = await tRes.json();
                if (tData.success && tData.full_text) {
                    return {
                        title: video.title || 'Video de YouTube',
                        videoId: video.id,
                        thumbnail: video.thumbnail,
                        fullText: tData.full_text,
                        timedText: tData.timed_text || tData.full_text,
                        hasCaptions: true
                    };
                }
            }
        } catch (tErr) {
            console.warn('Backend transcript API not available:', tErr);
        }

        // 3. Video without subtitles: Google Gemini backend will analyze it natively!
        return {
            title: video.title || 'Video de YouTube',
            videoId: video.id,
            thumbnail: video.thumbnail,
            fullText: null,
            timedText: null,
            hasCaptions: false
        };
    }

    // Demo button handler
    const btnLoadDemo = document.getElementById('btn-load-demo');
    if (btnLoadDemo) {
        btnLoadDemo.addEventListener('click', async () => {
            try {
                showToast('Cargando apunte de demostración...', 'info');
                const res = await fetch('/api/demo');
                const data = await res.json();
                if (data.success) {
                    state.currentResult = data.data;
                    renderStudyMaterial(data.data);
                    switchView('results');
                    showToast('¡Apunte de ejemplo cargado con éxito!', 'success');
                }
            } catch (e) {
                console.error('Error loading demo:', e);
                showToast('Error al cargar el ejemplo', 'error');
            }
        });
    }

    // Theme Toggle
    elements.btnThemeToggle.addEventListener('click', () => {
        document.body.classList.toggle('light-theme');
        const isLight = document.body.classList.contains('light-theme');
        elements.btnThemeToggle.querySelector('i').className = isLight ? 'fa-solid fa-sun' : 'fa-solid fa-moon';
        
        if (window.mermaid) {
            mermaid.initialize({
                startOnLoad: false,
                theme: isLight ? 'default' : 'dark'
            });
            if (state.currentResult) {
                renderAllMermaidDiagrams();
            }
        }
    });

    // --------------------------------------------------------------------------
    // 2. YouTube & File Inputs (Multi-URL Support)
    // --------------------------------------------------------------------------
    async function processAndAddYouTubeUrls(text) {
        if (!text || !text.trim()) return;
        
        // Split by newlines, commas, or spaces if user pasted multiple links at once
        const potentialUrls = text
            .split(/[\n,\s]+/)
            .map(s => s.trim())
            .filter(s => s.length > 5);

        if (potentialUrls.length === 0) return;

        let addedCount = 0;
        for (const rawUrl of potentialUrls) {
            // Check if already in list
            if (state.selectedVideos.some(v => v.url === rawUrl)) {
                continue;
            }

            try {
                const res = await fetch('/api/youtube-preview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: rawUrl })
                });
                const data = await res.json();
                if (data.success) {
                    state.selectedVideos.push({
                        url: rawUrl,
                        id: data.video_id,
                        title: data.title,
                        author: data.author,
                        thumbnail: data.thumbnail,
                        fallback_thumbnail: data.fallback_thumbnail,
                        has_captions: data.has_captions,
                        has_audio: data.has_audio,
                        caption_tracks: data.caption_tracks || []
                    });
                    addedCount++;
                    if (data.has_captions === false) {
                        showToast(`"${data.title || rawUrl}" agregado. Sin subtítulos: su audio se transcribirá con IA automáticamente.`, 'info');
                    }
                } else {
                    showToast(`No se pudo verificar el video "${rawUrl}": ${data.error || 'Enlace inválido'}`, 'warning');
                }
            } catch (e) {
                console.error('Error fetching preview for:', rawUrl, e);
            }
        }

        if (addedCount > 0) {
            elements.youtubeUrl.value = '';
            updateYtList();
            showToast(`${addedCount} video${addedCount > 1 ? 's agregados' : ' agregado'} a la lista.`, 'success');
        }
    }

    function updateYtList() {
        const count = state.selectedVideos.length;
        if (count === 0) {
            elements.ytVideosList.classList.add('hidden');
            elements.ytCountBadge.classList.add('hidden');
            if (elements.btnClearYt) elements.btnClearYt.classList.add('hidden');
            elements.ytVideosList.innerHTML = '';
            if (elements.ytFallbackBanner) elements.ytFallbackBanner.classList.add('hidden');
            return;
        }

        elements.ytCountBadge.textContent = `${count} ${count === 1 ? 'video' : 'videos'}`;
        elements.ytCountBadge.classList.remove('hidden');
        if (elements.btnClearYt) elements.btnClearYt.classList.remove('hidden');
        elements.ytVideosList.classList.remove('hidden');

        // Toggle fallback banner if any video is missing captions
        const hasMissingCaptions = state.selectedVideos.some(v => v.has_captions === false);
        if (elements.ytFallbackBanner) {
            if (hasMissingCaptions) {
                elements.ytFallbackBanner.classList.remove('hidden');
            } else {
                elements.ytFallbackBanner.classList.add('hidden');
            }
        }

        elements.ytVideosList.innerHTML = state.selectedVideos.map((vid, idx) => `
            <div class="yt-video-item" data-idx="${idx}">
                <img class="yt-video-thumb" src="${escapeHtml(vid.thumbnail)}" alt="Thumbnail" onerror="this.src='${escapeHtml(vid.fallback_thumbnail)}'">
                <div class="yt-video-details">
                    <h4>${escapeHtml(vid.title)}</h4>
                    <div class="yt-video-meta">
                        <span class="badge-order">Parte #${idx + 1}</span>
                        <span>${escapeHtml(vid.author)}</span>
                        ${vid.has_captions !== false 
                            ? '<span class="badge-success"><i class="fa-solid fa-closed-captioning"></i> Subtítulos listos</span>' 
                            : '<span class="badge-ai" style="background:rgba(99,102,241,0.25);color:#a5b4fc;padding:2px 8px;border-radius:6px;font-size:0.75rem;border:1px solid rgba(99,102,241,0.3);"><i class="fa-solid fa-wand-magic-sparkles"></i> Transcripción por audio IA</span>'}
                    </div>
                </div>
                <button type="button" class="remove-item-btn remove-yt-btn" data-idx="${idx}" title="Eliminar este video">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>
        `).join('');

        // Wire remove buttons
        document.querySelectorAll('.remove-yt-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const idx = parseInt(btn.getAttribute('data-idx'));
                state.selectedVideos.splice(idx, 1);
                updateYtList();
            });
        });
    }

    if (elements.btnClearYt) {
        elements.btnClearYt.addEventListener('click', () => {
            state.selectedVideos = [];
            updateYtList();
            showToast('Lista de videos vaciada.', 'info');
        });
    }

    // Connect banner rescue buttons
    if (elements.btnFallbackAudio) {
        elements.btnFallbackAudio.addEventListener('click', () => {
            if (elements.audioFileInput) elements.audioFileInput.click();
        });
    }
    if (elements.btnFallbackPdf) {
        elements.btnFallbackPdf.addEventListener('click', () => {
            if (elements.pdfFileInput) elements.pdfFileInput.click();
        });
    }
    if (elements.btnFallbackNotes) {
        elements.btnFallbackNotes.addEventListener('click', () => {
            if (elements.manualTextInput) {
                elements.manualTextInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
                elements.manualTextInput.focus();
            }
        });
    }

    // Audio Files Drag & Drop and Input
    if (elements.audioDropzone && elements.audioFileInput) {
        elements.audioDropzone.addEventListener('click', () => {
            elements.audioFileInput.click();
        });

        elements.audioDropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            elements.audioDropzone.classList.add('dragover');
        });

        elements.audioDropzone.addEventListener('dragleave', () => {
            elements.audioDropzone.classList.remove('dragover');
        });

        elements.audioDropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            elements.audioDropzone.classList.remove('dragover');
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                handleAudioFiles(e.dataTransfer.files);
            }
        });

        elements.audioFileInput.addEventListener('change', () => {
            if (elements.audioFileInput.files && elements.audioFileInput.files.length > 0) {
                handleAudioFiles(elements.audioFileInput.files);
            }
        });
    }

    function handleAudioFiles(files) {
        for (let file of files) {
            const ext = file.name.split('.').pop().toLowerCase();
            const isAudio = file.type.startsWith('audio/') || ['mp3', 'wav', 'm4a', 'ogg', 'aac', 'webm'].includes(ext);
            if (isAudio) {
                if (!state.selectedAudios.some(a => a.name === file.name && a.size === file.size)) {
                    state.selectedAudios.push(file);
                }
            } else {
                showToast(`El archivo "${file.name}" no es un formato de audio soportado (.mp3, .wav, .m4a).`, 'warning');
            }
        }
        updateAudioList();
    }

    function updateAudioList() {
        const count = state.selectedAudios.length;
        if (count === 0) {
            if (elements.audioList) {
                elements.audioList.classList.add('hidden');
                elements.audioList.innerHTML = '';
            }
            if (elements.audioCountBadge) elements.audioCountBadge.classList.add('hidden');
            if (elements.btnClearAudio) elements.btnClearAudio.classList.add('hidden');
            return;
        }

        if (elements.audioCountBadge) {
            elements.audioCountBadge.textContent = `${count} ${count === 1 ? 'audio' : 'audios'}`;
            elements.audioCountBadge.classList.remove('hidden');
        }
        if (elements.btnClearAudio) elements.btnClearAudio.classList.remove('hidden');
        if (elements.audioList) {
            elements.audioList.classList.remove('hidden');
            elements.audioList.innerHTML = state.selectedAudios.map((file, idx) => `
                <div class="file-item">
                    <div class="file-name">
                        <i class="fa-solid fa-file-audio" style="color: #34d399;"></i>
                        <span>${escapeHtml(file.name)} (${(file.size / (1024 * 1024)).toFixed(2)} MB)</span>
                    </div>
                    <button type="button" class="remove-item-btn remove-audio-btn" data-idx="${idx}" title="Eliminar">
                        <i class="fa-solid fa-xmark"></i>
                    </button>
                </div>
            `).join('');

            document.querySelectorAll('.remove-audio-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const idx = parseInt(btn.getAttribute('data-idx'));
                    state.selectedAudios.splice(idx, 1);
                    updateAudioList();
                });
            });
        }
    }

    if (elements.btnClearAudio) {
        elements.btnClearAudio.addEventListener('click', () => {
            state.selectedAudios = [];
            if (elements.audioFileInput) elements.audioFileInput.value = '';
            updateAudioList();
            showToast('Archivos de audio removidos.', 'info');
        });
    }

    // Add button click
    elements.btnAddYt.addEventListener('click', () => {
        processAndAddYouTubeUrls(elements.youtubeUrl.value);
    });

    // Enter key in input
    elements.youtubeUrl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            processAndAddYouTubeUrls(elements.youtubeUrl.value);
        }
    });

    // Auto-detect multi-line paste
    elements.youtubeUrl.addEventListener('paste', (e) => {
        setTimeout(() => {
            const val = elements.youtubeUrl.value;
            if (val.includes('\n') || val.includes('http')) {
                processAndAddYouTubeUrls(val);
            }
        }, 50);
    });

    // PDF Drag & Drop
    elements.pdfDropzone.addEventListener('click', () => {
        elements.pdfFileInput.click();
    });

    elements.pdfDropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        elements.pdfDropzone.classList.add('dragover');
    });

    elements.pdfDropzone.addEventListener('dragleave', () => {
        elements.pdfDropzone.classList.remove('dragover');
    });

    elements.pdfDropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        elements.pdfDropzone.classList.remove('dragover');
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            handleFiles(e.dataTransfer.files);
        }
    });

    elements.pdfFileInput.addEventListener('change', () => {
        if (elements.pdfFileInput.files && elements.pdfFileInput.files.length > 0) {
            handleFiles(elements.pdfFileInput.files);
        }
    });

    function handleFiles(files) {
        for (let file of files) {
            if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
                // Check if already added
                if (!state.selectedFiles.some(f => f.name === file.name && f.size === file.size)) {
                    state.selectedFiles.push(file);
                }
            } else {
                showToast(`El archivo "${file.name}" no es un PDF válido.`, 'warning');
            }
        }
        updateFileList();
    }

    function updateFileList() {
        const count = state.selectedFiles.length;
        if (count === 0) {
            elements.fileList.classList.add('hidden');
            if (elements.pdfCountBadge) elements.pdfCountBadge.classList.add('hidden');
            if (elements.btnClearPdf) elements.btnClearPdf.classList.add('hidden');
            elements.fileList.innerHTML = '';
            return;
        }

        if (elements.pdfCountBadge) {
            elements.pdfCountBadge.textContent = `${count} ${count === 1 ? 'archivo' : 'archivos'}`;
            elements.pdfCountBadge.classList.remove('hidden');
        }
        if (elements.btnClearPdf) elements.btnClearPdf.classList.remove('hidden');
        elements.fileList.classList.remove('hidden');

        elements.fileList.innerHTML = state.selectedFiles.map((file, idx) => `
            <div class="file-item">
                <div class="file-name">
                    <i class="fa-solid fa-file-pdf"></i>
                    <span>${escapeHtml(file.name)} (${(file.size / (1024 * 1024)).toFixed(2)} MB)</span>
                </div>
                <button type="button" class="remove-item-btn remove-file-btn" data-idx="${idx}" title="Eliminar">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>
        `).join('');

        document.querySelectorAll('.remove-file-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const idx = parseInt(btn.getAttribute('data-idx'));
                state.selectedFiles.splice(idx, 1);
                updateFileList();
            });
        });
    }

    if (elements.btnClearPdf) {
        elements.btnClearPdf.addEventListener('click', () => {
            state.selectedFiles = [];
            if (elements.pdfFileInput) elements.pdfFileInput.value = '';
            updateFileList();
            showToast('Archivos PDF removidos.', 'info');
        });
    }

    // Radio cards UI selection
    document.querySelectorAll('.radio-card').forEach(card => {
        card.addEventListener('click', () => {
            document.querySelectorAll('.radio-card').forEach(c => c.classList.remove('active'));
            card.classList.add('active');
            card.querySelector('input').checked = true;
        });
    });

    // --------------------------------------------------------------------------
    // 3. Form Submission & Google Gemini AI Pipeline
    // --------------------------------------------------------------------------
    elements.generatorForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        // If user typed a URL but forgot to click 'Agregar', process it first
        const pendingUrl = elements.youtubeUrl.value.trim();
        if (pendingUrl) {
            await processAndAddYouTubeUrls(pendingUrl);
        }

        const manualText = (elements.manualTextInput?.value || '').trim();
        const hasVideos = state.selectedVideos.length > 0;
        const hasPdfs = state.selectedFiles.length > 0;
        const hasAudios = (state.selectedAudios && state.selectedAudios.length > 0);
        const hasManual = manualText.length > 0;

        if (!hasVideos && !hasPdfs && !hasAudios && !hasManual) {
            showToast('Por favor agrega un enlace de YouTube, sube un PDF, un audio o escribe apuntes de estudio.', 'error');
            return;
        }

        const currentApiKey = getStoredApiKey();

        if (elements.btnGenerate) elements.btnGenerate.disabled = true;

        // Switch to loading view
        switchView('loading');
        
        // Progress stage 1: Preparing Materials
        elements.progressBar.style.width = '25%';
        elements.step1.className = 'step-item active';
        elements.step2.className = 'step-item';
        elements.step3.className = 'step-item';
        elements.loadingStatusTitle.textContent = 'Preparando fuentes y materiales...';
        elements.loadingStatusDesc.textContent = 'Verificando subtítulos de YouTube y preparando documentos...';

        try {
            // Check client-side YouTube captions (direct timedtext download from user IP)
            const clientTranscripts = {};
            for (const vid of state.selectedVideos) {
                elements.loadingStatusDesc.textContent = `Consultando subtítulos de "${vid.title || 'video'}"...`;
                try {
                    const tr = await fetchYouTubeTranscript(vid);
                    if (tr && tr.fullText && tr.fullText.length > 30) {
                        clientTranscripts[vid.id] = tr.fullText;
                    }
                } catch (e) {
                    console.warn(`No se pudieron extraer subtítulos para ${vid.id} en cliente:`, e);
                }
            }

            // Progress stage 2: Calling Google Gemini AI
            elements.progressBar.style.width = '60%';
            elements.step1.className = 'step-item completed';
            elements.step2.className = 'step-item active';
            elements.loadingStatusTitle.textContent = 'Generando apunte maestro con Google Gemini AI...';
            elements.loadingStatusDesc.textContent = 'Gemini está sintetizando conceptos clave, deducciones, fórmulas KaTeX y diagramas Mermaid...';

            const selectedDepth = document.querySelector('input[name="depth"]:checked')?.value || 'completo';
            const userInstructions = elements.instructionsInput ? elements.instructionsInput.value.trim() : '';

            const formData = new FormData();
            formData.append('depth', selectedDepth);
            formData.append('instructions', userInstructions);
            formData.append('notes_text', manualText);
            formData.append('youtube_urls', JSON.stringify(state.selectedVideos.map(v => v.url)));
            formData.append('client_transcripts', JSON.stringify(clientTranscripts));

            for (const pdf of state.selectedFiles) {
                formData.append('pdf_files', pdf);
            }
            for (const audio of state.selectedAudios) {
                formData.append('audio_files', audio);
            }
            if (currentApiKey) {
                formData.append('apiKey', currentApiKey);
            }

            const response = await fetch('/api/generate-notes', {
                method: 'POST',
                headers: currentApiKey ? { 'X-Gemini-Api-Key': currentApiKey } : {},
                body: formData
            });

            const data = await response.json();

            if (!response.ok || !data.success) {
                if (response.status === 401 || data.needs_key) {
                    switchView('input');
                    openApiKeyModal();
                    showToast(data.error || 'Por favor ingresa tu API Key gratuita de Google Gemini para continuar.', 'warning');
                    return;
                }
                throw new Error(data.error || 'Ocurrió un error al generar los apuntes con Gemini.');
            }

            // Progress stage 3: Render
            elements.progressBar.style.width = '100%';
            elements.step2.className = 'step-item completed';
            elements.step3.className = 'step-item completed';
            elements.loadingStatusTitle.textContent = '¡Apunte estructurado!';
            elements.loadingStatusDesc.textContent = 'Renderizando fórmulas KaTeX y mapas conceptuales...';

            state.currentResult = data.data;
            renderStudyMaterial(data.data);
            switchView('results');
            showToast('¡Apunte generado con éxito con Google Gemini AI!', 'success');

        } catch (err) {
            console.error('Error durante la generación:', err);
            switchView('input');
            showToast(err.message || 'Error al generar el apunte con Gemini. Intenta nuevamente.', 'error');
        } finally {
            if (elements.btnGenerate) elements.btnGenerate.disabled = false;
        }
    });

    let progressInterval = null;
    function simulateProgress() {
        let pct = 10;
        elements.progressBar.style.width = '10%';
        elements.step1.className = 'step-item active';
        elements.step2.className = 'step-item';
        elements.step3.className = 'step-item';
        elements.loadingStatusTitle.textContent = 'Extrayendo el material fuente...';
        elements.loadingStatusDesc.textContent = 'Leyendo transcripciones de video y páginas del PDF.';

        clearInterval(progressInterval);
        progressInterval = setInterval(() => {
            if (pct < 45) {
                pct += 5;
                elements.progressBar.style.width = `${pct}%`;
            } else if (pct < 85) {
                pct += 2;
                elements.progressBar.style.width = `${pct}%`;
                elements.step2.className = 'step-item active';
                elements.loadingStatusTitle.textContent = 'Analizando y estructurando los apuntes...';
                elements.loadingStatusDesc.textContent = 'Sintetizando conceptos clave, deducciones matemáticas y desarrollos.';
            } else if (pct < 96) {
                pct += 1;
                elements.progressBar.style.width = `${pct}%`;
                elements.step3.className = 'step-item active';
                elements.loadingStatusTitle.textContent = 'Generando diagramas visuales y quiz...';
                elements.loadingStatusDesc.textContent = 'Construyendo flashcards interactivas y mapas conceptuales.';
            }
        }, 600);
    }

    function switchView(viewName) {
        clearInterval(progressInterval);
        elements.inputView.classList.remove('active');
        elements.loadingView.classList.remove('active');
        elements.resultsView.classList.remove('active');
        elements.inputView.classList.add('hidden');
        elements.loadingView.classList.add('hidden');
        elements.resultsView.classList.add('hidden');

        if (viewName === 'input') {
            elements.inputView.classList.remove('hidden');
            elements.inputView.classList.add('active');
        } else if (viewName === 'loading') {
            elements.loadingView.classList.remove('hidden');
            elements.loadingView.classList.add('active');
        } else if (viewName === 'results') {
            elements.resultsView.classList.remove('hidden');
            elements.resultsView.classList.add('active');
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    }

    // --------------------------------------------------------------------------
    // 4. Render Study Material
    // --------------------------------------------------------------------------
    function renderStudyMaterial(data) {
        // Document Header
        elements.noteMainTitle.textContent = data.title || 'Apunte de Estudio';
        elements.docTitleBadge.textContent = data.title || 'Apunte Generado';
        elements.noteOverview.textContent = data.topic_overview || '';
        elements.noteEstTime.textContent = data.estimated_study_time || '20 min';

        // Sources chips
        let sourcesHtml = '';
        if (data.sources && Array.isArray(data.sources)) {
            data.sources.forEach(src => {
                if (src.type === 'youtube') {
                    sourcesHtml += `<span class="info-chip"><i class="fa-brands fa-youtube" style="color:#ef4444"></i> ${escapeHtml(src.title)}</span>`;
                } else if (src.type === 'pdf') {
                    sourcesHtml += `<span class="info-chip"><i class="fa-solid fa-file-pdf" style="color:#3b82f6"></i> ${escapeHtml(src.filename)} (${src.pages} pág.)</span>`;
                }
            });
        }
        elements.sourceChipsContainer.innerHTML = sourcesHtml;

        // 1. Key Takeaways ("Cosas Importantes")
        const typeIcons = {
            critical: '<i class="fa-solid fa-triangle-exclamation" style="color:var(--accent-rose)"></i>',
            warning: '<i class="fa-solid fa-circle-exclamation" style="color:var(--accent-amber)"></i>',
            tip: '<i class="fa-solid fa-lightbulb" style="color:var(--accent-emerald)"></i>',
            rule: '<i class="fa-solid fa-thumbtack" style="color:var(--primary)"></i>'
        };

        if (data.key_takeaways && data.key_takeaways.length > 0) {
            elements.keyTakeawaysGrid.innerHTML = data.key_takeaways.map(item => `
                <div class="takeaway-card ${escapeHtml(item.type || 'rule')}">
                    <div class="takeaway-header">
                        ${typeIcons[item.type] || typeIcons.rule}
                        <h4>${escapeHtml(item.title)}</h4>
                    </div>
                    <p>${escapeHtml(item.description)}</p>
                </div>
            `).join('');
        } else {
            elements.keyTakeawaysGrid.innerHTML = '<p class="text-muted">No se especificaron puntos críticos individuales.</p>';
        }

        // 2. Exhaustive Developments ("Desarrollos")
        if (data.developments && data.developments.length > 0) {
            elements.developmentsContainer.innerHTML = data.developments.map((dev, idx) => {
                const unitNum = dev.unit_number || (idx + 1);
                const markdownParsed = marked.parse(dev.content_markdown || '');
                
                // Optional inline diagram
                let diagramHtml = '';
                if (dev.mermaid_diagram && dev.mermaid_diagram.trim()) {
                    const diagId = `mermaid-dev-${idx}`;
                    diagramHtml = `
                        <div class="unit-diagram-box">
                            <div class="unit-diagram-title"><i class="fa-solid fa-project-diagram"></i> Diagrama de Estructura / Proceso</div>
                            <div id="${diagId}" class="mermaid-inline-diagram" data-mermaid="${encodeURIComponent(dev.mermaid_diagram)}"></div>
                        </div>
                    `;
                }

                // Visual concept illustration card
                let visualCardHtml = '';
                if (dev.visual_description && dev.visual_description.trim()) {
                    visualCardHtml = `
                        <div class="visual-concept-card">
                            <div class="visual-concept-icon"><i class="fa-solid fa-image"></i></div>
                            <div>
                                <h5>Representación Visual Sugerida:</h5>
                                <p>${escapeHtml(dev.visual_description)}</p>
                            </div>
                        </div>
                    `;
                }

                return `
                    <div class="unit-card">
                        <span class="unit-badge">Unidad ${unitNum}</span>
                        <h3 class="unit-title">${escapeHtml(dev.title || `Sección ${unitNum}`)}</h3>
                        <div class="unit-content math-renderable">
                            ${markdownParsed}
                        </div>
                        ${diagramHtml}
                        ${visualCardHtml}
                    </div>
                `;
            }).join('');
        }

        // 3. Exam Tips
        if (data.exam_tips && data.exam_tips.length > 0) {
            elements.examTipsList.innerHTML = data.exam_tips.map(tip => `
                <div class="exam-tip-item">
                    <i class="fa-solid fa-crosshairs"></i>
                    <p>${escapeHtml(tip)}</p>
                </div>
            `).join('');
        } else {
            elements.examTipsList.closest('.study-section').style.display = 'none';
        }

        // 4. Glossary
        if (data.glossary && data.glossary.length > 0) {
            elements.glossaryGrid.innerHTML = data.glossary.map(item => `
                <div class="glossary-item">
                    <dt>${escapeHtml(item.term)}</dt>
                    <dd>${escapeHtml(item.definition)}</dd>
                </div>
            `).join('');
        } else {
            elements.glossaryGrid.closest('.study-section').style.display = 'none';
        }

        // Render Math (KaTeX) in the document
        if (window.renderMathInElement) {
            renderMathInElement(elements.developmentsContainer, {
                delimiters: [
                    { left: '$$', right: '$$', display: true },
                    { left: '$', right: '$', display: false }
                ],
                throwOnError: false
            });
        }

        // 5. Flashcards
        state.flashcards = data.flashcards || [];
        state.currentFlashcardIndex = 0;
        elements.flashcardsCountBadge.textContent = state.flashcards.length;
        elements.totalCardsNum.textContent = state.flashcards.length;
        if (state.flashcards.length > 0) {
            displayFlashcard(0);
        }

        // 6. Quiz
        renderQuiz(data.quiz || []);

        // 7. Global Diagram (Tab 4)
        if (data.general_diagram && data.general_diagram.mermaid_code) {
            elements.diagramTitle.textContent = data.general_diagram.title || 'Mapa Conceptual Global';
            elements.mermaidGlobalContainer.setAttribute('data-mermaid', encodeURIComponent(data.general_diagram.mermaid_code));
        } else {
            elements.mermaidGlobalContainer.innerHTML = '<p class="text-muted">No se generó un diagrama global para este tema.</p>';
        }

        // Render all Mermaid diagrams
        renderAllMermaidDiagrams();
    }

    // --------------------------------------------------------------------------
    // 5. Mermaid Rendering Helper
    // --------------------------------------------------------------------------
    async function renderAllMermaidDiagrams() {
        if (!window.mermaid) return;

        // Render inline unit diagrams
        const inlineDiagrams = document.querySelectorAll('.mermaid-inline-diagram');
        for (let i = 0; i < inlineDiagrams.length; i++) {
            const el = inlineDiagrams[i];
            const rawCode = decodeURIComponent(el.getAttribute('data-mermaid') || '');
            if (rawCode) {
                try {
                    const cleanCode = sanitizeMermaidCode(rawCode);
                    const { svg } = await mermaid.render(`svg-inline-${i}-${Date.now()}`, cleanCode);
                    el.innerHTML = svg;
                } catch (err) {
                    console.warn('Error rendering inline Mermaid diagram:', err);
                    el.innerHTML = `<pre class="mermaid-code-fallback">${escapeHtml(rawCode)}</pre>`;
                }
            }
        }

        // Render global diagram
        const globalBox = elements.mermaidGlobalContainer;
        const globalRaw = decodeURIComponent(globalBox.getAttribute('data-mermaid') || '');
        if (globalRaw) {
            try {
                const cleanCode = sanitizeMermaidCode(globalRaw);
                const { svg } = await mermaid.render(`svg-global-${Date.now()}`, cleanCode);
                globalBox.innerHTML = svg;
            } catch (err) {
                console.warn('Error rendering global Mermaid diagram:', err);
                globalBox.innerHTML = `<pre class="mermaid-code-fallback">${escapeHtml(globalRaw)}</pre>`;
            }
        }
    }

    function sanitizeMermaidCode(code) {
        let cleaned = code.trim();
        // Remove markdown backticks if returned inside code
        if (cleaned.startsWith('```mermaid')) cleaned = cleaned.replace(/^```mermaid\s*/, '');
        if (cleaned.startsWith('```')) cleaned = cleaned.replace(/^```\s*/, '');
        if (cleaned.endsWith('```')) cleaned = cleaned.replace(/```$/, '');
        return cleaned.trim();
    }

    // --------------------------------------------------------------------------
    // 6. Flashcard Interactions
    // --------------------------------------------------------------------------
    function displayFlashcard(index) {
        if (!state.flashcards || state.flashcards.length === 0) return;
        
        elements.activeFlashcard.classList.remove('flipped');
        const card = state.flashcards[index];
        elements.currentCardNum.textContent = index + 1;
        elements.cardTopicFront.textContent = card.topic || 'Concepto';
        elements.cardQuestionText.textContent = card.question || '';
        elements.cardAnswerText.textContent = card.answer || '';
    }

    elements.activeFlashcard.addEventListener('click', () => {
        elements.activeFlashcard.classList.toggle('flipped');
    });

    elements.btnFlipCard.addEventListener('click', () => {
        elements.activeFlashcard.classList.toggle('flipped');
    });

    elements.btnPrevCard.addEventListener('click', () => {
        if (state.currentFlashcardIndex > 0) {
            state.currentFlashcardIndex--;
            displayFlashcard(state.currentFlashcardIndex);
        }
    });

    elements.btnNextCard.addEventListener('click', () => {
        if (state.currentFlashcardIndex < state.flashcards.length - 1) {
            state.currentFlashcardIndex++;
            displayFlashcard(state.currentFlashcardIndex);
        }
    });

    // --------------------------------------------------------------------------
    // 7. Quiz Interactions
    // --------------------------------------------------------------------------
    function renderQuiz(quizList) {
        state.quizAnswers = {};
        state.quizScore = 0;
        elements.quizCountBadge.textContent = quizList.length;
        elements.quizTotalValue.textContent = quizList.length;
        elements.quizScoreBadge.classList.add('hidden');

        if (!quizList || quizList.length === 0) {
            elements.quizContainer.innerHTML = '<p class="text-muted">No se generaron preguntas para este contenido.</p>';
            return;
        }

        const letters = ['A', 'B', 'C', 'D', 'E'];

        elements.quizContainer.innerHTML = quizList.map((q, qIdx) => `
            <div class="quiz-item" data-qidx="${qIdx}">
                <div class="quiz-question-title">
                    <span class="question-num">${qIdx + 1}</span>
                    <span>${escapeHtml(q.question)}</span>
                </div>
                <div class="quiz-options">
                    ${q.options.map((opt, optIdx) => `
                        <div class="quiz-opt" data-optidx="${optIdx}">
                            <span class="quiz-opt-letter">${letters[optIdx] || optIdx}</span>
                            <span>${escapeHtml(opt)}</span>
                        </div>
                    `).join('')}
                </div>
                <div class="quiz-feedback hidden"></div>
            </div>
        `).join('');

        // Attach option click events
        document.querySelectorAll('.quiz-item').forEach(item => {
            const qIdx = parseInt(item.getAttribute('data-qidx'));
            const options = item.querySelectorAll('.quiz-opt');
            const feedback = item.querySelector('.quiz-feedback');
            const questionData = quizList[qIdx];

            options.forEach(opt => {
                opt.addEventListener('click', () => {
                    // Prevent changing answer once answered
                    if (state.quizAnswers[qIdx] !== undefined) return;

                    const selectedOptIdx = parseInt(opt.getAttribute('data-optidx'));
                    state.quizAnswers[qIdx] = selectedOptIdx;

                    const isCorrect = selectedOptIdx === questionData.correct_index;
                    if (isCorrect) state.quizScore++;

                    // Style options
                    options.forEach(o => {
                        const oIdx = parseInt(o.getAttribute('data-optidx'));
                        if (oIdx === questionData.correct_index) {
                            o.classList.add('show-correct');
                        }
                    });

                    opt.classList.add('selected', isCorrect ? 'correct' : 'incorrect');

                    // Show explanation
                    feedback.classList.remove('hidden');
                    feedback.className = `quiz-feedback ${isCorrect ? 'correct' : 'incorrect'}`;
                    feedback.innerHTML = `
                        <strong>${isCorrect ? '¡Correcto!' : 'Respuesta Incorrecta'}</strong><br>
                        ${escapeHtml(questionData.explanation || '')}
                    `;

                    // Update total score badge
                    elements.quizScoreBadge.classList.remove('hidden');
                    elements.quizScoreValue.textContent = state.quizScore;
                });
            });
        });
    }

    elements.btnResetQuiz.addEventListener('click', () => {
        if (state.currentResult && state.currentResult.quiz) {
            renderQuiz(state.currentResult.quiz);
        }
    });

    // --------------------------------------------------------------------------
    // 8. Tabs & Navigation
    // --------------------------------------------------------------------------
    elements.tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-tab');
            elements.tabButtons.forEach(b => b.classList.remove('active'));
            elements.tabPanes.forEach(p => p.classList.remove('active'));

            btn.classList.add('active');
            const targetPane = document.getElementById(targetId);
            if (targetPane) {
                targetPane.classList.add('active');
            }

            // Render diagrams on tab switch if needed
            if (targetId === 'tab-diagram') {
                renderAllMermaidDiagrams();
            }
        });
    });

    elements.btnBackToInput.addEventListener('click', () => {
        switchView('input');
    });

    // Print / PDF Export
    elements.btnExportPdf.addEventListener('click', () => {
        window.print();
    });

    // Copy Markdown
    elements.btnCopyMarkdown.addEventListener('click', () => {
        if (!state.currentResult) return;
        
        let md = `# ${state.currentResult.title || 'Apunte de Estudio'}\n\n`;
        md += `> ${state.currentResult.topic_overview || ''}\n\n`;

        if (state.currentResult.key_takeaways) {
            md += `## Cosas Importantes & Reglas de Oro\n`;
            state.currentResult.key_takeaways.forEach(k => {
                md += `- **${k.title}**: ${k.description}\n`;
            });
            md += `\n`;
        }

        if (state.currentResult.developments) {
            md += `## Desarrollos Temáticos\n\n`;
            state.currentResult.developments.forEach(d => {
                md += `### Unidad ${d.unit_number || ''}: ${d.title}\n\n`;
                md += `${d.content_markdown}\n\n`;
            });
        }

        navigator.clipboard.writeText(md).then(() => {
            showToast('¡Apunte copiado al portapapeles en Markdown!', 'success');
        }).catch(() => {
            showToast('No se pudo copiar el texto.', 'error');
        });
    });

    // --------------------------------------------------------------------------
    // Helpers
    // --------------------------------------------------------------------------
    function escapeHtml(text) {
        if (!text) return '';
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return String(text).replace(/[&<>"']/g, m => map[m]);
    }

    function showToast(msg, type = 'info') {
        elements.toastMsg.textContent = msg;
        elements.toast.className = `toast ${type}`;
        elements.toast.classList.remove('hidden');

        setTimeout(() => {
            elements.toast.classList.add('hidden');
        }, 4000);
    }

});
