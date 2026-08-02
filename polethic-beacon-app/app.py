import os
import re
import sqlite3
import io
import base64
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from huggingface_hub import InferenceClient
from youtube_transcript_api import YouTubeTranscriptApi
from PIL import Image
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
# DICCIONARIO DE PROMPTS Y PLANTILLAS MULTILINGÜES DINÁMICAS
# =====================================================================
TEMPLATES = {
    "fr": {
        "system": (
            "Vous êtes POLETHIC BEACON, un moteur d'analyse métacognitive et forensique avancé.\n"
            "Votre objectif est d'exécuter un pipeline d'analyse obligatoire en 4 phases.\n\n"
            "RÈGLE LINGUISTIQUE ABSOLUE : Rédigez l'INTÉGRALITÉ de la réponse et des titres EN FRANÇAIS.\n\n"
            "DIRECTIVES D'ÉVALUATION :\n"
            "- Si le texte introduit des thérapies non conventionnelles (PSNC/Sophrologie) associées à des institutions médicales/publiques ou des maladies graves, attribuez un Ethic-Score entre 55 et 75 (Grade C).\n"
            "- Si le texte est un CV propre sans affirmations trompeuses ni coercition, attribuez un score entre 0 et 25 (Grade A).\n"
            "- NE JAMAIS INVENTER de biais (ex: pas de physique quantique ni d'hypnose si non mentionnés).\n\n"
            "FORMAT DE SORTIE IMPÉRATIF (RESPECTEZ EXATEMENT CES TITRES) :\n\n"
            "🏷️ **CLASSIFICATION (Phase 0)**\n"
            "- Type de Texte:\n"
            "- Objectif de l'Émetteur:\n\n"
            "📌 **NOYAU DE FAITS / PRÉMISSES (Phase 1)**\n"
            "- Données et affirmations filtrées sans bruit:\n\n"
            "🧠 **DÉMONTAGE COGNITIF ET LIMBIQUE (Phase 2)**\n"
            "- Stratégie Rhétorique / Déclencheur Détecté:\n"
            "- Intention vs Réalité (Analyse de blanchiment / appropriation de langage):\n\n"
            "🚀 **RECADRAGE CORTICAL ET STRATÉGIE (Phase 3)**\n"
            "- Diagnostic synthétique final et évaluation objective du risque:\n\n"
            "<flags>[Liste séparée par des virgules parmi: fakenews, myth, bluff, coercion, dogma, pseudoscience, authority_transfer, psnc]</flags>\n"
            "<score>[Note entière de 0 à 100]</score>"
        ),
        "refute_fallback": (
            "1. PREUVE CLINIQUE : Quelles études contrôlées démontrent l'efficacité de cette approche face aux protocoles médicaux conventionnels ?\n"
            "2. CADRE LÉGAL : Comment est délimité le cadre d'intervention entre l'accompagnement non conventionnel et le traitement médical strict ?\n"
            "3. MESURE DE L'EFFICACITÉ : Quels indicateurs objectifs et vérifiables permettent de mesurer les résultats chez les patients ?"
        )
    },
    "es": {
        "system": (
            "Eres POLETHIC BEACON, un motor de análisis metacognitivo forense avanzado.\n"
            "Tu objetivo es ejecutar un pipeline obligatorio de 4 fases.\n\n"
            "REGLA LINGÜÍSTICA ABSOLUTA: Escribe la TOTALIDAD de la respuesta y los títulos EN ESPAÑOL.\n\n"
            "DIRECTRICES DE EVALUACIÓN:\n"
            "- Si el texto introduce terapias no convencionales (PSNC/Sofrología) asociadas a instituciones médicas/públicas o enfermedades graves, asigna un Ethic-Score entre 55 y 75 (Grado C).\n"
            "- Si el texto es un CV limpio sin afirmaciones engañosas, asigna entre 0 y 25 (Grado A).\n"
            "- NO INVENTAR sesgos no presentes en el texto.\n\n"
            "FORMATO DE SALIDA OBLIGATORIO:\n\n"
            "🏷️ **CLASIFICACIÓN (Fase 0)**\n"
            "- Tipo de Texto:\n"
            "- Propósito del Emisor:\n\n"
            "📌 **NÚCLEO DE HECHOS / PREMISAS (Fase 1)**\n"
            "- Datos y afirmaciones filtradas sin ruido:\n\n"
            "🧠 **DESMONTAJE COGNITIVO Y LÍMBICO (Fase 2)**\n"
            "- Estrategia Retórica / Gatillo Detectado:\n"
            "- Intención vs. Realidad:\n\n"
            "🚀 **REENCUADRE CORTICAL Y ESTRATEGIA (Fase 3)**\n"
            "- Diagnóstico sintético final y valoración objetiva de riesgo:\n\n"
            "<flags>[Lista separada por comas de: fakenews, myth, bluff, coercion, dogma, pseudoscience, authority_transfer, psnc]</flags>\n"
            "<score>[Número entero de 0 a 100]</score>"
        ),
        "refute_fallback": (
            "1. EVIDENCIA CLÍNICA: ¿Qué estudios controlados respaldan la efectividad de este enfoque frente a la medicina convencional?\n"
            "2. MARCO LEGAL: ¿Cómo se delimita el alcance entre el acompañamiento no convencional y el tratamiento médico estricto?\n"
            "3. MEDICIÓN DE RESULTADOS: ¿Bajo qué indicadores métricos y objetivos se evalúa la mejora real en los pacientes?"
        )
    },
    "en": {
        "system": (
            "You are POLETHIC BEACON, an advanced Forensic Metacognitive Engine.\n"
            "Your objective is to execute a mandatory 4-Phase analysis pipeline.\n\n"
            "ABSOLUTE LANGUAGE RULE: Write the ENTIRE response and headings 100% IN ENGLISH.\n\n"
            "MANDATORY OUTPUT FORMAT:\n\n"
            "🏷️ **CLASSIFICATION (Phase 0)**\n"
            "- Text Type:\n"
            "- Issuer Purpose:\n\n"
            "📌 **CORE FACTS / PREMISES (Phase 1)**\n"
            "- Filtered data and claims without noise:\n\n"
            "🧠 **COGNITIVE & LIMBIC DECONSTRUCTION (Phase 2)**\n"
            "- Rhetorical Strategy / Trigger Detected:\n"
            "- Intention vs Reality:\n\n"
            "🚀 **CORTICAL REFRAMING & STRATEGY (Phase 3)**\n"
            "- Final synthetic diagnosis and objective risk assessment:\n\n"
            "<flags>[Comma-separated list from: fakenews, myth, bluff, coercion, dogma, pseudoscience, authority_transfer, psnc]</flags>\n"
            "<score>[Integer score from 0 to 100]</score>"
        ),
        "refute_fallback": (
            "1. CLINICAL EVIDENCE: What controlled studies support the efficacy of this approach compared to conventional medicine?\n"
            "2. LEGAL FRAMEWORK: How is the scope defined between non-conventional support and strict medical treatment?\n"
            "3. OUTCOME MEASUREMENT: What objective metrics are used to measure actual patient outcomes?"
        )
    }
}


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        lang = "fr"
        if request.is_json:
            data = request.get_json() or {}
            user_input = data.get("text", "").strip()
            lang = str(data.get("lang", "fr")).lower()
            file = None
        else:
            user_input = request.form.get("text", "").strip()
            lang = str(request.form.get("lang", "fr")).lower()
            file = request.files.get('file')

        if lang not in TEMPLATES:
            lang = "fr"

        final_content = user_input
        source_type = "plain_text"
        image_base64 = None

        if user_input and ("youtube.com" in user_input or "youtu.be" in user_input):
            transcript = extract_transcript(user_input)
            if transcript:
                final_content = transcript
                source_type = "video_transcript"

        if file:
            try:
                image_bytes = file.read()
                image_base64 = base64.b64encode(image_bytes).decode("utf-8")
                source_type = "image_file"
            except Exception as img_err:
                print(f"[Image Read Error]: {img_err}")

        if not final_content and not image_base64:
            return jsonify({
                "score": 0,
                "analysis": "Aucun contenu fourni / No content provided.",
                "source_type": source_type,
                "detected_flags": []
            }), 400

        local_penalty, local_flags = apply_local_rules(final_content)

        llm_score = 30
        detected_flags = list(local_flags)
        final_report = "Error: HF_TOKEN client not initialized."

        if client:
            prompt_user = f"Content to audit:\n{final_content if final_content else '[Image content attached]'}\nMandatory Output Language: {lang.upper()}"

            system_instruction = TEMPLATES[lang]["system"]

            messages = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt_user}
            ]

            try:
                response = client.chat.completions.create(
                    model="Qwen/Qwen2.5-Coder-32B-Instruct",
                    messages=messages,
                    max_tokens=1200
                )
                raw_text = response.choices[0].message.content

                score_match = re.search(r"<score>\s*(\d+)\s*</score>", raw_text, re.IGNORECASE)
                flags_match = re.search(r"<flags>(.*?)</flags>", raw_text, re.DOTALL | re.IGNORECASE)

                if score_match:
                    llm_score = int(score_match.group(1))
                    raw_text = re.sub(r"<score>\s*\d+\s*</score>", "", raw_text, flags=re.IGNORECASE)

                if flags_match:
                    parsed_flags = [f.strip().lower() for f in flags_match.group(1).split(",") if f.strip()]
                    detected_flags = list(set(detected_flags + parsed_flags))
                    raw_text = re.sub(r"<flags>.*?</flags>", "", raw_text, flags=re.IGNORECASE | re.DOTALL)

                final_report = raw_text.strip()

            except Exception as e:
                print(f"[HuggingFace API Error]: {e}")
                final_report = f"Audit Completed (Fallback mode). Error: {str(e)}"
                llm_score = 40
        else:
            final_report = "[DEMO MODE - Set HF_TOKEN in environment]"
            llm_score = 30
            detected_flags = ["authority_transfer", "psnc"]

        combined_score = max(0, min(100, llm_score + local_penalty))
        ethic_letter = get_ethic_letter(combined_score)

        save_audit("metacognitive_beacon", source_type, final_content or "Image Uploaded", combined_score, final_report)

        # Formateo ultra-limpio para evitar que las flags salgan pegadas
        formatted_flags_list = [f.upper() for f in detected_flags if f]
        formatted_flags_str = ", ".join(formatted_flags_list)

        return jsonify({
            "score": combined_score,
            "ethic_letter": ethic_letter,
            "analysis": final_report,
            "source_type": source_type,
            "detected_flags": formatted_flags_str
        }), 200

    except Exception as general_err:
        print(f"[Analyze Global Error]: {str(general_err)}")
        return jsonify({
            "score": 0,
            "ethic_letter": "A",
            "analysis": f"Internal Server Error: {str(general_err)}",
            "detected_flags": ""
        }), 500


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
        score = data.get("score", "0")
        analysis = data.get("analysis", "").replace("<br>", "\n").replace("<br/>", "\n")

        pdf_buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=letter,
            rightMargin=54, leftMargin=54,
            topMargin=54, bottomMargin=54
        )

        story = []
        try:
            numeric_score = int(re.sub(r"[^\d]", "", str(score)))
        except ValueError:
            numeric_score = 0

        if numeric_score >= 76:
            accent_color = colors.HexColor("#ff4d6d")
        elif numeric_score >= 51:
            accent_color = colors.HexColor("#f0883e")
        elif numeric_score >= 26:
            accent_color = colors.HexColor("#eab308")
        else:
            accent_color = colors.HexColor("#2ea44f")

        title_style = ParagraphStyle('DocTitle', fontName='Helvetica-Bold', fontSize=22, leading=26, textColor=colors.HexColor("#1e293b"))
        score_style = ParagraphStyle('ScoreDisplay', fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=accent_color)
        body_style = ParagraphStyle('ReportBody', fontName='Helvetica', fontSize=10, leading=15, textColor=colors.HexColor("#334155"))

        story.append(Paragraph("POLETHIC BEACON — FORENSIC REPORT", title_style))
        story.append(Paragraph(f"Ethic-Score™: {numeric_score}/100 (Grado {get_ethic_letter(numeric_score)})", score_style))
        story.append(Spacer(1, 15))

        for p_text in analysis.split('\n'):
            if p_text.strip():
                story.append(Paragraph(p_text.strip(), body_style))
                story.append(Spacer(1, 6))

        doc.build(story)
        pdf_buffer.seek(0)

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='Polethic_Beacon_Report.pdf'
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
