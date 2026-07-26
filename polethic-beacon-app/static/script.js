// Déjalo en "" si Flask sirve el HTML. 
// Si tu frontend está en otro dominio o servidor, pon la URL de Render (ej: "https://polethic-beacon-app.onrender.com")
const API_BASE_URL = ""; 

// Current active defense window (default is "news")
let currentWindow = "news";
// Tracks the module actually used for the last completed analysis,
// so PDF export always matches what is on screen (not whichever tab is open now)
let lastAnalyzedModule = "news";
// Tracks the raw numeric score from the last analysis, so PDF export
// never has to re-parse it back out of already-formatted display text
let lastScore = 0; // Defaults to 0 (Clean)

const windowTitles = {
    "news": "1. FakeNews: Enter the article text or link to evaluate:",
    "myth": "2. Myth-Buster: Paste the claim, remedy, or pseudoscientific theory:",
    "identity_spoofing": "3. Identity Spoofing: Paste the profile, credentials, or bio to audit:",
    "coercion": "4. Coercive Filter: Enter the persuasive text or suspicious discourse:"
};

const windowPlaceholders = {
    "news": "Paste media text, political articles, or video links to Beacon-ize it...",
    "myth": "Paste claims regarding alternative medicine or unverified theories to Beacon-ize it...",
    "identity_spoofing": "Paste suspicious bio data or credentials to audit for structural/professional intrusion...",
    "coercion": "Paste high-pressure sales pitches to Beacon-ize it..."
};

const sourceTypeLabels = {
    "plain_text": "📝 Source: plain text",
    "video_transcript": "🎬 Source: YouTube video transcript",
    "image_screenshot": "🖼️ Source: image (OCR-extracted text)"
};

document.addEventListener("DOMContentLoaded", () => {
    setupNavTabs();
    setupFileInput();
});

// Uses event delegation on data-module attributes instead of matching each
// button by a hardcoded id — this avoids silent breakage if a button id and
// its JS reference ever drift apart (e.g. after renaming a module).
function setupNavTabs() {
    document.querySelectorAll(".nav-tabs button").forEach(button => {
        button.addEventListener("click", () => {
            const windowType = button.dataset.module;
            if (!windowType) return;

            document.querySelectorAll(".nav-tabs button").forEach(btn => btn.classList.remove("active"));
            button.classList.add("active");
            currentWindow = windowType;

            // window-title is optional: only update it if present in the DOM
            const titleEl = document.getElementById("window-title");
            if (titleEl && windowTitles[windowType]) {
                titleEl.innerText = windowTitles[windowType];
            }

            const inputEl = document.getElementById("user-input");
            if (inputEl && windowPlaceholders[windowType]) {
                inputEl.placeholder = windowPlaceholders[windowType];
            }
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

// Renders the report text safely (no innerHTML injection of model/user content)
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

// Returns just the clean letter grade in English, with no color references
function getEthicLetter(score) {
    if (score <= 20) return "A";
    if (score <= 40) return "B";
    if (score <= 60) return "C";
    if (score <= 80) return "D";
    return "E";
}

function renderLocalFlags(flags) {
    const flagsList = document.getElementById("local-flags");
    if (!flagsList) return;

    flagsList.innerHTML = "";

    if (!flags || flags.length === 0) {
        const li = document.createElement("li");
        li.style.color = "#8b949e";
        li.style.listStyleType = "none";
        li.style.marginLeft = "-20px";
        li.innerText = "No local pattern flags detected.";
        flagsList.appendChild(li);
        return;
    }

    flags.forEach(flag => {
        const li = document.createElement("li");
        // Kept consistent in English: "pts" instead of "pts de riesgo"
        li.innerText = `"${flag.keyword}" → ${flag.category} (+${flag.penalty} pts)`;
        flagsList.appendChild(li);
    });
}

// 1. BEACON-IZE: The Main Analysis Function
async function analyze() {
    const textInput = document.getElementById("user-input").value.trim();
    const fileInput = document.getElementById("user-file");
    const file = fileInput && fileInput.files.length > 0 ? fileInput.files[0] : null;

    const scoreDiv = document.getElementById("ethic-score");
    const resultDiv = document.getElementById("analysis-report");
    const analyzeButton = document.getElementById("btn-analyze");

    if (!textInput && !file) {
        if (resultDiv) resultDiv.innerText = "Please introduce some content or attach an image to Beacon-ize.";
        return;
    }

    if (analyzeButton) {
        analyzeButton.innerText = "...";
        analyzeButton.disabled = true;
    }
    if (scoreDiv) {
        scoreDiv.innerText = "Ethic-Score™: --";
    }
    if (resultDiv) {
        resultDiv.innerText = "Running linguistic pattern analysis... Please wait.";
    }

    try {
        let response;

        if (file) {
            const formData = new FormData();
            formData.append("text", textInput);
            formData.append("module", currentWindow);
            formData.append("file", file);

            response = await fetch(`${API_BASE_URL}/analyze`, {
                method: "POST",
                body: formData
            });
        } else {
            response = await fetch(`${API_BASE_URL}/analyze`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: textInput, module: currentWindow })
            });
        }

        if (!response.ok) {
            throw new Error("Server communication failure");
        }

        const data = await response.json();

        // score can be null when the backend could not parse a reliable number
        // from the LLM response — this must show as an explicit error state,
        // not silently default to 0 (which would look like "no risk found").
        if (data.score === null || data.score === undefined) {
            lastAnalyzedModule = currentWindow;
            lastScore = 0;

            const resultsSection = document.getElementById("results-panel");
            if (resultsSection) resultsSection.className = 'results-section';

            if (scoreDiv) scoreDiv.innerText = "Ethic-Score™: Unavailable (parsing error)";
            if (resultDiv && data.analysis) renderReport(resultDiv, data.analysis);
            renderLocalFlags(data.local_flags);

            if (analyzeButton) {
                analyzeButton.innerText = "BEACON-IZE";
                analyzeButton.disabled = false;
            }
            return;
        }

        const parsedScore = parseInt(data.score, 10);
        // Defaults to 0 (no risk) if parsing fails
        const score = Number.isNaN(parsedScore) ? 0 : parsedScore;

        lastAnalyzedModule = currentWindow;
        lastScore = score;

        const resultsSection = document.getElementById("results-panel");
        if (resultsSection) {
            resultsSection.className = 'results-section';

            // Inverted scale: higher score = more dangerous
            if (score >= 81) {
                resultsSection.classList.add("threat-high");    // Letter E (Red)
            } else if (score >= 41) {
                resultsSection.classList.add("threat-medium");  // Letters C and D (Yellow/Orange)
            } else {
                resultsSection.classList.add("threat-low");     // Letters A and B (Green)
            }
        }

        if (scoreDiv) {
            // Only the letter grade is shown to the user; the numeric score
            // stays internal (DB, PDF color logic) but is never displayed on screen.
            scoreDiv.innerText = `Ethic-Score™: [${getEthicLetter(score)}]`;
        }

        if (resultDiv && data.analysis) {
            renderReport(resultDiv, data.analysis);
        }

        renderLocalFlags(data.local_flags);

    } catch (error) {
        console.error(error);
        if (scoreDiv) scoreDiv.innerText = "Error: System Offline";
        if (resultDiv) resultDiv.innerText = "The Beacon core is currently unreachable. Please verify your connection or server status.";
    } finally {
        if (analyzeButton) {
            analyzeButton.innerText = "BEACON-IZE";
            analyzeButton.disabled = false;
        }
    }
}

// 2. EXPORT PDF
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
            module: lastAnalyzedModule
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

// 3. PURGE DASHBOARD: Clean application state reset
function purgeDashboard() {
    const textInput = document.getElementById("user-input");
    if (textInput) textInput.value = "";

    const fileInput = document.getElementById("user-file");
    if (fileInput) fileInput.value = "";

    const fileNameDisplay = document.getElementById("file-name-display");
    if (fileNameDisplay) fileNameDisplay.innerText = "";

    const scoreElement = document.getElementById("ethic-score");
    if (scoreElement) {
        scoreElement.innerText = "Ethic-Score™: --";
    }
    lastScore = 0; // Reset to zero risk

    const analysisElement = document.getElementById("analysis-report");
    if (analysisElement) analysisElement.innerText = "System cleared. Awaiting new pattern audit payload...";

    renderLocalFlags([]);

    const resultsSection = document.getElementById("results-panel");
    if (resultsSection) {
        resultsSection.className = 'results-section';
    }
    console.log("Dashboard state successfully purged.");
}
