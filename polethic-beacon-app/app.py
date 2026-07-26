import os
import re
import sqlite3
import io
from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
from huggingface_hub import InferenceClient
from youtube_transcript_api import YouTubeTranscriptApi
from PIL import Image
import pytesseract
from dotenv import load_dotenv

# --- Critical reportlab imports for the PDF engine ---
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

DATABASE_NAME = "beacon.db"

# Secure Token Configuration
HF_TOKEN = os.environ.get("HF_TOKEN")
client = InferenceClient(api_key=HF_TOKEN) if HF_TOKEN else None


def get_db_connection():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Inicializa la base de datos y crea las tablas e índices si no existen."""
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


def extract_text_from_image(file_storage):
    """Runs OCR on an uploaded image file and returns the extracted text."""
    try:
        image = Image.open(file_storage.stream)
        text = pytesseract.image_to_string(image, lang="eng+spa+fra")
        return text.strip()
    except Exception as e:
        print(f"[extract_text_from_image] error: {e}")
        return None


def apply_local_rules(module_key, content):
    flags = []
    penalty_total = 0

    if not content:
        return penalty_total, flags

    lowered_content = content.lower()

    CONTEXT_GATED_KEYWORDS = {
        "trauma bond",
        "shadow work",
        "trabajo de sombra",
        "reparent your inner child",
    }

    COMMERCIAL_CONTEXT_SIGNALS = [
        "program", "programa", "course", "curso", "buy now", "compra ahora",
        "sign up", "apúntate", "exclusive method", "método exclusivo",
        "in just", "en solo", "limited offer", "oferta limitada",
        "coaching", "bootcamp", "masterclass", "invierte", "invest now"
    ]

    try:
        conn = get_db_connection()
        rules = conn.execute(
            "SELECT keyword, risk_category, penalty_points FROM local_rules WHERE module_key = ?",
            (module_key,)
        ).fetchall()
        conn.close()

        has_commercial_context = any(signal in lowered_content for signal in COMMERCIAL_CONTEXT_SIGNALS)

        for rule in rules:
            keyword_lower = rule["keyword"].lower()
            if keyword_lower not in lowered_content:
                continue

            if keyword_lower in CONTEXT_GATED_KEYWORDS and not has_commercial_context:
                continue

            penalty_total += rule["penalty_points"]
            flags.append({
                "keyword": rule["keyword"],
                "category": rule["risk_category"],
                "penalty": rule["penalty_points"]
            })
    except Exception as e:
        print(f"[apply_local_rules] Warning/Skipped: {e}")

    return penalty_total, flags


def save_audit(module_key, source_type, raw_content, ethic_score, diagnostic_report):
    try:
        conn = get_db_connection()
        conn.execute(
            """INSERT INTO audits (module_key, source_type, raw_content, ethic_score, diagnostic_report)
               VALUES (?, ?, ?, ?, ?)""",
            (module_key, source_type, raw_content, ethic_score, diagnostic_report)
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

        if user_input and ("youtube.com" in user_input or "youtu.be" in user_input):
            transcript = extract_transcript(user_input)
            if transcript:
                final_content = transcript
                source_type = "video_transcript"

        if file:
            ocr_text = extract_text_from_image(file)
            if ocr_text:
                final_content = ocr_text
                source_type = "image_screenshot"
            else:
                return jsonify({
                    "score": 0,
                    "analysis": "The image was received, but no readable text could be extracted from it (OCR failed).",
                    "source_type": "image_screenshot",
                    "local_flags": []
                })

        if not final_content:
            return jsonify({
                "score": 0,
                "analysis": "No content was provided to analyze.",
                "source_type": source_type,
                "local_flags": []
            })

        # LAYER 1: Local deterministic rules
        local_penalty, local_flags = apply_local_rules(module, final_content)

        # LAYER 2: LLM synthesis
        llm_score = 0
        final_report = "Error: Analytical engine unable to process request. Check HF_TOKEN configuration."

        module_names = {
            "news": "FakeNews (Polarization & Hype Tracking)",
            "myth": "Myth-Buster (Pseudoscience & Dogmatic Verification)",
            "identity_spoofing": "Identity Spoofing (Inflated Credentials & Professional Intrusion)",
            "coercion": "Coercive Filter (Information Control & Predatory Rhetoric)"
        }
        formal_module_name = module_names.get(module, "General Content Audit")

        if client:
            system_instructions = (
                f"You are POLETHIC BEACON, a cognitive self-defense expert auditing content for the active specialized module: '{formal_module_name}'.\n"
                "Your core task is to critically analyze the provided text and identify actual ethical threats, structural risks, pseudoscience, or manipulation.\n\n"
                "LANGUAGE REQUIREMENT:\n"
                "Always write your ENTIRE response in English, regardless of the language of the submitted content.\n\n"
                "OUTPUT FORMAT RULES (STRICT):\n"
                "You MUST wrap your analysis inside the following XML-like tags. Do not add any text outside of these tags.\n"
                "Format your output exactly like this:\n"
                "<analysis>\n"
                "Provide your forensic text analysis here in clean paragraphs. Point out specific issues if they exist.\n"
                "</analysis>\n"
                "<score>[number]</score>\n\n"
                "CRITICAL SCORE INSTRUCTIONS:\n"
                "- Replace '[number]' inside <score></score> with a single integer from 0 to 100.\n"
                "- Map your score mentally: 0-20 (Safe/A), 21-40 (B), 41-60 (C), 61-80 (D), 81-100 (E/Dangerous).\n"
            )

            messages = [
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": f"Content to audit:\n{final_content}"}
            ]

            try:
                response = client.chat.completions.create(
                    model="meta-llama/Meta-Llama-3-8B-Instruct",
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
                    report_clean = re.sub(r"<analysis>", "", raw_text, flags=re.IGNORECASE)
                    report_clean = re.sub(r"<score>.*?</score>", "", report_clean, flags=re.DOTALL | re.IGNORECASE)
                    final_report = report_clean.strip()
                else:
                    llm_score = 35
                    final_report = raw_text

            except Exception as e:
                print(f"[HuggingFace API Error]: {e}")
                final_report = f"Audit Completed (Fallback mode): Analysis processed. Details: {str(e)}"
                llm_score = 40
        else:
            final_report = f"[DEMO AUDIT MODE - Set HF_TOKEN in environment]\nAnalyzed input under module '{formal_module_name}'.\nDetected potential structural or rhetorical manipulation."
            llm_score = 30

        if llm_score is None:
            combined_score = 0
        else:
            combined_score = max(0, min(100, llm_score + local_penalty))

        if local_flags:
            flags_summary = "\n\n---\nLocal Pattern Flags Detected:\n" + "\n".join(
                f"- \"{f['keyword']}\" → {f['category']} (+{f['penalty']} risk pts)" for f in local_flags
            )
            final_report += flags_summary

        save_audit(module, source_type, final_content, combined_score, final_report)

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
            numeric_score = int(score)
        except ValueError:
            numeric_score = 0

        def get_ethic_letter(value):
            if value <= 20: return "A"
            if value <= 40: return "B"
            if value <= 60: return "C"
            if value <= 80: return "D"
            return "E"

        ethic_letter = get_ethic_letter(numeric_score)
        accent_color = colors.HexColor("#ff4d6d") if numeric_score >= 81 else (colors.HexColor("#f0883e") if numeric_score >= 41 else colors.HexColor("#2ea44f"))

        title_style = ParagraphStyle('DocTitle', fontName='Helvetica-Bold', fontSize=22, leading=26, textColor=colors.HexColor("#1e293b"))
        score_style = ParagraphStyle('ScoreDisplay', fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=accent_color)
        body_style = ParagraphStyle('ReportBody', fontName='Helvetica', fontSize=10, leading=15, textColor=colors.HexColor("#334155"))

        story.append(Paragraph("POLETHIC BEACON — FORENSIC REPORT", title_style))
        story.append(Paragraph(f"Ethic-Score™: [{ethic_letter}] ({numeric_score}/100)", score_style))
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


# Inicializar base de datos al arrancar
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
