const API_BASE_URL = "https://polethic-beacon-api.onrender.com";

let currentWindow = "news";
let lastAnalyzedModule = "news";
let lastScore = 0; // Se mantiene en memoria como número para el backend/PDF

// Detectar idioma inicial (Prioridad: URL -> localStorage -> por defecto 'fr')
const urlParams = new URLSearchParams(window.location.search);
let currentLang = urlParams.get('lang') || localStorage.getItem('preferred_lang') || "fr";

// 1. DICCIONARIO DE TRADUCCIONES PARA EL DASHBOARD Y NAVEGACIÓN
const i18n = {
    fr: {
        windowTitles: {
            "news": "1. FakeNews: Entrez le texte de l'article ou le lien à évaluer :",
            "myth": "2. Myth-Buster: Collez la déclaration, le remède ou la théorie pseudoscientifique :",
            "identity_spoofing": "3. Identity Spoofing: Collez le profil, les identifiants ou la bio à auditer :",
            "coercion": "4. Filtre Coercitif: Entrez le texte persuasif ou le discours suspect :"
        },
        windowPlaceholders: {
            "news": "Collez du texte média, des articles politiques ou des liens vidéo...",
            "myth": "Collez des affirmations sur la médecine alternative ou des théories non vérifiées...",
            "identity_spoofing": "Collez des données de bio ou des identifiants suspects...",
            "coercion": "Collez des discours de vente à haute pression ou de la manipulation..."
        },
        ethicLabel: "Ethic-Score™",
        runningText: "Analyse des motifs linguistiques en cours... Veuillez patienter.",
        emptyText: "Veuillez introduire du contenu ou joindre une image à analyser.",
        systemOffline: "Erreur: Système Hors Ligne",
        offlineReport: "Le cœur de Beacon est actuellement inaccessible. Vérifiez votre connexion ou l'état du serveur.",
        parsingError: "Indisponible (erreur d'analyse)"
    },
    es: {
        windowTitles: {
            "news": "1. FakeNews: Introduce el texto o enlace del artículo a evaluar:",
            "myth": "2. Myth-Buster: Pega la afirmación, remedio o teoría seudocientífica:",
            "identity_spoofing": "3. Identity Spoofing: Pega el perfil o biografía para auditar:",
            "coercion": "4. Filtro Coercitivo: Introduce el texto persuasivo o discurso sospechoso:"
        },
        windowPlaceholders: {
            "news": "Pega texto de prensa, artículos políticos o enlaces de vídeo para auditarlo...",
            "myth": "Pega afirmaciones sobre medicina alternativa o teorías no verificadas...",
            "identity_spoofing": "Pega biografías o credenciales sospechosas para analizar intrusión profesional...",
            "coercion": "Pega discursos de alta presión, manipulación o ventas agresivas..."
        },
        ethicLabel: "Ethic-Score™",
        runningText: "Ejecutando análisis de patrones lingüísticos... Por favor, espera.",
        emptyText: "Por favor, introduce algún contenido o adjunta una imagen para analizar.",
        systemOffline: "Error: Sistema Fuera de Línea",
        offlineReport: "El núcleo de Beacon no está localizable. Verifica tu conexión o el servidor.",
        parsingError: "No disponible (error de análisis)"
    },
    en: {
        windowTitles: {
            "news": "1. FakeNews: Enter the article text or link to evaluate:",
            "myth": "2. Myth-Buster: Paste the claim, remedy, or pseudoscientific theory:",
            "identity_spoofing": "3. Identity Spoofing: Paste the profile, credentials, or bio to audit:",
            "coercion": "4. Coercive Filter: Enter the persuasive text or suspicious discourse:"
        },
        windowPlaceholders: {
            "news": "Paste media text, political articles, or video links to Beacon-ize it...",
            "myth": "Paste claims regarding alternative medicine or unverified theories to Beacon-ize it...",
            "identity_spoofing": "Paste suspicious bio data or credentials to audit for structural/professional intrusion...",
            "coercion": "Paste high-pressure sales pitches to Beacon-ize it..."
        },
        ethicLabel: "Ethic-Score™",
        runningText: "Running linguistic pattern analysis... Please wait.",
        emptyText: "Please introduce some content or attach an image to Beacon-ize.",
        systemOffline: "Error: System Offline",
        offlineReport: "The Beacon core is currently unreachable. Please verify your connection or server status.",
        parsingError: "Unavailable (parsing error)"
    }
};

document.addEventListener("DOMContentLoaded", () => {
    // Inicializar listeners de interacción y navegación
    setupNavTabs();
    setupFileInput();
    setupLangSelector();
    setupActionButtons(); // Conecta BEACON-IZE, EXPORT PDF y PURGE
    
    // Carga inicial de idioma respetando URL o almacenamiento local
    switchLanguage(currentLang);
});

// 2. CONEXIÓN DE LOS BOTONES DE ACCIÓN (BEACON-IZE, PDF, PURGAR)
function setupActionButtons() {
    const btnAnalyze = document.getElementById("btn-analyze");
    if (btnAnalyze) {
        btnAnalyze.addEventListener("click", (e) => {
            e.preventDefault();
            analyze();
        });
    }

    const btnPdf = document.getElementById("btn-pdf");
    if (btnPdf) {
        btnPdf.addEventListener("click", (e) => {
            e.preventDefault();
            triggerPDFDownload();
        });
    }

    const btnPurge = document.getElementById("btn-purge");
    if (btnPurge) {
        btnPurge.addEventListener("click", (e) => {
            e.preventDefault();
            purgeDashboard();
        });
    }
}

// 3. CONEXIÓN CON EL SELECTOR DE IDIOMAS Y SINCRONIZACIÓN DE URL
function setupLangSelector() {
    const btnFr = document.getElementById("btn-fr");
    const btnEs = document.getElementById("btn-es");
    const btnEn = document.getElementById("btn-en");

    if (btnFr) btnFr.addEventListener("click", (e) => { e.preventDefault(); switchLanguage("fr"); });
    if (btnEs) btnEs.addEventListener("click", (e) => { e.preventDefault(); switchLanguage("es"); });
    if (btnEn) btnEn.addEventListener("click", (e) => { e.preventDefault(); switchLanguage("en"); });
}

function switchLanguage(lang) {
    if (!i18n[lang]) return;
    currentLang = lang;

    localStorage.setItem('preferred_lang', lang);
    document.documentElement.lang = lang;

    document.querySelectorAll(".lang-btn").forEach(btn => btn.classList.remove("active"));
    const activeBtn = document.getElementById(`btn-${lang}`);
    if (activeBtn) activeBtn.classList.add("active");

    // Sincronizar URL ?lang=xx sin refrescar la página
    const newUrl = `${window.location.pathname}?lang=${lang}`;
    window.history.replaceState({ path: newUrl }, '', newUrl);

    updateModuleTexts();
}

function updateModuleTexts() {
    const t = i18n[currentLang];
    
    const titleEl = document.getElementById("window-title");
    if (titleEl && t.windowTitles[currentWindow]) {
        titleEl.innerText = t.windowTitles[currentWindow];
    }

    const inputEl = document.getElementById("user-input");
    if (inputEl && t.windowPlaceholders[currentWindow]) {
        inputEl.placeholder = t.windowPlaceholders[currentWindow];
    }
}

// 4. NAVEGACIÓN ENTRE LOS 4 BOTONES / MÓDULOS
function setupNavTabs() {
    const buttons = document.querySelectorAll(".nav-tabs button");
    buttons.forEach(button => {
        button.addEventListener("click", () => {
            const windowType = button.dataset.module;
            if (!windowType) return;

            buttons.forEach(btn => btn.classList.remove("active"));
            button.classList.add("active");
            currentWindow = windowType;

            updateModuleTexts();
        });
    });
}

// 5. GESTIÓN DEL INPUT DE IMAGEN/CÁMARA A LA IZQUIERDA
function setupFileInput() {
    const fileInput = document.getElementById("user-file");
    const fileNameDisplay = document.getElementById("file-name-display");
    if (!fileInput) return;

    fileInput.addEventListener("change", () => {
        if (fileInput.files && fileInput.files.length > 0) {
            if (fileNameDisplay) fileNameDisplay.innerText = `📎 ${fileInput.files[0].name}`;
        } else {
            if (fileNameDisplay) fileNameDisplay.innerText = "";
        }
    });
}

function renderReport(resultDiv, verdictText) {
    resultDiv.innerHTML = "";
    const lines = verdictText.split("\n");
    lines.forEach((line, index) => {
        resultDiv.appendChild(document.createTextNode(line));
        if (index < lines.length - 1) {
            resultDiv.appendChild(document.createElement("br"));
        }
    });
}

function renderLocalFlags(flags) {
    const container = document.getElementById("local-flags-container");
    if (!container) return;
    container.innerHTML = "";
    if (flags && flags.length > 0) {
        flags.forEach(flag => {
            const badge = document.createElement("span");
            badge.className = "flag-badge";
            badge.innerText = flag;
            container.appendChild(badge);
        });
    }
}

// 6. MAPEO DE PUNTUACIÓN INTERNA A SOLAMENTE LETRAS (A, B, C, D)
function getEthicLetter(score) {
    if (score <= 25) return "A"; // Sin Riesgo / Integridad Alta
    if (score <= 50) return "B"; // Riesgo Moderado
    if (score <= 75) return "C"; // Riesgo Alto
    return "D";                  // Peligro Máximo / Coerción
}

// 7. FUNCIÓN PRINCIPAL DE ANÁLISIS (BEACON-IZE)
async function analyze() {
    const t = i18n[currentLang];
    const textInput = document.getElementById("user-input").value.trim();
    const fileInput = document.getElementById("user-file");
    const file = fileInput && fileInput.files.length > 0 ? fileInput.files[0] : null;

    const scoreDiv = document.getElementById("ethic-score");
    const resultDiv = document.getElementById("analysis-report");
    const analyzeButton = document.getElementById("btn-analyze");

    if (!textInput && !file) {
        if (resultDiv) resultDiv.innerText = t.emptyText;
        return;
    }

    if (analyzeButton) {
        analyzeButton.innerText = "...";
        analyzeButton.disabled = true;
    }
    if (scoreDiv) {
        scoreDiv.innerText = `${t.ethicLabel}: --`;
    }
    if (resultDiv) {
        resultDiv.innerText = t.runningText;
    }

    try {
        let response;

        if (file) {
            const formData = new FormData();
            formData.append("text", textInput);
            formData.append("module", currentWindow);
            formData.append("lang", currentLang); 
            formData.append("file", file);

            response = await fetch(`${API_BASE_URL}/analyze`, {
                method: "POST",
                body: formData
            });
        } else {
            response = await fetch(`${API_BASE_URL}/analyze`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: textInput, module: currentWindow, lang: currentLang })
            });
        }

        if (!response.ok) {
            throw new Error("Server communication failure");
        }

        const data = await response.json();

        if (data.score === null || data.score === undefined) {
            lastAnalyzedModule = currentWindow;
            lastScore = 0;

            const resultsSection = document.getElementById("results-panel");
            if (resultsSection) resultsSection.className = 'results-section';

            if (scoreDiv) scoreDiv.innerText = `${t.ethicLabel}: ${t.parsingError}`;
            if (resultDiv && data.analysis) renderReport(resultDiv, data.analysis);
            renderLocalFlags(data.local_flags);

            return;
        }

        const parsedScore = parseInt(data.score, 10);
        const score = Number.isNaN(parsedScore) ? 0 : parsedScore;

        lastAnalyzedModule = currentWindow;
        lastScore = score;

        const resultsSection = document.getElementById("results-panel");
        if (resultsSection) {
            resultsSection.className = 'results-section';

            if (score >= 76) {
                resultsSection.classList.add("threat-high");    // D (Rojo)
            } else if (score >= 51) {
                resultsSection.classList.add("threat-medium");  // C (Naranja)
            } else if (score >= 26) {
                resultsSection.classList.add("threat-caution"); // B (Amarillo)
            } else {
                resultsSection.classList.add("threat-low");     // A (Verde)
            }
        }

        if (scoreDiv) {
            scoreDiv.innerText = `${t.ethicLabel}: ${getEthicLetter(score)}`;
        }

        if (resultDiv && data.analysis) {
            renderReport(resultDiv, data.analysis);
        }

        renderLocalFlags(data.local_flags);

    } catch (error) {
        console.error(error);
        if (scoreDiv) scoreDiv.innerText = t.systemOffline;
        if (resultDiv) resultDiv.innerText = t.offlineReport;
    } finally {
        if (analyzeButton) {
            analyzeButton.innerText = "BEACON-IZE";
            analyzeButton.disabled = false;
        }
    }
}

// 8. EXPORTAR A PDF
function triggerPDFDownload() {
    const analysisElement = document.getElementById("analysis-report");
    const currentAnalysis = analysisElement ? analysisElement.innerText.trim() : "No analysis target found.";
    const pdfButton = document.getElementById("btn-pdf");

    if (pdfButton) {
        pdfButton.innerText = "EXPORTING...";
        pdfButton.disabled = true;
    }

    fetch(`${API_BASE_URL}/export_pdf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            score: lastScore,
            analysis: currentAnalysis,
            module: lastAnalyzedModule,
            lang: currentLang
        })
    })
    .then(response => {
        if (!response.ok) throw new Error(`PDF server route failed (status ${response.status})`);
        return response.blob();
    })
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'Polethic_Beacon_Report.pdf';
        document.body.appendChild(a);
        a.click();
        a.remove();
    })
    .catch(err => {
        console.error("Error triggering PDF:", err);
        alert("PDF export failed: " + err.message);
    })
    .finally(() => {
        if (pdfButton) {
            pdfButton.innerText = "EXPORT PDF";
            pdfButton.disabled = false;
        }
    });
}

// 9. REINICIAR Y PURGAR EL DASHBOARD
function purgeDashboard() {
    const textInput = document.getElementById("user-input");
    if (textInput) textInput.value = "";

    const fileInput = document.getElementById("user-file");
    if (fileInput) fileInput.value = "";

    const fileNameDisplay = document.getElementById("file-name-display");
    if (fileNameDisplay) fileNameDisplay.innerText = "";

    const scoreElement = document.getElementById("ethic-score");
    if (scoreElement) {
        scoreElement.innerText = `${i18n[currentLang].ethicLabel}: --`;
    }
    lastScore = 0;

    const analysisElement = document.getElementById("analysis-report");
    if (analysisElement) analysisElement.innerText = "...";

    renderLocalFlags([]);

    const resultsSection = document.getElementById("results-panel");
    if (resultsSection) {
        resultsSection.className = 'results-section';
    }
}
