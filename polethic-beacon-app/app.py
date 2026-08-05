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
# SYSTEM PROMPT METACOGNITIVO ADAPTATIVO (FASE 0 ➔ FASE 3)
# =====================================================================
SYSTEM_PROMPT_BEACON = (
    "You are POLETHIC BEACON, an advanced Metacognitive Engine.\n"
    "Your objective is to execute a mandatory 4-Phase analysis pipeline for every input:\n\n"
    "FASE 0: RECONOCEDOR PRINCIPAL (Context & Taxonomy)\n"
    "- Identify Tipology: [Noticia, Personal/WhatsApp, Publicidad/Reel, CV, Científico, Filosófico, Teológico/Religioso, New Age].\n"
    "- Identify Emisor Purpose & Subjectivity (1-10).\n"
    "- Mode Selection:\n"
    "  * If Scientific: Activate BYPASS LÍMBICO (Evaluate methodology & evidence).\n"
    "  * If Philosophical/Literary: Activate CONCEPTUAL MODE (Evaluate premises & subtext).\n"
    "  * If Religious/Spiritual/New Age: Activate HERMENEUTIC/DECONSTRUCTION MODE (Evaluate internal coherence, dogmas, and pseudoscience).\n\n"
    "FASE 1: LIMPIEZA DE RUIDO\n"
    "- Strip clickbait, hyperbole, emotional blackmail, or fluff according to the text category.\n"
    "- Extract 2-4 core objective facts, claims, or premises.\n\n"
    "FASE 2: DESMONTAJE LÍMBICO (Intention & Bias Analysis)\n"
    "- Analyze emotional triggers (Fear, Guilt, FOMO, Estatus, Devotion).\n"
    "- Expose cognitive biases, fallacies, or unproven dogmas.\n\n"
    "FASE 3: TRADUCTEUR CORTICAL (Actionable Output)\n"
    "- Structure your final response into clear, objective sections.\n\n"
    "CRITICAL LANGUAGE RULE:\n"
    "Detect the language of the user input and write your entire response 100% in that target language.\n\n"
    "MANDATORY AUDIT OUTPUT FORMAT:\n"
    "🏷️ **1. CLASIFICACIÓN (Fase 0)**\n"
    "- Tipo de Texto:\n"
    "- Propósito del Emisor:\n\n"
    "📌 **2. NÚCLEO DE HECHOS / PREMISAS (Fase 1)**\n"
    "- Datos/Premisas filtrados sin ruido:\n\n"
    "🧠 **3. DESMONTAJE COGNITIVO Y LÍMBICO (Fase 2)**\n"
    "- Gatillo Emocional / Sesgo Detectado:\n"
    "- Intención vs. Realidad:\n\n"
    "🚀 **4. REENCUADRE CORTICAL Y ESTRATEGIA (Fase 3)**\n"
    "- Análisis objetivo final y recomendación de acción:\n\n"
    "<flags>[Comma-separated list from: fakenews, myth, bluff, coercion, dogma, pseudoscience]</flags>\n"
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
            prompt_user = f"Content to audit:\n{final_content if final_content else '[Image content attached]'}\nPreferred Language Code: {lang}"

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
            detected_flags = ["bluff", "myth"]

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
        lang = data.get("lang", "es")

        if not analysis:
            return jsonify({"refutation": "No content provided to counter-argue."}), 400

        # Detección de contenido sensible (Religión, Teología, New Age)
        is_religious_or_newage = any(
            k in analysis.lower() 
            for k in ["teológico", "religioso", "dios", "dogma", "new age", "vibración", "cuántica", "manifestación", "fe", "espiritual"]
        )

        disclaimer_text = ""
        if is_religious_or_newage:
            disclaimer_text = (
                "⚠️ **ADVERTENCIA DE ANÁLISIS CRÍTICO Y DECONSTRUCCIÓN**\n"
                "*Este módulo aplica principios de lógica formal, exégesis histórica y método científico. "
                "El resultado puede generar disonancia cognitiva al cuestionar dogmas o sistemas de creencia. "
                "La plataforma no se responsabiliza de la fricción emocional resultante de este análisis.* \n\n"
            )

        if client:
            prompt = (
                f"Basándote en este análisis previo:\n{analysis}\n\n"
                f"Actúa como un refutador metodológico e implacable. Genera exactamente 3 preguntas incómodas, "
                f"quirúrgicas y profundas para devolver la carga de la prueba al emisor o desmontar su axioma no probado.\n"
                f"Escribe la respuesta 100% en el idioma objetivo indicado por el código: '{lang}'."
            )
            response = client.chat.completions.create(
                model="Qwen/Qwen2.5-Coder-32B-Instruct",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500
            )
            refutation_text = response.choices[0].message.content.strip()
        else:
            refutation_text = (
                "1. ¿En qué estudio empírico o evidencia histórica independiente se basa esta afirmación?\n"
                "2. Si eliminamos el componente de fe o el uso metafórico de términos científicos, ¿qué hecho comprobable permanece?\n"
                "3. ¿Cómo se diferencia metodológicamente este postulado de otros dogmas contradictorios con la misma pretensión de verdad?"
            )

        full_response = f"{disclaimer_text}{refutation_text}"

        return jsonify({"refutation": full_response}), 200
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
