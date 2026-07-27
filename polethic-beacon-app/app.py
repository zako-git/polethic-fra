import os
import re
import sqlite3
import io
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
from PIL import Image
from dotenv import load_dotenv

# Importaciones para el motor de PDF
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors

# API de Google Gemini (Multimodal nativo)
from google import genai

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

DATABASE_NAME = "beacon.db"

# Inicialización de Gemini Client
gemini_api_key = os.environ.get("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=gemini_api_key) if gemini_api_key else None


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


def apply_local_rules(module_key, content):
    flags = []
    penalty_total = 0
    if not content or not isinstance(content, str):
        return penalty_total, flags

    lowered_content = content.lower()
    try:
        conn = get_db_connection()
        rules = conn.execute(
            "SELECT keyword, risk_category, penalty_points FROM local_rules WHERE module_key = ?",
            (module_key,)
        ).fetchall()
        conn.close()

        for rule in rules:
            if rule["keyword"].lower() in lowered_content:
                penalty_total += rule["penalty_points"]
                flags.append({
                    "keyword": rule["keyword"],
                    "category": rule["risk_category"],
                    "penalty": rule["penalty_points"]
                })
    except Exception as e:
        print(f"[apply_local_rules] Warning: {e}")

    return penalty_total, flags


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


@app.route("/")
def index():
    return jsonify({"status": "online", "message": "POLETHIC BEACON API Running"}), 200


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        # Petición JSON o FormData
        if request.is_json:
            data = request.get_json() or {}
            user_input = data.get("text", "").strip()
            module = data.get("module", "news")
            file = None
        else:
            user_input = request.form.get("text", "").strip()
            module = request.form.get("module", "news")
            file = request.files.get('file')

        final_content = user_input
        source_type = "plain_text"
        image_obj = None

        # Procesar YouTube
        if user_input and ("youtube.com" in user_input or "youtu.be" in user_input):
            transcript = extract_transcript(user_input)
            if transcript:
                final_content = transcript
                source_type = "video_transcript"

        # Procesar Imagen con Pillow (Sin necesidad de Tesseract)
        if file:
            try:
                image_obj = Image.open(io.BytesIO(file.read()))
                source_type = "image_file"
            except Exception as img_err:
                print(f"Error procesando imagen: {img_err}")

        if not final_content and not image_obj:
            return jsonify({
                "score": 0,
                "analysis": "No content or image was provided to analyze.",
                "source_type": source_type,
                "local_flags": []
            }), 400

        # Reglas locales si hay texto
        local_penalty, local_flags = apply_local_rules(module, final_content if isinstance(final_content, str) else "")

        # Análisis con Gemini (Multimodal: Texto + Imagen)
        llm_score = 30
        final_report = ""

        module_names = {
            "news": "FakeNews (Polarization & Hype Tracking)",
            "myth": "Myth-Buster (Pseudoscience & Dogmatic Verification)",
            "identity": "Identity Spoofing (Inflated Credentials)",
            "coercive": "Coercive Filter (Information Control & Predatory Rhetoric)"
        }
        formal_module_name = module_names.get(module, "General Content Audit")

        if gemini_client:
            prompt_system = (
                f"You are POLETHIC BEACON, a cognitive self-defense expert auditing content for module: '{formal_module_name}'.\n"
                "Analyze the provided text and/or image content and identify actual ethical threats, structural risks, pseudoscience, or manipulation.\n\n"
                "LANGUAGE REQUIREMENT: Always write your ENTIRE response in English.\n\n"
                "OUTPUT FORMAT RULES (STRICT):\n"
                "Wrap your output in XML tags like this:\n"
                "<analysis>\nWrite your forensic analysis here in clear paragraphs.\n</analysis>\n"
                "<score>[number from 0 to 100]</score>"
            )

            contents = [prompt_system]
            if final_content:
                contents.append(f"Text content:\n{final_content}")
            if image_obj:
                contents.append(image_obj)

            try:
                response = gemini_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=contents
                )
                raw_text = response.text

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
                print(f"[Gemini API Error]: {e}")
                final_report = f"Audit Completed (Fallback mode). Error: {str(e)}"
                llm_score = 40
        else:
            final_report = f"[DEMO AUDIT MODE - Set GEMINI_API_KEY in environment]\nAnalyzed input under module '{formal_module_name}'."
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
