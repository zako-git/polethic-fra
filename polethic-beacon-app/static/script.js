const API_BASE_URL = "https://polethic-beacon-api.onrender.com";

let lastScore = 0;
let lastAnalysisText = "";

// Detectar idioma inicial
const urlParams = new URLSearchParams(window.location.search);
let currentLang = urlParams.get('lang') || localStorage.getItem('preferred_lang') || "fr";

// Diccionario Completo de Traducciones
const i18n = {
    fr: {
        nav_home: "ACCUEIL",
        nav_obs: "L'OBSERVATOIRE",
        nav_museum: "PSICOMUSÉE",
        nav_beacon: "BEACON LAB",
        nav_cap: "NOTRE CAP",
        nav_contact: "CONTACT",
        beacon_subtitle: "Moteur d'autodéfense cognitive & Analyse métacommunicationnelle",
        btn_beaconise: "⚡ BEACON-IZE",
        btnAnalyzeLoading: "⏳ ANALYSE EN COURS...",
        status_ready: "● MOTEUR PRÊT",
        flag_ready: "ANALYSE PRÊTE",
        report_placeholder: "En attente d'analyse... Entrez un texte ou téléchargez une image ci-dessus et cliquez sur BEACON-IZE.",
        btn_refute: "🔄 RÉFUTER / CHALLENGER",
        btn_pdf: "📄 EXPORTER EN PDF",
        btn_purge: "🗑️ PURGER",
        ethicLabel: "Ethic-Score™",
        runningText: "⚡ Analyse des motifs linguistiques et des biais en cours... Veuillez patienter.",
        emptyText: "Veuillez introduire du contenu ou joindre une image à analyser.",
        systemOffline: "Erreur: Système Hors Ligne",
        offlineReport: "Le cœur de Beacon est inaccessible. Vérifiez votre connexion ou le serveur.",
        footer_shield: "Bouclier de Protection Professionnelle",
        footer_disc1: "Action exclusive de prévention primaire et de psychoéducation non clinique.",
        footer_disc2: "Aucun diagnostic ou thérapie médicale n'est pratiqué.",
        footer_legal: "Mentions Légales",
        footer_privacy: "Politique de Confidentialité",
        footer_cookies: "Gestion des Cookies",
        flags: {
            fakenews: "FakeNews",
            myth: "Chasseur de Mythes",
            identity_spoofing: "Bluff & Esbroufe",
            coercion: "Filtre Coercitif"
        }
    },
    es: {
        nav_home: "INICIO",
        nav_obs: "OBSERVATORIO",
        nav_museum: "PSICOMUSEO",
        nav_beacon: "BEACON LAB",
        nav_cap: "NUESTRO RUMBO",
        nav_contact: "CONTACTO",
        beacon_subtitle: "Motor de autodefensa cognitiva y Análisis metacomunicacional",
        btn_beaconise: "⚡ BEACON-IZE",
        btnAnalyzeLoading: "⏳ ANALIZANDO...",
        status_ready: "● MOTOR LISTO",
        flag_ready: "ANÁLISIS LISTO",
        report_placeholder: "Esperando análisis... Ingrese un texto o suba una imagen arriba y haga clic en BEACON-IZE.",
        btn_refute: "🔄 REFUTAR / DESAFIAR",
        btn_pdf: "📄 EXPORTAR EN PDF",
        btn_purge: "🗑️ PURGAR",
        ethicLabel: "Ethic-Score™",
        runningText: "⚡ Ejecutando análisis de patrones lingüísticos y sesgos... Espera un momento.",
        emptyText: "Por favor, introduce algún texto o adjunta una imagen para analizar.",
        systemOffline: "Error: Sistema Fuera de Línea",
        offlineReport: "El núcleo de Beacon no está localizable. Verifica tu conexión o el servidor.",
        footer_shield: "Escudo de Protección Profesional",
        footer_disc1: "Acción exclusiva de prevención primaria y psicoeducación no clínica.",
        footer_disc2: "No se realiza ningún diagnóstico ni terapia médica.",
        footer_legal: "Aviso Legal",
        footer_privacy: "Política de Privacidad",
        footer_cookies: "Gestión de Cookies",
        flags: {
            fakenews: "FakeNews",
            myth: "Cazador de Mitos",
            identity_spoofing: "Postureo / Identidad",
            coercion: "Filtro Coercitivo"
        }
    },
    en: {
        nav_home: "HOME",
        nav_obs: "OBSERVATORY",
        nav_museum: "PSYCHOMUSEUM",
        nav_beacon: "BEACON LAB",
        nav_cap: "OUR COURSE",
        nav_contact: "CONTACT",
        beacon_subtitle: "Cognitive self-defense engine & Metacommunicational analysis",
        btn_beaconise: "⚡ BEACON-IZE",
        btnAnalyzeLoading: "⏳ ANALYZING...",
        status_ready: "● ENGINE READY",
        flag_ready: "ANALYSIS READY",
        report_placeholder: "Awaiting analysis... Enter text or upload an image above and click BEACON-IZE.",
        btn_refute: "🔄 REFUTE / CHALLENGE",
        btn_pdf: "📄 EXPORT PDF",
        btn_purge: "🗑️ PURGE",
        ethicLabel: "Ethic-Score™",
        runningText: "⚡ Running linguistic pattern & bias analysis... Please wait.",
        emptyText: "Please introduce some text or attach an image to analyze.",
        systemOffline: "Error: System Offline",
        offlineReport: "The Beacon core is currently unreachable. Check your connection or server status.",
        footer_shield: "Professional Protection Shield",
        footer_disc1: "Exclusive action for primary prevention and non-clinical psychoeducation.",
        footer_disc2: "No medical diagnosis or therapy is performed.",
        footer_legal: "Legal Notice",
        footer_privacy: "Privacy Policy",
        footer_cookies: "Cookie Management",
        flags: {
            fakenews: "FakeNews",
            myth: "Myth-Buster",
            identity_spoofing: "Identity / Posturing",
            coercion: "Coercive Filter"
        }
    }
};

// 1. APLICAR IDIOMA EN TODA LA PÁGINA
function updatePageLanguage(lang) {
    currentLang = lang;
    localStorage.setItem('preferred_lang', lang);

    const t = i18n[lang] || i18n.fr;

    // Actualizar elementos con atributo data-key
    document.querySelectorAll('[data-key]').forEach(element => {
        const key = element.getAttribute('data-key');
        if (t && t[key]) {
            element.textContent = t[key];
        }
    });

    // Actualizar estados visuales de los botones FR / ES / EN
    document.querySelectorAll('.lang-btn').forEach(btn => btn.classList.remove('active'));
    const activeBtn = document.getElementById(`btn-${lang}`);
    if (activeBtn) activeBtn.classList.add('active');
}

// 2. CONFIGURAR BOTONES Y LISTENERS
function setupActionButtons() {
    const btnAnalyze = document.getElementById("btn-analyze");
    if (btnAnalyze) {
        btnAnalyze.addEventListener("click", (e) => {
            e.preventDefault();
            analyze();
        });
    }

    const btnRefute = document.getElementById("btn-refute");
    if (btnRefute) {
        btnRefute.addEventListener("click", (e) => {
            e.preventDefault();
            alert("Función de refutación activada");
        });
    }

    const btnPdf = document.getElementById("btn-pdf");
    if (btnPdf) {
        btnPdf.addEventListener("click", (e) => {
            e.preventDefault();
            window.print();
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

// 3. FUNCIÓN DE ANÁLISIS PRINCIPAL
async function analyze() {
    const t = i18n[currentLang] || i18n.fr;
    const userInputEl = document.getElementById("user-input");
    const textInput = userInputEl ? userInputEl.value.trim() : "";
    const fileInput = document.getElementById("user-file");
    const file = fileInput && fileInput.files.length > 0 ? fileInput.files[0] : null;

    const btnAnalyze = document.getElementById("btn-analyze");
    const resultsPanel = document.getElementById("results-panel");
    const scoreDiv = document.getElementById("ethic-score");
    const resultDiv = document.getElementById("analysis-report");

    if (!textInput && !file) {
        alert(t.emptyText);
        return;
    }

    if (btnAnalyze) {
        btnAnalyze.innerText = t.btnAnalyzeLoading;
        btnAnalyze.disabled = true;
    }

    if (resultsPanel) resultsPanel.style.display = "block";
    if (scoreDiv) scoreDiv.innerText = `${t.ethicLabel}: --`;
    if (resultDiv) resultDiv.innerText = t.runningText;

    try {
        let response;

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

        lastScore = parseInt(data.score, 10) || 0;
        lastAnalysisText = data.analysis || "";

        if (scoreDiv) scoreDiv.innerText = `${t.ethicLabel}: ${getEthicLetter(lastScore)}`;
        if (resultDiv) resultDiv.innerText = lastAnalysisText;

        renderDetectedFlags(data.detected_flags || []);

    } catch (error) {
        console.error("Error en BEACON-IZE:", error);
        if (scoreDiv) scoreDiv.innerText = t.systemOffline;
        if (resultDiv) resultDiv.innerText = t.offlineReport;
    } finally {
        if (btnAnalyze) {
            btnAnalyze.innerText = "⚡ BEACON-IZE";
            btnAnalyze.disabled = false;
        }
    }
}

function getEthicLetter(score) {
    if (score <= 25) return "A";
    if (score <= 50) return "B";
    if (score <= 75) return "C";
    return "D";
}

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

function setupLangSelector() {
    ["fr", "es", "en"].forEach(lang => {
        const btn = document.getElementById(`btn-${lang}`);
        if (btn) {
            btn.addEventListener("click", (e) => {
                e.preventDefault();
                updatePageLanguage(lang);
            });
        }
    });
}

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

function purgeDashboard() {
    const userInput = document.getElementById("user-input");
    const userFile = document.getElementById("user-file");
    const fileNameDisplay = document.getElementById("file-name-display");
    const resultsPanel = document.getElementById("results-panel");

    if (userInput) userInput.value = "";
    if (userFile) userFile.value = "";
    if (fileNameDisplay) fileNameDisplay.innerText = "";
    if (resultsPanel) resultsPanel.style.display = "none";

    lastScore = 0;
    lastAnalysisText = "";
}

// INICIALIZACIÓN
document.addEventListener("DOMContentLoaded", () => {
    updatePageLanguage(currentLang);
    setupActionButtons();
    setupLangSelector();
    setupFileInput();
});
