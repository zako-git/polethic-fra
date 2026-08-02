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

        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'es', 'fr'])
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
# SYSTEM PROMPT METACOGNITIVO ADAPTATIVO (SIN NÚMEROS EN SECCIONES)
# =====================================================================
SYSTEM_PROMPT_BEACON = (
    "You are POLETHIC BEACON, an advanced Forensic Metacognitive Engine.\n"
    "Your objective is to execute a mandatory 4-Phase analysis pipeline for every input:\n\n"
    "FASE 0: RECONOCEDOR PRINCIPAL (Taxonomía y Contexto)\n"
    "- Identify Typology: [Noticia, Personal/WhatsApp, Publicidad/Reel, CV/Perfil Profesional, Científico, Filosófico, Teológico, New Age/PSNC].\n"
    "- Identify Emisor Purpose and Strategy.\n"
    "- EVALUATION GUIDELINES:\n"
    "  * If text introduces Non-Conventional Therapies (PSNC/Sophrology) linked to medical/public institutions or severe diseases (AVC, Chronic Diseases), evaluate authority transfer and give an Ethic-Score in range 55-75 (Grade C).\n"
    "  * If text is a clean CV without unproven claims or coercion, assign Range 0-25 (Grade A).\n\n"
    "FASE 1: LIMPIEZA DE RUIDO\n"
    "- Strip emotional fluff, hyperbole, and decorative prose.\n"
    "- Extract 2-4 core objective facts and explicit claims.\n\n"
    "FASE 2: DESMONTAJE LÍMBICO (Análisis de Estrategia y Sesgos)\n"
    "- Unmask the real rhetorical strategy: Authority Transfer, Clinical Euphemisms, Emotional Exploitation of Vulnerable Patients, False Dichotomy, etc.\n"
    "- ABSOLUTE RULE: DO NOT INVENT BIASES OR CONCEPTS NOT PRESENT IN THE TEXT (e.g., do not mention quantum physics, hypnosis, or commercial rush if not mentioned in input).\n\n"
    "FASE 3: TRADUCTEUR CORTICAL\n"
    "- Provide an objective cortical summary and actionable risk assessment.\n\n"
    "CRITICAL LANGUAGE RULE:\n"
    "Detect the input language and write the ENTIRE response (including section headings) 100% in that target language.\n\n"
    "MANDATORY OUTPUT FORMAT (NO NUMBERS IN HEADINGS):\n"
    "🏷️ **CLASIFICACIÓN (Fase 0)**\n"
    "- Tipo de Texto:\n"
    "- Propósito del Emisor:\n\n"
    "📌 **NÚCLEO DE HECHOS / PREMISAS (Fase 1)**\n"
    "- Datos y afirmaciones filtradas sin ruido:\n\n"
    "🧠 **DESMONTAJE COGNITIVO Y LÍMBICO (Fase 2)**\n"
    "- Estrategia Retórica / Gatillo Detectado:\n"
    "- Intención vs. Realidad (Análisis de Blanqueamiento/Apropiación de Lenguaje):\n\n"
    "🚀 **REENCUADRE CORTICAL Y ESTRATEGIA (Fase 3)**\n"
    "- Diagnóstico sintético final y valoración objetiva de riesgo:\n\n"
    "<flags>[Comma-separated list from: fakenews, myth, bluff, coercion, dogma, pseudoscience, authority_transfer, psnc]</flags>\n"
    "<score>[Integer score from 0 (Healthy) to 100 (High Risk/Coercion)]</score>"
)


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        lang = "fr"
        if request.is_json:
            data = request.get_json() or {}
            user_input = data.get("text", "").strip()
            lang = data.get("lang", "fr")
            file = None
        else:
            user_input = request.form.get("text", "").strip()
            lang = request.form.get("lang", "fr")
            file = request.files.get('file')

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
                "analysis": "No content provided.",
                "source_type": source_type,
                "detected_flags": []
            }), 400

        local_penalty, local_flags = apply_local_rules(final_content)

        llm_score = 30
        detected_flags = list(local_flags)
        final_report = "Error: HF_TOKEN client not initialized."

        if client:
            prompt_user = f"Content to audit:\n{final_content if final_content else '[Image content attached]'}\nTarget Language Code: {lang}"

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT_BEACON},
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
            detected_flags = ["bluff", "authority_transfer"]

        combined_score = max(0, min(100, llm_score + local_penalty))
        ethic_letter = get_ethic_letter(combined_score)

        save_audit("metacognitive_beacon", source_type, final_content or "Image Uploaded", combined_score, final_report)

        return jsonify({
            "score": combined_score,
            "ethic_letter": ethic_letter,
            "analysis": final_report,
            "source_type": source_type,
            "detected_flags": detected_flags
        }), 200

    except Exception as general_err:
        print(f"[Analyze Global Error]: {str(general_err)}")
        return jsonify({
            "score": 0,
            "ethic_letter": "A",
            "analysis": f"Internal Server Error: {str(general_err)}",
            "detected_flags": []
        }), 500


@app.route("/refute", methods=["POST"])
def refute():
    try:
        data = request.get_json() or {}
        analysis = data.get("analysis", "")
        lang = data.get("lang", "fr")

        if not analysis:
            return jsonify({"refutation": "No content provided to counter-argue."}), 400

        if client:
            prompt = (
                f"Analisi forense previa:\n{analysis}\n\n"
                f"Consigne: Genera exactamente 3 preguntas quirúrgicas de refutación o deconstrucción metodológica "
                f"basándote ÚNICAMENTE en las afirmaciones y estrategias identificadas en el análisis previo.\n"
                f"REGLA DE ORO: ESTÁ STRICTAMENTE PROHIBIDO inventar o mencionar términos que no existan en la entrada "
                f"(por ejemplo, no hables de física cuántica, hipnosis, ni urgencia comercial salvo que se mencionen explícitamente).\n"
                f"Concéntrate en cuestionar la evidencia científica, el marco legal, la transferencia de autoridad o la eficacia clínica.\n"
                f"Escribe la respuesta 100% en el idioma objetivo indicado por el código: '{lang}'."
            )
            response = client.chat.completions.create(
                model="Qwen/Qwen2.5-Coder-32B-Instruct",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=450
            )
            refutation_text = response.choices[0].message.content.strip()
        else:
            refutation_text = (
                "1. ¿Qué evidencia clínica objetiva respalda esta aproximación frente a las terapias médicas convencionales?\n"
                "2. ¿Cómo se delimita el alcance ético entre el acompañamiento no convencional y el tratamiento médico estricto?\n"
                "3. ¿Bajo qué indicadores métricos se mide la efectividad del tratamiento en los pacientes?"
            )

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
