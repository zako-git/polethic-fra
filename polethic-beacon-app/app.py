import os
import re
import sqlite3
import io
import unicodedata
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from huggingface_hub import InferenceClient
from youtube_transcript_api import YouTubeTranscriptApi
from dotenv import load_dotenv

# --- ReportLab para exportación PDF ---
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

DATABASE_NAME = "beacon.db"

# Token de Hugging Face
HF_TOKEN = os.environ.get("HF_TOKEN")
client = InferenceClient(api_key=HF_TOKEN) if HF_TOKEN else None


def get_db_connection():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    try:
        conn = get_db_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS local_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module_key TEXT NOT NULL,
                keyword TEXT NOT NULL,
                risk_category TEXT NOT NULL,
                penalty_points INTEGER NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module_key TEXT,
                source_type TEXT,
                raw_content TEXT,
                ethic_score INTEGER,
                diagnostic_report TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[init_db] Warning: {e}")


def extract_transcript(url):
    try:
        if "youtu.be/" in url:
            video_id = url.split("youtu.be/")[1].split("?")[0]
        else:
            video_id = url.split("v=")[1].split("&")[0]

        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['fr', 'es', 'en'])
        return " ".join([t['text'] for t in transcript])
    except Exception as e:
        print(f"[extract_transcript] error: {e}")
        return None


def apply_local_rules(content):
    flags = []
    penalty_total = 0

    if not content or not isinstance(content, str):
        return penalty_total, flags

    lowered_content = content.lower()

    try:
        conn = get_db_connection()
        rules = conn.execute(
            "SELECT keyword, risk_category, penalty_points FROM local_rules"
        ).fetchall()
        conn.close()

        for rule in rules:
            keyword_lower = rule["keyword"].lower()
            if keyword_lower in lowered_content:
                penalty_total += rule["penalty_points"]
                flags.append(rule["risk_category"].lower())
    except Exception as e:
        print(f"[apply_local_rules] Warning/Skipped: {e}")

    return penalty_total, list(set(flags))


def get_ethic_letter(score):
    if score <= 25:
        return "A"
    elif score <= 50:
        return "B"
    elif score <= 75:
        return "C"
    return "D"


def save_audit(module_key, source_type, raw_content, ethic_score, diagnostic_report):
    try:
        conn = get_db_connection()
        conn.execute(
            """INSERT INTO audits (module_key, source_type, raw_content, ethic_score, diagnostic_report)
               VALUES (?, ?, ?, ?, ?)""",
            (module_key, source_type, str(raw_content), ethic_score, diagnostic_report)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[save_audit] error: {e}")


# =====================================================================
# 📍 TEMPLATES: DICCIONARIO DE PROMPTS Y PLANTILLAS MULTILINGÜES DINÁMICAS
# =====================================================================
TEMPLATES = {
    "fr": {
        "system": ( 
            "Vous êtes POLETHIC BEACON, un moteur d'analyse métacognitive et forensique avancé.\n"
            "Votre objectif est d'exécuter un pipeline d'analyse obligatoire en 4 phases.\n\n"
            "RÈGLE LINGUISTIQUE ABSOLUE : Rédigez l'INTÉGRALITÉ de la réponse et des titres EN FRANÇAIS.\n\n"
            "INTERDICTION ABSOLUE : N'utilisez JAMAIS les mots 'LIMBIQUE' ni 'ET LIMBIQUE' dans les titres ou le texte.\n\n"
            "DIRECTIVES D'ÉVALUATION STRICTES :\n"
            "- TARTE ROUGE / RISQUE ÉLEVÉ (Grade D, Score 76 à 100) : Attribution OBLIGATOIRE si le texte promeut des thérapies non conventionnelles ou approches à risque de dérive sectaire (ex: Constellations familiales / Bert Hellinger, mémoire cellulaire, ésotérisme), que ce soit dans la santé ou appliquées aux entreprises, au coaching et au leadership.\n"
            "- ORGANISMES DE VIGILANCE : Mentionnez systématiquement que ces pratiques font l'objet d'une vigilance accrue par des organismes officiels (ex: MIVILUDES en France) en raison des risques de dérive sectaire, d'emprise et de sujection psychologique.\n"
            "- RISQUE MODÉRÉ (Grade B-C, Score 26 à 75) : Si le texte présente des biais rhétoriques majeurs, de l'exagération commerciale ou du blanchiment de langage sans dérive ésotérique/sectaire.\n"
            "- RISQUE MINIME (Grade A, Score 0 à 25) : CV propre, texte informatif ou factuel sans coercition ni affirmations trompeuses.\n"
            "- NE JAMAIS INVENTER de biais non présents dans le texte.\n\n"
            "FORMAT DE SORTIE IMPÉRATIF (RESPECTEZ EXATEMENT CES TITRES) :\n\n"
            "🏷️ **CLASSIFICATION (Phase 0)**\n"
            "- Type de Texte:\n"
            "- Objectif de l'Émetteur:\n\n"
            "📌 **NOYAU DE FAITS / PRÉMISSES (Phase 1)**\n"
            "- Données et affirmations filtrées sans bruit:\n\n"
            "🧠 **DÉMONTAGE COGNITIF (Phase 2)**\n"
            "- Stratégie Rhétorique / Déclencheur Détecté:\n"
            "- Intention vs Réalité (Analyse de blanchiment / appropriation de langage):\n\n"
            "🚀 **RECADRAGE CORTICAL ET STRATÉGIE (Phase 3)**\n"
            "- Diagnostic synthétique final et évaluation objective du risque:\n\n"
            "<flags>[Liste séparée par des virgules parmi: fakenews, myth, bluff, coercion, dogma, pseudoscience, authority_transfer, psnc]</flags>\n"
            "<score>[Note entière de 0 à 100, ex: 85 pour Grade D]</score>"
        ),
        "refute_fallback": (
            "1. PREUVE CLINIQUE / ÉMPIRIQUE : Quelles études contrôlées démontrent l'efficacité de cette approche face aux méthodes scientifiques conventionnelles ?\n"
            "2. CADRE DÉRIVE SECTAIRE : Comment garantissez-vous l'absence de sujection psychologique ou d'influence ésotérique (ex: thèses d'Hellinger, MIVILUDES) sur les participants ?\n"
            "3. MESURE DE L'EFFICACITÉ : Quels indicateurs objectifs et vérifiables permettent de mesurer les résultats réels ?"
        )
    },
    "es": {
        "system": (
            "Eres POLETHIC BEACON, un motor de análisis metacognitivo y forense avanzado.\n"
            "Tu objetivo es ejecutar un pipeline obligatorio de análisis en 4 fases.\n\n"
            "REGLA LINGÜÍSTICA ABSOLUTA: Escribe la TOTALIDAD de la respuesta y los títulos EN ESPAÑOL.\n\n"
            "PROHIBICIÓN ABSOLUTA: NUNCA utilices las palabras 'LÍMBICO' ni 'Y LÍMBICO' en los títulos o el texto.\n\n"
            "DIRECTRICES DE EVALUACIÓN STRICTAS:\n"
            "- TARJETA ROJA / RIESGO ALTO (Grado D, Score 76 a 100): Asignación OBLIGATORIA si el texto promueve terapias no convencionales con riesgo de deriva sectaria (ej: Constelaciones familiares / Bert Hellinger, memoria celular, esoterismo), ya sea en salud o aplicadas a empresas, coaching y liderazgo.\n"
            "- ORGANISMOS DE VIGILANCIA: Señala explícitamente que estas prácticas están sometidas a la vigilancia de organismos oficiales (ej: MIVILUDES en Francia) debido al riesgo documentado de deriva sectaria, manipulación y sujeción psicológica.\n"
            "- RIESGO MODERADO (Grado B-C, Score 26 a 75): Si el texto presenta sesgos retóricos mayores, exageración comercial o blanqueamiento de lenguaje sin deriva esotérica/sectaria.\n"
            "- RIESGO MÍNIMO (Grado A, Score 0 a 25): CV limpio, texto informativo o factual sin coerción ni afirmaciones engañosas.\n"
            "- NO INVENTAR sesgos no presentes en el texto.\n\n"
            "FORMATO DE SALIDA OBLIGATORIO (RESPETA EXACTAMENTE ESTOS TÍTULOS):\n\n"
            "🏷️ **CLASIFICACIÓN (Fase 0)**\n"
            "- Tipo de Texto:\n"
            "- Propósito del Emisor:\n\n"
            "📌 **NÚCLEO DE HECHOS / PREMISAS (Fase 1)**\n"
            "- Datos y afirmaciones filtradas sin ruido:\n\n"
            "🧠 **DESMONTAJE COGNITIVO (Fase 2)**\n"
            "- Estrategia Retórica / Gatillo Detectado:\n"
            "- Intención vs. Realidad (Análisis de blanqueamiento / apropiación de lenguaje):\n\n"
            "🚀 **REENCUADRE CORTICAL Y ESTRATEGIA (Fase 3)**\n"
            "- Diagnóstico sintético final y valoración objetiva de riesgo:\n\n"
            "<flags>[Lista separada por comas de: fakenews, myth, bluff, coercion, dogma, pseudoscience, authority_transfer, psnc]</flags>\n"
            "<score>[Número entero de 0 a 100, ej: 85 para Grado D]</score>"
        ),
        "refute_fallback": (
            "1. EVIDENCIA EMPÍRICA: ¿Qué estudios controlados respaldan la efectividad de este enfoque frente a la gestión/psicología convencional?\n"
            "2. RIESGO SECTARIO: ¿Cómo se garantiza la ausencia de manipulación psicológica o doctrina esotérica (ej: observaciones de MIVILUDES u organismos estatales) en los participantes?\n"
            "3. MEDICIÓN DE RESULTADOS: ¿Bajo qué indicadores métricos y objetivos se evalúa el impacto real?"
        )
    },
    "en": {
        "system": (
            "You are POLETHIC BEACON, an advanced forensic metacognitive analysis engine.\n"
            "Your objective is to execute a mandatory 4-phase analysis pipeline.\n\n"
            "ABSOLUTE LANGUAGE RULE: Write the ENTIRE response and section titles IN ENGLISH.\n\n"
            "ABSOLUTE PROHIBITION: NEVER use the words 'LIMBIC' or 'AND LIMBIC' in titles or text.\n\n"
            "STRICT EVALUATION DIRECTIVES:\n"
            "- RED CARD / HIGH RISK (Grade D, Score 76 to 100): MANDATORY assignment if the text promotes unconventional therapies with high risk of cultic deviance (e.g., Family Constellations / Bert Hellinger, cellular memory, esotericism), whether in healthcare or applied to corporate settings, coaching, and leadership.\n"
            "- MONITORING AGENCIES: Highlight that these practices are closely monitored by official state agencies (e.g., MIVILUDES in France) due to documented risks of cultic deviance and psychological manipulation.\n"
            "- MODERATE RISK (Grade B-C, Score 26 to 75): If the text presents major rhetorical biases, commercial hype, or language laundering without esoteric/cultic deviance.\n"
            "- MINIMAL RISK (Grade A, Score 0 to 25): Clean CV, purely factual or informative text without coercion or misleading claims.\n"
            "- NEVER INVENT biases not present in the input text.\n\n"
            "MANDATORY OUTPUT FORMAT (RESPECT THESE TITLES EXACTLY):\n\n"
            "🏷️ **CLASSIFICATION (Phase 0)**\n"
            "- Text Type:\n"
            "- Sender Purpose:\n\n"
            "📌 **CORE FACTS / PREMISES (Phase 1)**\n"
            "- Noise-filtered data and claims:\n\n"
            "🧠 **COGNITIVE DECONSTRUCTION (Phase 2)**\n"
            "- Rhetorical Strategy / Trigger Detected:\n"
            "- Intent vs. Reality (Language laundering / appropriation analysis):\n\n"
            "🚀 **CORTICAL REFRAMING & STRATEGY (Phase 3)**\n"
            "- Final synthetic diagnosis and objective risk assessment:\n\n"
            "<flags>[Comma-separated list from: fakenews, myth, bluff, coercion, dogma, pseudoscience, authority_transfer, psnc]</flags>\n"
            "<score>[Integer from 0 to 100, e.g., 85 for Grade D]</score>"
        ),
        "refute_fallback": (
            "1. EMPIRICAL EVIDENCE: What controlled studies demonstrate the effectiveness of this approach compared to conventional scientific methods?\n"
            "2. CULTIC RISK SAFEGUARD: How do you guarantee the absence of psychological coercion or esoteric doctrine (e.g., state watchdog warnings like MIVILUDES) on participants?\n"
            "3. PERFORMANCE METRICS: Which objective and verifiable metrics are used to evaluate real-world outcomes?"
        )
    }
}

# =====================================================================
# SANEADO DE TEXTO PARA PDF (ReportLab)
# =====================================================================
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U0000FE0F"
    "]+",
    flags=re.UNICODE
)


def sanitize_for_pdf(text):
    if not text:
        return ""

    text = _EMOJI_PATTERN.sub("", text)
    text = "".join(
        ch for ch in text
        if unicodedata.category(ch)[0] != "C"
        and (ord(ch) < 0x2500 or ch in "™")
    )
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return text.strip()


def is_heading_line(original_line):
    stripped = _EMOJI_PATTERN.sub("", original_line).strip()
    return stripped.startswith("**") and stripped.rstrip().endswith("**")


# =====================================================================
# ENDPOINTS DE LA API
# =====================================================================

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json() or {}
        text = data.get("text", "")
        url = data.get("url", "")
        lang = str(data.get("lang", "fr")).lower()

        if lang not in TEMPLATES:
            lang = "fr"

        content_to_analyze = text
        source_type = "text"

        if url:
            transcript = extract_transcript(url)
            if transcript:
                content_to_analyze = transcript
                source_type = "youtube"

        if not content_to_analyze.strip():
            return jsonify({"error": "No content to analyze."}), 400

        # Reglas locales
        local_penalty, local_flags = apply_local_rules(content_to_analyze)

        template = TEMPLATES[lang]
        analysis_text = ""

        if client:
            try:
                response = client.chat.completions.create(
                    model="Qwen/Qwen2.5-Coder-32B-Instruct",
                    messages=[
                        {"role": "system", "content": template["system"]},
                        {"role": "user", "content": content_to_analyze}
                    ],
                    max_tokens=1000
                )
                analysis_text = response.choices[0].message.content
            except Exception as hf_err:
                print(f"[HF Error]: {hf_err}")
                analysis_text = "Error connecting to LLM service."

        # Extraer score y flags de la respuesta del modelo
        score_match = re.search(r"<score>(\d+)</score>", analysis_text)
        flags_match = re.search(r"<flags>(.*?)</flags>", analysis_text)

        model_score = int(score_match.group(1)) if score_match else 0
        model_flags = [f.strip() for f in flags_match.group(1).split(",")] if flags_match else []

        # Fusionar con reglas locales
        final_score = min(100, model_score + local_penalty)
        final_flags = list(set(model_flags + local_flags))

        # Limpiar etiquetas XML del informe visual
        clean_analysis = re.sub(r"<score>.*?</score>", "", analysis_text)
        clean_analysis = re.sub(r"<flags>.*?</flags>", "", clean_analysis).strip()

        ethic_letter = get_ethic_letter(final_score)
        save_audit("CORE", source_type, content_to_analyze, final_score, clean_analysis)

        return jsonify({
            "analysis": clean_analysis,
            "score": final_score,
            "flags": final_flags,
            "ethic_letter": ethic_letter
        }), 200

    except Exception as e:
        print(f"[Analyze error]: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/refute", methods=["POST"])
def refute():
    try:
        data = request.get_json() or {}
        analysis = data.get("analysis", "")
        lang = str(data.get("lang", "fr")).lower()

        if lang not in TEMPLATES:
            lang = "fr"

        if not analysis:
            return jsonify({"refutation": "No content provided to counter-argue."}), 400

        if client:
            prompt = (
                f"Analyse forensique préalable:\n{analysis}\n\n"
                f"CONSIGNE IMPÉRATIVE:\n"
                f"Génère exactement 3 questions chirurgicales de réfutation méthodologique "
                f"basées UNIQUEMENT sur les affirmations du texte ci-dessus.\n"
                f"INTERDICTION ABSOLUE d'inventer des termes absents du texte (pas de physique quantique, hypnose, urgence commerciale).\n"
                f"Rédige la réponse 100% dans la langue du code : '{lang.upper()}'."
            )
            response = client.chat.completions.create(
                model="Qwen/Qwen2.5-Coder-32B-Instruct",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=450
            )
            refutation_text = response.choices[0].message.content.strip()
        else:
            refutation_text = TEMPLATES[lang]["refute_fallback"]

        return jsonify({"refutation": refutation_text}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/export_pdf", methods=["POST"])
def export_pdf():
    try:
        data = request.get_json() or {}
        raw_score = data.get("score", 0)
        raw_analysis = (data.get("analysis") or "").replace("<br>", "\n").replace("<br/>", "\n")

        if not raw_analysis.strip():
            return jsonify({"error": "No hay análisis para exportar."}), 400

        try:
            digits = re.sub(r"[^\d]", "", str(raw_score))
            numeric_score = int(digits) if digits else 0
        except ValueError:
            numeric_score = 0

        ethic_letter = data.get("ethic_letter") or get_ethic_letter(numeric_score)

        pdf_buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=letter,
            rightMargin=40, leftMargin=40,
            topMargin=40, bottomMargin=40
        )

        story = []

        primary_blue = colors.HexColor("#0284c7")
        text_body = colors.HexColor("#334155")
        heading_color = colors.HexColor("#0f172a")

        if ethic_letter == "A":
            score_color = colors.HexColor("#059669")
        elif ethic_letter == "B":
            score_color = colors.HexColor("#d97706")
        elif ethic_letter == "C":
            score_color = colors.HexColor("#ea580c")
        else:
            score_color = colors.HexColor("#dc2626")

        title_style = ParagraphStyle(
            'DocTitle',
            fontName='Helvetica-Bold',
            fontSize=16,
            leading=20,
            textColor=primary_blue
        )
        subtitle_style = ParagraphStyle(
            'DocSubtitle',
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#64748b")
        )
        score_style = ParagraphStyle(
            'ScoreDisplay',
            fontName='Helvetica-Bold',
            fontSize=13,
            leading=16,
            textColor=score_color,
            alignment=2
        )
        heading_style = ParagraphStyle(
            'SectionHeading',
            fontName='Helvetica-Bold',
            fontSize=11,
            leading=15,
            textColor=heading_color,
            spaceBefore=12,
            spaceAfter=4,
        )
        body_style = ParagraphStyle(
            'ReportBody',
            fontName='Helvetica',
            fontSize=9.5,
            leading=14,
            textColor=text_body
        )

        story.append(Paragraph("POLETHIC FRANCE — BEACON LAB", title_style))
        story.append(Paragraph("RAPPORT D'AUDIT METACOGNITIF ET METACONTEXTUEL", subtitle_style))
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"ETHIC-SCORE: {ethic_letter} ({numeric_score}/100)", score_style))
        story.append(Spacer(1, 12))

        for raw_line in raw_analysis.split('\n'):
            line_str = raw_line.strip()
            if not line_str:
                continue

            clean_line = sanitize_for_pdf(line_str)
            if not clean_line:
                continue

            if is_heading_line(line_str):
                story.append(Paragraph(clean_line, heading_style))
            else:
                story.append(Paragraph(clean_line, body_style))
                story.append(Spacer(1, 4))

        doc.build(story)
        pdf_buffer.seek(0)

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'Audit_BEACON_{ethic_letter}.pdf'
        )
    except Exception as e:
        print(f"[export_pdf error]: {e}")
        return jsonify({"error": str(e)}), 500


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
