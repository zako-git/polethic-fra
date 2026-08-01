const API_BASE_URL = "https://polethic-beacon-api.onrender.com";

let lastScore = 0;
let lastAnalysisText = "";

// Detectar idioma inicial
const urlParams = new URLSearchParams(window.location.search);
let currentLang = urlParams.get('lang') || localStorage.getItem('preferred_lang') || "fr";

// Diccionario de textos
const i18n = {
    fr: {
        ethicLabel: "Ethic-Score™",
        runningText: "⚡ Analyse des motifs linguistiques et des biais en cours... Veuillez patienter.",
        emptyText: "Veuillez introduire du contenu ou joindre une image à analyser.",
        systemOffline: "Erreur: Système Hors Ligne",
        offlineReport: "Le cœur de Beacon est inaccessible. Vérifiez votre connexion ou le serveur.",
        flags: {
            fakenews: "FakeNews",
            myth: "Chasseur de Mythes",
            identity_spoofing: "Usurpation / Posture",
            coercion: "Filtre Coercitif"
        }
    },
    es: {
        ethicLabel: "Ethic-Score™",
        runningText: "⚡ Ejecutando análisis de patrones lingüísticos y sesgos... Espera un momento.",
        emptyText: "Por favor, introduce algún texto o adjunta una imagen para analizar.",
        systemOffline: "Error: Sistema Fuera de Línea",
        offlineReport: "El núcleo de Beacon no está localizable. Verifica tu conexión o el servidor.",
        flags: {
            fakenews: "FakeNews",
            myth: "Cazador de Mitos",
            identity_spoofing: "Postureo / Identidad",
            coercion: "Filtre Coercitivo"
        }
    },
    en: {
        ethicLabel: "Ethic-Score™",
        runningText: "⚡ Running linguistic pattern & bias analysis... Please wait.",
        emptyText: "Please introduce some text or attach an image to analyze.",
        systemOffline: "Error: System Offline",
        offlineReport: "The Beacon core is currently unreachable. Check your connection or server status.",
        flags: {
            fakenews: "FakeNews",
            myth: "Myth-Buster",
            identity_spoofing: "Identity / Posturing",
            coercion: "Coercive Filter"
        }
    }
};

document.addEventListener("DOMContentLoaded", () => {
    setupActionButtons();
    setupFileInput();
    setupLangSelector();
});

// 1. VINCULACIÓN DEL BOTÓN BEACON-IZE Y RESTO DE ACCIONES
function setupActionButtons() {
    const btnAnalyze = document.getElementById("btn-analyze");
    if (btnAnalyze) {
        btnAnalyze.addEventListener("click", (e) => {
            e.preventDefault();
            analyze(); // Llama a la función principal
        });
    }

    const btnRefute = document.getElementById("btn-refute");
    if (btnRefute) {
        btnRefute.addEventListener("click", (e) => {
            e.preventDefault();
            generateRefutation();
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

// 2. FUNCIÓN EJECUTADA AL PULSAR EL BOTÓN BEACON-IZE
async function analyze() {
    const t = i18n[currentLang] || i18n.fr;
    const textInput = document.getElementById("user-input").value.trim();
    const fileInput = document.getElementById("user-file");
    const file = fileInput && fileInput.files.length > 0 ? fileInput.files[0] : null;

    const btnAnalyze = document.getElementById("btn-analyze");
    const resultsPanel = document.getElementById("results-panel");
    const scoreDiv = document.getElementById("ethic-score");
    const resultDiv = document.getElementById("analysis-report");

    // Validación de entrada vacía
    if (!textInput && !file) {
        alert(t.emptyText);
        return;
    }

    // Efecto de carga en el botón y despliegue del panel
    if (btnAnalyze) {
        btnAnalyze.innerText = "⏳ ANALYSING...";
        btnAnalyze.disabled = true;
    }

    if (resultsPanel) resultsPanel.style.display = "block";
    if (scoreDiv) scoreDiv.innerText = `${t.ethicLabel}: --`;
    if (resultDiv) resultDiv.innerText = t.runningText;

    try {
        let response;

        // Petición al backend (con o sin archivo)
        if (file) {
            const formData = new FormData();
            formData.append("text", textInput);
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
                body: JSON.stringify({ text: textInput, lang: currentLang })
            });
        }

        if (!response.ok) throw new Error("Server error");

        const data = await response.json();

        // Almacenar datos en memoria
        lastScore = parseInt(data.score, 10) || 0;
        lastAnalysisText = data.analysis || "";

        // Mostrar puntuación y reporte
        if (scoreDiv) scoreDiv.innerText = `${t.ethicLabel}: ${getEthicLetter(lastScore)}`;
        if (resultDiv) resultDiv.innerText = lastAnalysisText;

        // Renderizar botones/badges de categorías detectadas automáticamente
        renderDetectedFlags(data.detected_flags || []);

    } catch (error) {
        console.error("Error en BEACON-IZE:", error);
        if (scoreDiv) scoreDiv.innerText = t.systemOffline;
        if (resultDiv) resultDiv.innerText = t.offlineReport;
    } finally {
        if (btnAnalyze) {
            btnAnalyze.innerText = "⚡ ANALYSER LE TEXTE";
            btnAnalyze.disabled = false;
        }
    }
}

// Convertir nota numérica a letra (A, B, C, D)
function getEthicLetter(score) {
    if (score <= 25) return "A";
    if (score <= 50) return "B";
    if (score <= 75) return "C";
    return "D";
}

// Inyectar etiquetas detectadas automáticamente en el informe
function renderDetectedFlags(flags) {
    const container = document.getElementById("detected-flags-container");
    if (!container) return;
    container.innerHTML = "";

    const t = i18n[currentLang]?.flags || i18n.fr.flags;

    flags.forEach(flag => {
        const badge = document.createElement("span");
        badge.className = `flag-badge flag-${flag}`;
        badge.innerText = t[flag] || flag;
        container.appendChild(badge);
    });
}

// Selector de idioma
function setupLangSelector() {
    ["fr", "es", "en"].forEach(lang => {
        const btn = document.getElementById(`btn-${lang}`);
        if (btn) {
            btn.addEventListener("click", (e) => {
                e.preventDefault();
                currentLang = lang;
                localStorage.setItem('preferred_lang', lang);
                document.querySelectorAll('.lang-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            });
        }
    });
}

// Mostrar nombre del archivo al adjuntar cámara/imagen
function setupFileInput() {
    const fileInput = document.getElementById("user-file");
    const fileNameDisplay = document.getElementById("file-name-display");
    if (!fileInput) return;

    fileInput.addEventListener("change", () => {
        if (fileInput.files.length > 0) {
            if (fileNameDisplay) fileNameDisplay.innerText = `📎 ${fileInput.files[0].name}`;
        } else {
            if (fileNameDisplay) fileNameDisplay.innerText = "";
        }
    });
}

// Purga de la consola
function purgeDashboard() {
    document.getElementById("user-input").value = "";
    if (document.getElementById("user-file")) document.getElementById("user-file").value = "";
    if (document.getElementById("file-name-display")) document.getElementById("file-name-display").innerText = "";
    
    const resultsPanel = document.getElementById("results-panel");
    if (resultsPanel) resultsPanel.style.display = "none";

    lastScore = 0;
    lastAnalysisText = "";
}
