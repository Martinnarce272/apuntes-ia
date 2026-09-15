/**
 * ApuntesIA - Application Core JavaScript
 * Handles YouTube & PDF ingestion, Gemini AI interaction,
 * Mermaid.js diagramming, KaTeX formulas, 3D Flashcards, and Quizzes.
 */

document.addEventListener('DOMContentLoaded', () => {
    // State management
    const state = {
        customApiKey: localStorage.getItem('gemini_custom_key') || '',
        hasServerKey: false,
        activeTab: 'tab-notes',
        selectedVideos: [],
        selectedFiles: [],
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

        // Nav & Controls
        geminiStatusChip: document.getElementById('gemini-status-chip'),
        btnOpenKeyModal: document.getElementById('btn-open-key-modal'),
        btnThemeToggle: document.getElementById('btn-theme-toggle'),

        // Key Modal Elements
        modalApiKey: document.getElementById('modal-api-key'),
        btnCloseKeyModal: document.getElementById('btn-close-key-modal'),
        modalKeyStatusDot: document.getElementById('modal-key-status-dot'),
        modalKeyStatusText: document.getElementById('modal-key-status-text'),
        inputCustomKey: document.getElementById('input-custom-key'),
        btnToggleKeyVis: document.getElementById('btn-toggle-key-visibility'),
        btnSaveCustomKey: document.getElementById('btn-save-custom-key'),
        btnClearKey: document.getElementById('btn-clear-key'),

        // Form & Inputs
        generatorForm: document.getElementById('generator-form'),
        youtubeUrl: document.getElementById('youtube-url'),
        btnAddYt: document.getElementById('btn-add-yt'),
        ytCountBadge: document.getElementById('yt-count-badge'),
        ytVideosList: document.getElementById('yt-videos-list'),
        pdfDropzone: document.getElementById('pdf-dropzone'),
        pdfFileInput: document.getElementById('pdf-files'),
        fileList: document.getElementById('file-list'),
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
    // 1. Google Gemini API Status & Key Management
    // --------------------------------------------------------------------------
    function updateGeminiStatusChip() {
        if (!elements.geminiStatusChip) return;
        if (state.customApiKey) {
            elements.geminiStatusChip.innerHTML = `
                <i class="fa-solid fa-bolt" style="color: var(--accent-emerald);"></i>
                <span>Gemini (Key Propia)</span>
                <span class="status-dot active"></span>
            `;
            elements.geminiStatusChip.title = "Usando clave personalizada de Google Gemini";
        } else if (state.hasServerKey) {
            elements.geminiStatusChip.innerHTML = `
                <i class="fa-solid fa-bolt" style="color: var(--accent-emerald);"></i>
                <span>Gemini 3.8 Flash</span>
                <span class="status-dot active"></span>
            `;
            elements.geminiStatusChip.title = "Google Gemini Flash activo en el servidor";
        } else {
            elements.geminiStatusChip.innerHTML = `
                <i class="fa-solid fa-key" style="color: var(--accent-amber);"></i>
                <span>Configurar Gemini Key</span>
                <span class="status-dot warning"></span>
            `;
            elements.geminiStatusChip.title = "Ingresa tu clave gratuita de Google AI Studio";
        }

        updateModalStatusUI();
    }

    function updateModalStatusUI() {
        if (!elements.modalKeyStatusDot || !elements.modalKeyStatusText) return;
        if (state.customApiKey) {
            elements.modalKeyStatusDot.className = 'status-dot active';
            elements.modalKeyStatusText.textContent = 'Clave personalizada activa (guardada localmente).';
        } else if (state.hasServerKey) {
            elements.modalKeyStatusDot.className = 'status-dot active';
            elements.modalKeyStatusText.textContent = 'Clave del servidor (.env) activa y lista para usar.';
        } else {
            elements.modalKeyStatusDot.className = 'status-dot warning';
            elements.modalKeyStatusText.textContent = 'Sin clave configurada. Ingresa una clave gratuita de Google AI Studio abajo.';
        }
    }

    function openKeyModal() {
        if (!elements.modalApiKey) return;
        if (elements.inputCustomKey) {
            elements.inputCustomKey.value = state.customApiKey || '';
        }
        updateModalStatusUI();
        elements.modalApiKey.classList.remove('hidden');
    }

    function closeKeyModal() {
        if (!elements.modalApiKey) return;
        elements.modalApiKey.classList.add('hidden');
    }

    async function checkServerStatus() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            state.hasServerKey = Boolean(data.has_api_key);
            console.log('[Status] Servidor listo. Motor:', data.engine, 'Key en servidor:', state.hasServerKey);
            updateGeminiStatusChip();
        } catch (err) {
            console.warn('[Status] No se pudo verificar estado del servidor:', err);
            updateGeminiStatusChip();
        }
    }

    // Modal wire-up
    if (elements.btnOpenKeyModal) {
        elements.btnOpenKeyModal.addEventListener('click', openKeyModal);
    }
    if (elements.geminiStatusChip) {
        elements.geminiStatusChip.style.cursor = 'pointer';
        elements.geminiStatusChip.addEventListener('click', openKeyModal);
    }
    if (elements.btnCloseKeyModal) {
        elements.btnCloseKeyModal.addEventListener('click', closeKeyModal);
    }
    if (elements.modalApiKey) {
        elements.modalApiKey.addEventListener('click', (e) => {
            if (e.target === elements.modalApiKey) closeKeyModal();
        });
    }

    // Toggle key visibility in modal
    if (elements.btnToggleKeyVis && elements.inputCustomKey) {
        elements.btnToggleKeyVis.addEventListener('click', () => {
            const isPass = elements.inputCustomKey.type === 'password';
            elements.inputCustomKey.type = isPass ? 'text' : 'password';
            const icon = elements.btnToggleKeyVis.querySelector('i');
            if (icon) {
                icon.className = isPass ? 'fa-solid fa-eye-slash' : 'fa-solid fa-eye';
            }
        });
    }

    // Save key
    if (elements.btnSaveCustomKey) {
        elements.btnSaveCustomKey.addEventListener('click', async () => {
            const keyVal = elements.inputCustomKey ? elements.inputCustomKey.value.trim() : '';
            if (!keyVal) {
                showToast("Ingresa una clave válida de Google AI Studio.", "warning");
                return;
            }

            elements.btnSaveCustomKey.disabled = true;
            elements.btnSaveCustomKey.textContent = "Validando...";

            try {
                const res = await fetch('/api/save-key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ apiKey: keyVal })
                });
                const data = await res.json();

                if (data.success) {
                    state.customApiKey = keyVal;
                    localStorage.setItem('gemini_custom_key', keyVal);
                    updateGeminiStatusChip();
                    showToast("¡Clave de Google Gemini validada y guardada!", "success");
                    closeKeyModal();
                } else {
                    showToast(data.error || "Clave no válida. Verifica que pertenezca a Google AI Studio.", "error");
                }
            } catch (e) {
                showToast("Error al verificar la clave con Google.", "error");
            } finally {
                elements.btnSaveCustomKey.disabled = false;
                elements.btnSaveCustomKey.textContent = "Guardar y Activar";
            }
        });
    }

    // Clear key
    if (elements.btnClearKey) {
        elements.btnClearKey.addEventListener('click', () => {
            state.customApiKey = '';
            localStorage.removeItem('gemini_custom_key');
            if (elements.inputCustomKey) elements.inputCustomKey.value = '';
            updateGeminiStatusChip();
            showToast("Clave personalizada eliminada.", "info");
        });
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
                        fallback_thumbnail: data.fallback_thumbnail
                    });
                    addedCount++;
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
            elements.ytVideosList.innerHTML = '';
            return;
        }

        elements.ytCountBadge.textContent = `${count} ${count === 1 ? 'video' : 'videos'}`;
        elements.ytCountBadge.classList.remove('hidden');
        elements.ytVideosList.classList.remove('hidden');

        elements.ytVideosList.innerHTML = state.selectedVideos.map((vid, idx) => `
            <div class="yt-video-item" data-idx="${idx}">
                <img class="yt-video-thumb" src="${escapeHtml(vid.thumbnail)}" alt="Thumbnail" onerror="this.src='${escapeHtml(vid.fallback_thumbnail)}'">
                <div class="yt-video-details">
                    <h4>${escapeHtml(vid.title)}</h4>
                    <div class="yt-video-meta">
                        <span class="badge-order">Parte #${idx + 1}</span>
                        <span>${escapeHtml(vid.author)}</span>
                        <span class="badge-success"><i class="fa-solid fa-check"></i> Listo</span>
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
        if (state.selectedFiles.length === 0) {
            elements.fileList.classList.add('hidden');
            elements.fileList.innerHTML = '';
            return;
        }

        elements.fileList.classList.remove('hidden');
        elements.fileList.innerHTML = state.selectedFiles.map((file, idx) => `
            <div class="file-item">
                <div class="file-name">
                    <i class="fa-solid fa-file-pdf"></i>
                    <span>${escapeHtml(file.name)} (${(file.size / (1024 * 1024)).toFixed(2)} MB)</span>
                </div>
                <button type="button" class="icon-btn remove-file-btn" data-idx="${idx}" title="Eliminar">
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

    // Radio cards UI selection
    document.querySelectorAll('.radio-card').forEach(card => {
        card.addEventListener('click', () => {
            document.querySelectorAll('.radio-card').forEach(c => c.classList.remove('active'));
            card.classList.add('active');
            card.querySelector('input').checked = true;
        });
    });

    // --------------------------------------------------------------------------
    // 3. Form Submission & Generation
    // --------------------------------------------------------------------------
    elements.generatorForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        // If user typed a URL but forgot to click 'Agregar', process it first
        const pendingUrl = elements.youtubeUrl.value.trim();
        if (pendingUrl) {
            await processAndAddYouTubeUrls(pendingUrl);
        }

        const hasVideos = state.selectedVideos.length > 0;
        const hasPdfs = state.selectedFiles.length > 0;

        if (!hasVideos && !hasPdfs) {
            showToast('Por favor agrega al menos un enlace de YouTube o sube un archivo PDF.', 'error');
            return;
        }

        // Si no hay clave configurada en el navegador ni en el servidor, abrir modal
        if (!state.customApiKey && !state.hasServerKey) {
            openKeyModal();
            showToast('Ingresa tu clave gratuita de Google AI Studio para generar apuntes.', 'warning');
            return;
        }

        // Cambiar a vista de carga
        switchView('loading');
        simulateProgress();

        const formData = new FormData();
        state.selectedVideos.forEach(vid => {
            formData.append('youtubeUrls', vid.url);
        });
        formData.append('depth', document.querySelector('input[name="depth"]:checked').value);
        formData.append('instructions', elements.instructionsInput.value.trim());

        state.selectedFiles.forEach(file => {
            formData.append('pdfFiles', file);
        });

        if (state.customApiKey) {
            formData.append('apiKey', state.customApiKey);
        }

        const headers = {};
        if (state.customApiKey) {
            headers['X-Gemini-Api-Key'] = state.customApiKey;
        }

        try {
            // 1. Extracción y generación directa con Google Gemini Flash
            setLoadingStage(1);

            // Transición visual a etapa de generación tras unos segundos
            setTimeout(() => {
                if (currentStage === 1) setLoadingStage(2);
            }, 2000);

            const response = await fetch('/api/generate-notes', {
                method: 'POST',
                headers: headers,
                body: formData
            });

            let backendData;
            const textResponse = await response.text();
            try {
                backendData = JSON.parse(textResponse);
            } catch (jsonErr) {
                console.error('Server returned non-JSON response:', textResponse);
                switchView('input');
                showToast(`El servidor devolvió un error (código ${response.status}). Intenta nuevamente.`, 'error');
                return;
            }

            if (response.status === 401 || backendData.error_code === 'no_api_key') {
                switchView('input');
                openKeyModal();
                showToast(backendData.error || 'Se requiere una clave de Google AI Studio.', 'warning');
                return;
            }

            if (!backendData.success) {
                switchView('input');
                showToast(backendData.error || 'Error al generar el apunte.', 'error');
                return;
            }

            // 2. Estructuración y renderizado
            setLoadingStage(3);

            state.currentResult = backendData.data;
            renderStudyMaterial(backendData.data);
            switchView('results');

            showToast(`¡Apunte generado con éxito usando ${backendData.model_used || 'Google Gemini Flash'}!`, 'success');

        } catch (err) {
            console.error('Error during generation flow:', err);
            switchView('input');
            showToast('Error de comunicación durante la generación. Revisa la consola.', 'error');
        }
    });

    let progressInterval = null;
    let currentStage = 1;
    let progressPct = 10;

    function setLoadingStage(stage) {
        currentStage = stage;
        if (stage === 1) {
            progressPct = Math.max(progressPct, 15);
            elements.step1.className = 'step-item active';
            elements.step2.className = 'step-item';
            elements.step3.className = 'step-item';
            elements.loadingStatusTitle.textContent = 'Extrayendo fuentes...';
            elements.loadingStatusDesc.textContent = 'Leyendo transcripciones de YouTube y texto de PDFs.';
        } else if (stage === 2) {
            progressPct = Math.max(progressPct, 50);
            elements.step1.className = 'step-item completed';
            elements.step2.className = 'step-item active';
            elements.step3.className = 'step-item';
            elements.loadingStatusTitle.textContent = 'Generando apunte con Gemini Flash...';
            elements.loadingStatusDesc.textContent = 'Sintetizando conceptos clave, fórmulas KaTeX y desarrollos pedagógicos.';
        } else if (stage === 3) {
            progressPct = Math.max(progressPct, 92);
            elements.step1.className = 'step-item completed';
            elements.step2.className = 'step-item completed';
            elements.step3.className = 'step-item active';
            elements.loadingStatusTitle.textContent = 'Estructurando resultado...';
            elements.loadingStatusDesc.textContent = 'Organizando post-its, diagramas Mermaid y apunte maestro.';
        }
        if (elements.progressBar) {
            elements.progressBar.style.width = `${progressPct}%`;
        }
    }

    function simulateProgress() {
        progressPct = 10;
        setLoadingStage(1);

        clearInterval(progressInterval);
        progressInterval = setInterval(() => {
            if (currentStage === 1 && progressPct < 45) {
                progressPct += 5;
                elements.progressBar.style.width = `${progressPct}%`;
            } else if (currentStage === 2 && progressPct < 88) {
                progressPct += 2;
                elements.progressBar.style.width = `${progressPct}%`;
            } else if (currentStage === 3 && progressPct < 98) {
                progressPct += 1;
                elements.progressBar.style.width = `${progressPct}%`;
            }
        }, 500);
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

    function formatSeconds(sec) {
        if (typeof sec !== 'number') sec = parseInt(sec) || 0;
        const m = Math.floor(sec / 60);
        const s = sec % 60;
        return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
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
                
                // Parse Markdown with support for ==highlighted text==
                let rawMd = dev.content_markdown || '';
                rawMd = rawMd.replace(/==([^=]+)==/g, '<mark class="hl-yellow">$1</mark>');
                const markdownParsed = marked.parse(rawMd);
                
                // Formulas con desglose de variables ("donde:")
                let formulasHtml = '';
                if (dev.formulas && Array.isArray(dev.formulas) && dev.formulas.length > 0) {
                    formulasHtml = `
                        <div class="unit-formulas-group">
                            ${dev.formulas.map(f => {
                                const latexCode = f.latex || '';
                                const timeLabel = f.timestamp_display ? `[${escapeHtml(f.timestamp_display)}]` : '';
                                let whereHtml = '';
                                if (f.where_variables && Array.isArray(f.where_variables) && f.where_variables.length > 0) {
                                    whereHtml = `
                                        <div class="formula-variables-box">
                                            <div class="where-title"><i class="fa-solid fa-list-check"></i> Donde cada término representa:</div>
                                            <ul class="where-list">
                                                ${f.where_variables.map(w => `<li>${marked.parseInline(w)}</li>`).join('')}
                                            </ul>
                                        </div>
                                    `;
                                }
                                return `
                                    <div class="video-formula-box">
                                        <div class="formula-top-bar">
                                            <span class="formula-badge"><i class="fa-solid fa-square-root-variable"></i> Fórmula ${timeLabel}</span>
                                        </div>
                                        <div class="formula-content math-renderable">
                                            ${latexCode.startsWith('$') ? latexCode : `$$${latexCode}$$`}
                                        </div>
                                        ${f.explanation ? `<p class="formula-explanation">${escapeHtml(f.explanation)}</p>` : ''}
                                        ${whereHtml}
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    `;
                }

                // Callouts & Notas al margen (Estilo Apuntes de Estudio / Post-it)
                let calloutsHtml = '';
                if (dev.callouts && Array.isArray(dev.callouts) && dev.callouts.length > 0) {
                    const calloutIcons = {
                        idea_clave: '<i class="fa-solid fa-lightbulb" style="color:#eab308"></i>',
                        pregunta_examen: '<i class="fa-solid fa-graduation-cap" style="color:#6366f1"></i>',
                        porque: '<i class="fa-solid fa-circle-question" style="color:#06b6d4"></i>',
                        observacion: '<i class="fa-solid fa-triangle-exclamation" style="color:#f59e0b"></i>',
                        tip: '<i class="fa-solid fa-thumbtack" style="color:#eab308"></i>',
                        regla_rapida: '<i class="fa-solid fa-bolt" style="color:#10b981"></i>'
                    };
                    const calloutTitles = {
                        idea_clave: 'Idea clave para entender',
                        pregunta_examen: 'Preguntas de final / examen',
                        porque: '¿Por qué ocurre esto?',
                        observacion: 'Observación y trampa de cálculo',
                        tip: 'Tip / Ayuda al margen',
                        regla_rapida: 'Regla rápida para recordar'
                    };

                    calloutsHtml = `
                        <div class="unit-callouts-container">
                            ${dev.callouts.map(c => {
                                const cType = c.type || 'tip';
                                const icon = calloutIcons[cType] || calloutIcons.tip;
                                const defTitle = calloutTitles[cType] || 'Nota importante';
                                const title = c.title || defTitle;
                                const bodyParsed = marked.parse(c.content || '');
                                return `
                                    <div class="study-callout-card callout-${cType}">
                                        <div class="callout-pin"><i class="fa-solid fa-thumbtack"></i></div>
                                        <div class="callout-header">
                                            ${icon}
                                            <span>${escapeHtml(title)}</span>
                                        </div>
                                        <div class="callout-body math-renderable">
                                            ${bodyParsed}
                                        </div>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    `;
                }

                // Recorte / Momento del Video
                let videoMomentHtml = '';
                const snap = dev.video_snapshot || {};
                const startSec = snap.timestamp_seconds !== undefined ? snap.timestamp_seconds : dev.timestamp_seconds;
                const timeDisplay = snap.timestamp_display || dev.timestamp_display || (startSec !== undefined ? formatSeconds(startSec) : null);
                const snapDesc = snap.description || dev.visual_description || '';
                const videoId = snap.video_id || dev.video_id || (data.sources && data.sources.find(s => s.type === 'youtube')?.id);

                if (videoId && startSec !== undefined && startSec !== null) {
                    videoMomentHtml = `
                        <div class="video-moment-box">
                            <div class="video-moment-header">
                                <span class="video-moment-badge"><i class="fa-solid fa-film"></i> Recorte del Video ${timeDisplay ? `[${escapeHtml(timeDisplay)}]` : ''}</span>
                                ${snapDesc ? `<span class="video-moment-desc">${escapeHtml(snapDesc)}</span>` : ''}
                            </div>
                            <div class="video-crop-player">
                                <iframe src="https://www.youtube-nocookie.com/embed/${videoId}?start=${startSec}&autoplay=0" 
                                        title="Recorte del video en ${timeDisplay || startSec}" 
                                        frameborder="0" 
                                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                                        allowfullscreen loading="lazy"></iframe>
                            </div>
                        </div>
                    `;
                }

                // Optional inline diagram
                let diagramHtml = '';
                if (dev.mermaid_diagram && dev.mermaid_diagram.trim()) {
                    const diagId = `mermaid-dev-${idx}`;
                    diagramHtml = `
                        <div class="unit-diagram-box">
                            <div class="unit-diagram-title"><i class="fa-solid fa-project-diagram"></i> Diagrama Conceptual</div>
                            <div id="${diagId}" class="mermaid-inline-diagram" data-mermaid="${encodeURIComponent(dev.mermaid_diagram)}"></div>
                        </div>
                    `;
                }

                // Visual concept card if no video player
                let visualCardHtml = '';
                if (!videoMomentHtml && dev.visual_description && dev.visual_description.trim()) {
                    visualCardHtml = `
                        <div class="visual-concept-card">
                            <div class="visual-concept-icon"><i class="fa-solid fa-image"></i></div>
                            <div>
                                <h5>Referencia Visual:</h5>
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
                        ${formulasHtml}
                        ${calloutsHtml}
                        ${videoMomentHtml}
                        ${diagramHtml}
                        ${visualCardHtml}
                    </div>
                `;
            }).join('');
        }

        // 3. Exam Tips (si existen en el DOM)
        if (elements.examTipsList) {
            if (data.exam_tips && data.exam_tips.length > 0) {
                elements.examTipsList.innerHTML = data.exam_tips.map(tip => `
                    <div class="exam-tip-item">
                        <i class="fa-solid fa-crosshairs"></i>
                        <p>${escapeHtml(tip)}</p>
                    </div>
                `).join('');
                const section = elements.examTipsList.closest('.study-section');
                if (section) section.style.display = 'block';
            } else {
                const section = elements.examTipsList.closest('.study-section');
                if (section) section.style.display = 'none';
            }
        }

        // 4. Glossary (si existe en el DOM)
        if (elements.glossaryGrid) {
            if (data.glossary && data.glossary.length > 0) {
                elements.glossaryGrid.innerHTML = data.glossary.map(item => `
                    <div class="glossary-item">
                        <dt>${escapeHtml(item.term)}</dt>
                        <dd>${escapeHtml(item.definition)}</dd>
                    </div>
                `).join('');
                const section = elements.glossaryGrid.closest('.study-section');
                if (section) section.style.display = 'block';
            } else {
                const section = elements.glossaryGrid.closest('.study-section');
                if (section) section.style.display = 'none';
            }
        }

        // Render Math (KaTeX) in the document
        if (window.renderMathInElement && elements.developmentsContainer) {
            renderMathInElement(elements.developmentsContainer, {
                delimiters: [
                    { left: '$$', right: '$$', display: true },
                    { left: '$', right: '$', display: false }
                ],
                throwOnError: false
            });
        }

        // 5. Flashcards (opcional / omitido)
        if (elements.flashcardsCountBadge && elements.activeFlashcard) {
            state.flashcards = data.flashcards || [];
            state.currentFlashcardIndex = 0;
            elements.flashcardsCountBadge.textContent = state.flashcards.length;
            if (elements.totalCardsNum) elements.totalCardsNum.textContent = state.flashcards.length;
            if (state.flashcards.length > 0) {
                displayFlashcard(0);
            }
        }

        // 6. Quiz (opcional / omitido)
        if (elements.quizContainer) {
            renderQuiz(data.quiz || []);
        }

        // 7. Global Diagram (Integrado en el apunte)
        const diagSection = document.getElementById('integrated-diagram-section');
        if (data.general_diagram && data.general_diagram.mermaid_code) {
            if (diagSection) diagSection.classList.remove('hidden');
            if (elements.diagramTitle) elements.diagramTitle.textContent = data.general_diagram.title || 'Mapa Conceptual Global';
            if (elements.mermaidGlobalContainer) {
                elements.mermaidGlobalContainer.setAttribute('data-mermaid', encodeURIComponent(data.general_diagram.mermaid_code));
            }
        } else {
            if (diagSection) diagSection.classList.add('hidden');
            if (elements.mermaidGlobalContainer) {
                elements.mermaidGlobalContainer.innerHTML = '';
            }
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
        if (!elements.activeFlashcard || !state.flashcards || state.flashcards.length === 0) return;
        
        elements.activeFlashcard.classList.remove('flipped');
        const card = state.flashcards[index];
        if (elements.currentCardNum) elements.currentCardNum.textContent = index + 1;
        if (elements.cardTopicFront) elements.cardTopicFront.textContent = card.topic || 'Concepto';
        if (elements.cardQuestionText) elements.cardQuestionText.textContent = card.question || '';
        if (elements.cardAnswerText) elements.cardAnswerText.textContent = card.answer || '';
    }

    if (elements.activeFlashcard) {
        elements.activeFlashcard.addEventListener('click', () => {
            elements.activeFlashcard.classList.toggle('flipped');
        });
    }

    if (elements.btnFlipCard) {
        elements.btnFlipCard.addEventListener('click', () => {
            if (elements.activeFlashcard) elements.activeFlashcard.classList.toggle('flipped');
        });
    }

    if (elements.btnPrevCard) {
        elements.btnPrevCard.addEventListener('click', () => {
            if (state.currentFlashcardIndex > 0) {
                state.currentFlashcardIndex--;
                displayFlashcard(state.currentFlashcardIndex);
            }
        });
    }

    if (elements.btnNextCard) {
        elements.btnNextCard.addEventListener('click', () => {
            if (state.currentFlashcardIndex < state.flashcards.length - 1) {
                state.currentFlashcardIndex++;
                displayFlashcard(state.currentFlashcardIndex);
            }
        });
    }

    // --------------------------------------------------------------------------
    // 7. Quiz Interactions
    // --------------------------------------------------------------------------
    function renderQuiz(quizList) {
        if (!elements.quizContainer) return;

        state.quizAnswers = {};
        state.quizScore = 0;
        if (elements.quizCountBadge) elements.quizCountBadge.textContent = quizList.length;
        if (elements.quizTotalValue) elements.quizTotalValue.textContent = quizList.length;
        if (elements.quizScoreBadge) elements.quizScoreBadge.classList.add('hidden');

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
                    if (feedback) {
                        feedback.classList.remove('hidden');
                        feedback.className = `quiz-feedback ${isCorrect ? 'correct' : 'incorrect'}`;
                        feedback.innerHTML = `
                            <strong>${isCorrect ? '¡Correcto!' : 'Respuesta Incorrecta'}</strong><br>
                            ${escapeHtml(questionData.explanation || '')}
                        `;
                    }

                    // Update total score badge
                    if (elements.quizScoreBadge && elements.quizScoreValue) {
                        elements.quizScoreBadge.classList.remove('hidden');
                        elements.quizScoreValue.textContent = state.quizScore;
                    }
                });
            });
        });
    }

    if (elements.btnResetQuiz) {
        elements.btnResetQuiz.addEventListener('click', () => {
            if (state.currentResult && state.currentResult.quiz) {
                renderQuiz(state.currentResult.quiz);
            }
        });
    }

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

    // Startup check
    checkServerStatus();
});
