const API_BASE_URL = "https://polethic-beacon-api.onrender.com";

let lastScore = 0;
let lastAnalysisText = "";

const urlParams = new URLSearchParams(window.location.search);
let currentLang = urlParams.get('lang') || localStorage.getItem('preferred_lang') || "fr";

// DICCIONARIO DE TRADUCCIONES
const i18n = {
    fr: {
        windowTitle: "Collez le texte, le lien ou joignez une image à évaluer :",
        placeholder: "Collez du texte média, des déclarations, des théories, des bios ou des liens...",
        btnAnalyze: "BEACON-ISER",
        btnRefute: "🔄 REFUTER / CHALLENGER",
        btnPdf: "EXPORTER EN PDF",
        btnPurge: "PURGER",
        ethicLabel: "Ethic-Score™",
        runningText: "Analyse des motifs linguistiques et des biais en cours... Veuillez patienter.",
        emptyText: "Veuillez introduire du contenu ou joindre une image à analyser.",
        systemOffline: "Erreur: Système Hors Ligne",
        offlineReport: "Le cœur de Beacon est actuellement inaccessible. Vérifiez votre connexion.",
        flags: {
            fakenews: "FakeNews",
            myth: "Chasseur de Mythes",
            posturing: "Postureur / Titres Inflés",
            coercion: "Vente d'Ombre / Coercition"
        }
    },
    es: {
        windowTitle: "Introduce el texto, enlace o adjunta una imagen a evaluar:",
        placeholder: "Pega texto de prensa, afirmaciones, teorías, biografías, ventas agresivas o enlaces...",
        btnAnalyze: "ANALIZAR (BEACON-IZE)",
        btnRefute: "🔄 REFUTAR / DESAFIAR SESGO",
        btnPdf: "EXPORTAR PDF DE DEFENSA",
        btnPurge: "PURGAR",
        ethicLabel: "Ethic-Score™",
        runningText: "Ejecutando análisis de patrones lingüísticos y sesgos... Calculando carga de la prueba.",
        emptyText: "Por favor, introduce algún contenido o adjunta una imagen para analizar.",
        systemOffline: "Error: Sistema Fuera de Línea",
        offlineReport: "El núcleo de Beacon no está disponible. Verifica la conexión.",
        flags: {
            fakenews: "FakeNews",
            myth: "Cazador de Mitos",
            posturing: "Postureo y Credenciales",
            coercion: "Venta de Humo / Coerción"
        }
    },
    en: {
        windowTitle: "Enter the text, link or attach an image to evaluate:",
        placeholder: "Paste media text, claims, theories, bios, high-pressure sales or links...",
        btnAnalyze: "BEACON-IZE",
        btnRefute: "🔄 REFUTE / CHALLENGE BIAS",
        btnPdf: "EXPORT DEFENSE PDF",
        btnPurge: "PURGE",
        ethicLabel: "Ethic-Score™",
        runningText: "Running linguistic pattern and bias analysis... Calculating burden of proof.",
        emptyText: "Please introduce some content or attach an image to Beacon-ize.",
        systemOffline: "Error: System Offline",
        offlineReport: "The Beacon core is currently unreachable.",
        flags: {
            fakenews: "FakeNews",
            myth: "Myth-Buster",
            posturing: "Titles & Posturing",
            coercion: "Smoke & Coercion"
        }
    }
};

document.addEventListener("DOMContentLoaded", () => {
    setupFileInput();
    setupLangSelector();
    setupActionButtons();
    switchLanguage(currentLang);
});

function setupActionButtons() {
    const btnAnalyze = document.getElementById("btn-analyze");
    if (btnAnalyze) btnAnalyze.addEventListener("click", (e) => { e.preventDefault(); analyze(); });

    const btnRefute = document.getElementById("btn-refute");
    if (btnRefute) btnRefute.addEventListener("click", (e) => { e.preventDefault(); generateRefutation(); });

    const btnPdf = document.getElementById("btn-pdf");
    if (btnPdf) btnPdf.addEventListener("click", (e) => { e.preventDefault(); triggerPDFDownload(); });

    const btnPurge = document.getElementById("btn-purge");
    if (btnPurge) btnPurge.addEventListener("click", (e) => { e.preventDefault(); purgeDashboard(); });
}

function setupLangSelector() {
    ["fr", "es", "en"].forEach(lang => {
        const btn = document.getElementById(`btn-${lang}`);
        if (btn) btn.addEventListener("click", (e) => { e.preventDefault(); switchLanguage(lang); });
    });
}

function switchLanguage(lang) {
    if (!i18n[lang]) return;
    currentLang = lang;
    localStorage.setItem('preferred_lang', lang);
    document.documentElement.lang = lang;

    document.querySelectorAll(".lang-btn").forEach(btn => btn.classList.remove("active"));
    const activeBtn = document.getElementById(`btn-${lang}`);
    if (activeBtn) activeBtn.classList.add("active");

    updateTexts();
}

function updateTexts() {
    const t = i18n[currentLang];

    const titleEl = document.getElementById("window-title");
    if (titleEl) titleEl.innerText = t.windowTitle;

    const inputEl = document.getElementById("user-input");
    if (inputEl) inputEl.placeholder = t.placeholder;

    if (document.getElementById("btn-analyze")) document.getElementById("btn-analyze").innerText = t.btnAnalyze;
    if (document.getElementById("btn-refute")) document.getElementById("btn-refute").innerText = t.btnRefute;
    if (document.getElementById("btn-pdf")) document.getElementById("btn-pdf").innerText = t.btnPdf;
    if (document.getElementById("btn-purge")) document.getElementById("btn-purge").innerText = t.btnPurge;
}

function setupFileInput() {
    const fileInput = document.getElementById("user-file");
    const fileNameDisplay = document.getElementById("file-name-display");
    if (!fileInput) return;

    fileInput.addEventListener("change", () => {
        if (fileInput.files && fileInput.files.length > 0) {
            if (fileNameDisplay) fileNameDisplay.innerText = `📷 ${fileInput.files[0].name}`;
        } else {
            if (fileNameDisplay) fileNameDisplay.innerText = "";
        }
    });
}

function getEthicLetter(score) {
    if (score <= 25) return "A";
    if (score <= 50) return "B";
    if (score <= 75) return "C";
    return "D";
}

// RENDERIZADO DINÁMICO DE LOS 4 BOTONES/CATEGORÍAS TRAS EL ANÁLISIS
function renderDetectedFlags(flags) {
    const container = document.getElementById("detected-flags-container");
    if (!container) return;
    container.innerHTML = "";

    const t = i18n[currentLang].flags;

    // Mapeo de banderas recibidas del backend
    if (flags && flags.length > 0) {
        flags.forEach(flag => {
            const badge = document.createElement("span");
            badge.className = `flag-badge flag-${flag}`; // CSS para dar color específico
            badge.innerText = t[flag] || flag;
            container.appendChild(badge);
        });
    }
}

// ANÁLISIS AUTOMÁTICO
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

    if (analyzeButton) analyzeButton.disabled = true;
    if (scoreDiv) scoreDiv.innerText = `${t.ethicLabel}: --`;
    if (resultDiv) resultDiv.innerText = t.runningText;

    try {
        let response;
        if (file) {
            const formData = new FormData();
            formData.append("text", textInput);
            formData.append("lang", currentLang); 
            formData.append("file", file);
            response = await fetch(`${API_BASE_URL}/analyze`, { method: "POST", body: formData });
        } else {
            response = await fetch(`${API_BASE_URL}/analyze`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: textInput, lang: currentLang })
            });
        }

        const data = await response.json();
        const score = parseInt(data.score, 10) || 0;
        lastScore = score;
        lastAnalysisText = data.analysis;

        // Actualizar panel visual
        const resultsSection = document.getElementById("results-panel");
        if (resultsSection) {
            resultsSection.style.display = "block"; // Se despliega el panel de resultados
            resultsSection.className = 'results-section';
            if (score >= 76) resultsSection.classList.add("threat-high");
            else if (score >= 51) resultsSection.classList.add("threat-medium");
            else if (score >= 26) resultsSection.classList.add("threat-caution");
            else resultsSection.classList.add("threat-low");
        }

        if (scoreDiv) scoreDiv.innerText = `${t.ethicLabel}: ${getEthicLetter(score)}`;
        if (resultDiv) resultDiv.innerText = data.analysis;

        // Renderiza los 4 botones/categorías según lo detectado
        renderDetectedFlags(data.detected_flags || []);

    } catch (error) {
        console.error(error);
        if (scoreDiv) scoreDiv.innerText = t.systemOffline;
        if (resultDiv) resultDiv.innerText = t.offlineReport;
    } finally {
        if (analyzeButton) analyzeButton.disabled = false;
    }
}

// REFUTACIÓN Y DESAFÍO DE SESGO
async function generateRefutation() {
    const resultDiv = document.getElementById("analysis-report");
    const btnRefute = document.getElementById("btn-refute");

    if (!lastAnalysisText) return;

    if (btnRefute) btnRefute.disabled = true;
    resultDiv.innerText = "⚽ Calculando contra-argumentación y preguntas para invertir la carga de la prueba...";

    try {
        const response = await fetch(`${API_BASE_URL}/refute`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ analysis: lastAnalysisText, lang: currentLang })
        });

        if (response.ok) {
            const data = await response.json();
            resultDiv.innerText = `--- ESTRATEGIA DE DEFENSA DIALÉCTICA ---\n\n${data.refutation}`;
        }
    } catch (err) {
        console.error(err);
    } finally {
        if (btnRefute) btnRefute.disabled = false;
    }
}

function triggerPDFDownload() {
    const analysisElement = document.getElementById("analysis-report");
    const currentAnalysis = analysisElement ? analysisElement.innerText.trim() : "";

    fetch(`${API_BASE_URL}/export_pdf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ score: lastScore, analysis: currentAnalysis, lang: currentLang })
    })
    .then(res => res.blob())
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'Polethic_Beacon_Report.pdf';
        a.click();
    });
}

function purgeDashboard() {
    document.getElementById("user-input").value = "";
    if (document.getElementById("user-file")) document.getElementById("user-file").value = "";
    document.getElementById("analysis-report").innerText = "...";
    document.getElementById("ethic-score").innerText = "Ethic-Score™: --";
    
    const container = document.getElementById("detected-flags-container");
    if (container) container.innerHTML = "";
    
    const resultsSection = document.getElementById("results-panel");
    if (resultsSection) resultsSection.style.display = "none"; // Oculta hasta el siguiente análisis

    lastAnalysisText = "";
    lastScore = 0;
}
