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
            "news": "1. Chasse aux Intox: Collez l'article ou le lien pour révéler le faux :",
            "myth": "2. Déboulonneur de Mythes: Collez le remède miracle ou la pseudo-science :",
            "identity_spoofing": "3. Détecteur de Posture: Collez le profil ou la bio pour auditer la façade :",
            "coercion": "4. Filtre Anti-Blabla: Collez le discours de vente à haute pression ou la manipulation :"
        },
        windowPlaceholders: {
            "news": "Collez du texte média, des articles politiques ou des liens vidéo...",
            "myth": "Collez des affirmations sur la médecine alternative ou des théories non vérifiées...",
            "identity_spoofing": "Collez des données de bio ou des identifiants de 'gourous' suspects...",
            "coercion": "Collez des discours de vente agressive ou de la manipulation..."
        }
    },
    es: {
        windowTitles: {
            "news": "1. Cazador de Bulos: Pega el artículo, titular o enlace para destapar la mentira:",
            "myth": "2. Rompe-Mitos: Pega el remedio mágico, la conspiración o la ciencia de garrafa:",
            "identity_spoofing": "3. Detector de Postureo: Pega el perfil o bio del gurú para auditar la fachada:",
            "coercion": "4. Filtro Vendehumos: Pega la chapa persuasiva o el discurso de alta presión:"
        },
        windowPlaceholders: {
            "news": "Pega texto de prensa, titulares dudosos o enlaces de vídeo para auditarlos...",
            "myth": "Pega afirmaciones sobre medicina alternativa, brebajes o teorías de conspiración...",
            "identity_spoofing": "Pega biografías de LinkedIn, cargos de fantasía o credenciales sospechosas...",
            "coercion": "Pega discursos de ventas agresivas, manipulación o 'chapas' de alta presión..."
        }
    },
    en: {
        windowTitles: {
            "news": "1. FakeNews Hunter: Paste the article or link to expose the spin:",
            "myth": "2. Myth-Buster: Paste the miracle cure, pseudoscience, or wild theory:",
            "identity_spoofing": "3. Clout & Posture Audit: Paste the bio or profile to scan for fake credentials:",
            "coercion": "4. Hype & Coercion Filter: Paste the high-pressure pitch or manipulative talk:"
        },
        windowPlaceholders: {
            "news": "Paste media text, political spin, or video links to audit...",
            "myth": "Paste claims regarding alternative remedies or unverified theories...",
            "identity_spoofing": "Paste suspicious bio data, inflated titles, or guru credentials...",
            "coercion": "Paste high-pressure sales pitches, manipulation, or aggressive discourse..."
        }
    }
};

document.addEventListener("DOMContentLoaded", () => {
    setupNavTabs();
    setupFileInput();
    setupLangSelector();
    
    // Aplicar el idioma guardado previamente tan pronto como la página cargue
    switchLanguage(currentLang);
});

// 2. CONEXIÓN CON EL SELECTOR DE IDIOMAS DE LA CABECERA
function setupLangSelector() {
    const btnFr = document.getElementById("btn-fr");
    const btnEs = document.getElementById("btn-es");
    const btnEn = document.getElementById("btn-en");

    if (btnFr) btnFr.addEventListener("click", (e) => { e.preventDefault(); switchLanguage("fr"); });
    if (btnEs) btnEs.addEventListener("click", (e) => { e.preventDefault(); switchLanguage("es"); });
    if (btnEn) btnEn.addEventListener("click", (e) => { e.preventDefault(); switchLanguage("en"); });
}

function switchLanguage(lang) {
    if (!i18n[lang]) lang = "fr";
    currentLang = lang;

    // Guardar preferencia global y actualizar atributo lang del documento HTML
    localStorage.setItem('preferred_lang', lang);
    document.documentElement.lang = lang;

    // Actualizar clases activas en los botones de idioma
    document.querySelectorAll(".lang-btn").forEach(btn => btn.classList.remove("active"));
    const activeBtn = document.getElementById(`btn-${lang}`);
    if (activeBtn) activeBtn.classList.add("active");

    // Actualizar dinámicamente los textos visibles de los módulos
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

function setupNavTabs() {
    document.querySelectorAll(".nav-tabs button").forEach(button => {
        button.addEventListener("click", () => {
            const windowType = button.dataset.module;
            if (!windowType) return;

            document.querySelectorAll(".nav-tabs button").forEach(btn => btn.classList.remove("active"));
            button.classList.add("active");
            currentWindow = windowType;

            updateModuleTexts();
        });
    });
}

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

// 3. MAPEO DE PUNTUACIÓN INTERNA (0-100) A SOLAMENTE LETRAS (A, B, C, D)
function getEthicLetter(score) {
    if (score <= 25) return "A"; // Sin Riesgo / Integridad Alta
    if (score <= 50) return "B"; // Riesgo Moderado
    if (score <= 75) return "C"; // Riesgo Alto
    return "D";                  // Peligro Máximo / Coerción
}

// 4. FUNCIÓN PRINCIPAL DE ANÁLISIS
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

        // Enviamos el idioma actual en las peticiones al backend
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

        // APLICAR CLASES DE COLOR SEGÚN LA LETRA DE AMENAZA
        const resultsSection = document.getElementById("results-panel");
        if (resultsSection) {
            resultsSection.className = 'results-section';

            if (score >= 76) {
                resultsSection.classList.add("threat-high");    // Letra D (Rojo)
            } else if (score >= 51) {
                resultsSection.classList.add("threat-medium");  // Letra C (Naranja)
            } else if (score >= 26) {
                resultsSection.classList.add("threat-caution"); // Letra B (Amarillo)
            } else {
                resultsSection.classList.add("threat-low");     // Letra A (Verde)
            }
        }

        // IMPRIME EXCLUSIVAMENTE LA LETRA (Sin cifras ni puntuación)
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

// 5. EXPORTAR PDF
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

// 6. PURGAR DASHBOARD
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
