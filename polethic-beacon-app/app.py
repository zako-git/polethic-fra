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
# Permitir peticiones desde cualquier origen (CORS)
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
            system_instructions = (
                "You are POLETHIC BEACON, an advanced Metacognitive Defense Engine.\n\n"
                "THEORETICAL FRAMEWORKS:\n"
                "1. PREDICTIVE BRAIN (Lisa Feldman Barrett)\n"
                "2. THE MIND IS FLAT (Nick Chater)\n"
                "3. BITE MODEL OF COERCIVE CONTROL (Steven Hassan)\n\n"
                "CRITICAL LANGUAGE RULE:\n"
                f"Respond 100% in the target language specified: '{lang}'.\n\n"
                "MANDATORY AUDIT OUTPUT FORMAT:\n"
                "### 1. DIAGNÓSTICO TÉCNICO\n"
                "- Análisis de Hechos/Contenido:\n"
                "- Sesgos y Falacias:\n"
                "- Táctica de Manipulación:\n\n"
                "### 2. REGLAMENTO DIALÉCTICO\n"
                "- ⚽ Falta Cometida:\n"
                "- ⚖️ Carga de la Prueba:\n"
                "- 🛡️ Respuesta Escudo:\n\n"
                "### 3. ESTRATEGIA DE DEFENSA\n"
                "- Pasos de autodefensa.\n\n"
                "<flags>[Lista separada por comas de las categorías detectadas ÚNICAMENTE entre: fakenews, myth, bluff, coercion]</flags>\n"
                "<score>[Número entero de 0 a 100]</score>"
            )

            prompt_user = f"Content to audit:\n{final_content if final_content else '[Image content attached]'}"

            messages = [
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": prompt_user}
            ]

            try:
                response = client.chat.completions.create(
                    model="Qwen/Qwen2.5-Coder-32B-Instruct",
                    messages=messages,
                    max_tokens=1000
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

        save_audit("auto_beacon", source_type, final_content or "Image Uploaded", combined_score, final_report)

        return jsonify({
            "score": combined_score,
            "ethic_letter": ethic_letter,
            "analysis": final_report,
            "source_type": source_type,
            "detected_flags": detected_flags
        }), 200

    except Exception as general_err:
        return jsonify({
            "score": 0,
            "ethic_letter": "A",
            "analysis": f"Internal Server Error: {str(general_err)}",
            "detected_flags": []
        }), 500

        # Reglas locales de coincidencia de texto
        local_penalty, local_flags = apply_local_rules(module, final_content)

        module_names = {
            "news": "FakeNews (Polarization & Hype Tracking)",
            "myth": "Myth-Buster (Pseudoscience & Dogmatic Verification)",
            "identity": "Identity Spoofing (Inflated Credentials)",
            "coercive": "Coercive Filter (Information Control & Predatory Rhetoric)"
        }
        formal_module_name = module_names.get(module, "General Content Audit")

        llm_score = 30
        final_report = "Error: HF_TOKEN client not initialized."

        if client:
            system_instructions = (
    "You are POLETHIC BEACON, an advanced Metacognitive Defense Engine and Relational Shield.\n"
    f"Active Module: '{formal_module_name}'.\n\n"
    "THEORETICAL & CLINICAL FRAMEWORKS:\n"
    "1. PREDICTIVE BRAIN (Lisa Feldman Barrett): Identify how the message triggers emotional prediction errors or forced allostatic load.\n"
    "2. THE MIND IS FLAT (Nick Chater): Unmask superficial depth, inflated credentials, and ungrounded dogmas.\n"
    "3. BITE MODEL OF COERCIVE CONTROL (Steven Hassan): Analyze Behavioral, Informational, Thought, and Emotional manipulation. Explicitly identify DOUBLE BINDS and gaslighting.\n\n"
    "REGLA CRÍTICA DE IDIOMA:\n"
    "Detecta automáticamente el idioma del contenido recibido. Escribe TU RESPUESTA COMPLETA EN ESE MISMO IDIOMA (si la entrada es en español, responde 100% en español).\n\n"
    "REGLAS STRICTAS DE FORMATO:\n"
    "<analysis>\n"
    "A. DETECTOR DE SESGOS Y MANIPULACIÓN COERCITIVA (Modelo BITE / Trampa de comunicación)\n"
    "B. VERIFICACIÓN DE EVIDENCIA Y RIGOR (Calidad de afirmaciones o datos)\n"
    "C. REFUTACIÓN Y DESMONTAJE DE CÁMARAS DE ECO (La otra cara fundada)\n"
    "D. CARGA METABÓLICA Y ESTRATEGIA DE SALIDA (Pasos concretos de autodefensa y comunicación)\n"
    "</analysis>\n"
    "<score>[número de 0 a 100 donde 100 es PELIGRO MÁXIMO / COERCIÓN y 0 es saludable]</score>"
)

            prompt_user = f"Content to audit:\n{final_content if final_content else '[Image content attached]'}"

            messages = [
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": prompt_user}
            ]

            try:
                # Usamos un modelo universalmente activo en la Inference API de HF
                response = client.chat.completions.create(
                    model="Qwen/Qwen2.5-Coder-32B-Instruct",  # O "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B"
                    messages=messages,
                    max_tokens=1000
                )
                raw_text = response.choices[0].message.content

                score_match = re.search(r"<score>\s*(\d+)\s*</score>", raw_text, re.IGNORECASE)
                analysis_match = re.search(r"<analysis>(.*?)</analysis>", raw_text, re.DOTALL | re.IGNORECASE)

                if analysis_match and score_match:
                    llm_score = int(score_match.group(1))
                    final_report = analysis_match.group(1).strip()
                elif score_match:
                    llm_score = int(score_match.group(1))
                    final_report = raw_text
                else:
                    llm_score = 35
                    final_report = raw_text

            except Exception as e:
                print(f"[HuggingFace API Error]: {e}")
                final_report = f"Audit Completed (Fallback mode). Error details: {str(e)}"
                llm_score = 40
        else:
            final_report = f"[DEMO MODE - Set HF_TOKEN in environment]\nAnalyzed input under module '{formal_module_name}'."
            llm_score = 30

        combined_score = max(0, min(100, llm_score + local_penalty))

        if local_flags:
            flags_summary = "\n\n---\nLocal Pattern Flags Detected:\n" + "\n".join(
                f"- \"{f['keyword']}\" → {f['category']} (+{f['penalty']} risk pts)" for f in local_flags
            )
            final_report += flags_summary

        save_audit(module, source_type, final_content or "Image Uploaded", combined_score, final_report)

        return jsonify({
            "score": combined_score,
            "analysis": final_report,
            "source_type": source_type,
            "local_flags": local_flags
        }), 200

    except Exception as general_err:
        print(f"[Analyze Global Error]: {str(general_err)}")
        return jsonify({
            "score": 0,
            "analysis": f"Internal Server Error: {str(general_err)}"
        }), 500


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

        accent_color = colors.HexColor("#ff4d6d") if numeric_score >= 81 else (colors.HexColor("#f0883e") if numeric_score >= 41 else colors.HexColor("#2ea44f"))

        title_style = ParagraphStyle('DocTitle', fontName='Helvetica-Bold', fontSize=22, leading=26, textColor=colors.HexColor("#1e293b"))
        score_style = ParagraphStyle('ScoreDisplay', fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=accent_color)
        body_style = ParagraphStyle('ReportBody', fontName='Helvetica', fontSize=10, leading=15, textColor=colors.HexColor("#334155"))

        story.append(Paragraph("POLETHIC BEACON — FORENSIC REPORT", title_style))
        story.append(Paragraph(f"Ethic-Score™: {numeric_score}/100", score_style))
        story.append(Spacer(1, 15))

        for p_text in analysis.split('\n'):
            if p_text.strip():
                story.append(Paragraph(p_text.strip(), body_style))
                story.append(Spacer(1, 6))
                # En app.py -> ruta /export_pdf
if numeric_score >= 76:
    accent_color = colors.HexColor("#ff4d6d") # Rojo (Peligro Alto / Letra D)
elif numeric_score >= 51:
    accent_color = colors.HexColor("#f0883e") # Naranja (Letra C)
elif numeric_score >= 26:
    accent_color = colors.HexColor("#eab308") # Amarillo / Azul (Letra B)
else:
    accent_color = colors.HexColor("#2ea44f") # Verde (Limpio / Letra A)

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
