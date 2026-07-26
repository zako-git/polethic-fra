import os
import re
import sqlite3
import io
from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS  # Habilitar CORS
from huggingface_hub import InferenceClient
from youtube_transcript_api import YouTubeTranscriptApi
from PIL import Image
import pytesseract
from dotenv import load_dotenv

# --- Critical reportlab imports for the PDF engine ---
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# Load environment variables from .env
load_dotenv()

app = Flask(__name__)
CORS(app)  # Permite que tu botón conecte desde cualquier frontend/dominio

DATABASE_NAME = "beacon.db"

# Secure Token Configuration
HF_TOKEN = os.environ.get("HF_TOKEN")
client = InferenceClient(api_key=HF_TOKEN) if HF_TOKEN else None


def get_db_connection():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def extract_transcript(url):
    try:
        if "youtu.be/" in url:
            video_id = url.split("youtu.be/")[1].split("?")[0]
        else:
            video_id = url.split("v=")[1].split("&")[0]

        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'es'])
        return " ".join([t['text'] for t in transcript])
    except Exception as e:
        print(f"[extract_transcript] error: {e}")
        return None


def extract_text_from_image(file_storage):
    """Runs OCR on an uploaded image file and returns the extracted text."""
    try:
        image = Image.open(file_storage.stream)
        text = pytesseract.image_to_string(image, lang="eng+spa")
        return text.strip()
    except Exception as e:
        print(f"[extract_text_from_image] error: {e}")
        return None


def apply_local_rules(module_key, content):
    """
    Local deterministic layer. Scans the content for known risk keywords
    tied to the active module and returns a penalty total plus the list
    of matched flags, BEFORE the content is sent to the LLM layer.
    """
    flags = []
    penalty_total = 0

    if not content:
        return penalty_total, flags

    lowered_content = content.lower()

    # Keywords that require an accompanying commercial/coercive signal.
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
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
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

    # --- LAYER 1: Local deterministic rules ---
    local_penalty, local_flags = apply_local_rules(module, final_content)

    # --- LAYER 2: Asynchronous LLM synthesis ---
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
        # 1. BASE INSTRUCTIONS (Common to all modules)
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
            "- Replace '[number]' inside <score></score> with a single integer from 0 to 100. Never output a range.\n"
            "- Do NOT mention the score, letters (A, B, C, D, E), or ranges anywhere inside the <analysis> tags.\n"
            "- Map your score mentally to these threat levels, but ONLY output the final number inside the tags:\n"
            "  0-20: High Integrity / Low Risk (Letter A) -> USE THIS FOR LEGITIMATE SCIENCE/FACTS.\n"
            "  21-40: Moderate Bias / Attention Alert (Letter B)\n"
            "  41-60: Structural Risk / Pseudoscience (Letter C)\n"
            "  61-80: Severe Manipulation / High Risk (Letter D)\n"
            "  81-100: Critical Danger / Coercion (Letter E)\n\n"

            "CONTENT TYPE RECOGNITION & CALIBRATION:\n"
            "- DO NOT critique academic abstracts or scientific papers for using technical jargon (e.g., 'multiomic', 'RNA sequencing'). Technical vocabulary in science is mandatory.\n"
            "- CRITICAL: Only assign a penalty (Score C, D, or E) if you detect actual systemic threats or manipulation targeted by the active module.\n"
        )

        # 2. MODULE-SPECIFIC CRITERIA
        if module == "news":
            system_instructions += (
                "\n\nSPECIALIZED FAKENEWS CRITERIA (Polarization & Hype Tracking):\n"
                "Analyze the text for media manipulation tactics. Focus on:\n"
                "1. Epistemic Arrogance / Sensationalism: Using emotionally charged adjectives or hyperbole to inflate an event's significance.\n"
                "2. Outgroup Polarization: Us-vs-Them tribal framing designed to alienate a specific social, political, or cultural group.\n"
                "3. Manufacturing Consensus: Using unquantified assertions (e.g., 'Everyone knows', 'Experts agree') without sourcing direct data or empirical links.\n"
            )

        elif module == "myth":
            system_instructions += (
                "\n\nSPECIALIZED MYTH-BUSTER CRITERIA (Pseudoscience & Dogmatic Verification):\n"
                "Deconstruct pseudoscientific assertions or deep-seated cognitive errors. Focus on:\n"
                "1. Empirical Deficit: Scientific sounding claims that offer zero verifiable, biological, or physical mechanisms.\n"
                "2. Dogmatic Fallacies: Framing a hypothesis as absolute truth while aggressively attacking alternative peer-reviewed evidence.\n"
                "3. Commercialized Panaceas: Promoting unverified alternative healing methods paired directly with high-ticket programs, courses, or product sales.\n"
            )

        elif module == "identity_spoofing":
            system_instructions += (
                "\n\nSPECIALIZED IDENTITY SPOOFING CRITERIA (Professional Practice Intrusion - PPI Framework):\n"
                "Execute an aggressive forensic deconstruction of professional intrusion. Look for:\n"
                "1. Regulatory Arbitrage: Combining an unregulated noun ('analyst', 'coach') with a clinical adjective to mimic medical authority.\n"
                "2. Epistemological Inconsistency: Mixing evidence-based clinical terms (CBT/TCC) with mystical or speculative models (Psychoanalysis, Tarot, Numerology). If found, generate a clean Markdown Comparison Table breaking down the paradigm contradiction.\n"
                "3. The 'Trojan Horse' Strategy: Using validated acronyms as scientific bait, only to inject unscientific practices once trust is built.\n"
                "4. The 'No-Cure' Alibi (Semantic Shielding): Using defensive legal disclaimers ('I only analyze, I do not treat') to avoid malpractice liability while maintaining a therapeutic aesthetic.\n"
            )

        elif module == "coercion":
            system_instructions += (
                "\n\nSPECIALIZED COERCIVE FILTER CRITERIA (Steven Hassan's BITE Model):\n"
                "Deconstruct the text against the BITE Model of authoritarian manipulation and coercive control. Identify which specific dimension is being actively exploited:\n"
                "1. Behavior Control: Mandating rigid lifestyle demands, punishing individuality, or restricting time and baseline autonomy.\n"
                "2. Information Control: Deliberately limiting access to counter-evidence, using deception, or framing external critiques as 'evil/attacks'.\n"
                "3. Thought Control: Utilizing loaded language, thought-terminating clichés, or binary 'Us vs. Them' filtering to halt rational processing.\n"
                "4. Emotional Control: Utilizing systematic guilt, fear appeals, phobia indoctrination (e.g., 'If you leave us, you will lose everything/be destroyed'), or love-bombing dependency.\n"
                "When a BITE component is present, explicitly name it and break down its structural psychological danger.\n"
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
                fallback_score = re.search(r"SCORE:\s*(\d+)", raw_text, re.IGNORECASE)
                if fallback_score:
                    llm_score = int(fallback_score.group(1))
                    final_report = re.sub(r"SCORE:\s*\d+\n*", "", raw_text, flags=re.IGNORECASE).strip()
                else:
                    llm_score = None
                    final_report = raw_text + "\n\n[WARNING: Response parsing structure failed.]"

        except Exception as e:
            final_report = f"Analytical Error during Hugging Face forensic compilation: {str(e)}"
            llm_score = 100

    if llm_score is None:
        combined_score = None
    else:
        combined_score = max(0, min(100, llm_score + local_penalty))

    if local_flags:
        flags_summary = "\n\n---\nLocal Pattern Flags Detected:\n" + "\n".join(
            f"- \"{f['keyword']}\" → {f['category']} (+{f['penalty']} risk pts)" for f in local_flags
        )
        final_report += flags_summary

    save_audit(module, source_type, final_content, combined_score if combined_score is not None else -1, final_report)

    return jsonify({
        "score": combined_score,
        "analysis": final_report,
        "source_type": source_type,
        "local_flags": local_flags
    })


@app.route("/export_pdf", methods=["POST"])
def export_pdf():
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
    styles = getSampleStyleSheet()

    try:
        numeric_score = int(score)
    except ValueError:
        numeric_score = 0

    def get_ethic_letter(value):
        if value <= 20:
            return "A"
        if value <= 40:
            return "B"
        if value <= 60:
            return "C"
        if value <= 80:
            return "D"
        return "E"

    ethic_letter = get_ethic_letter(numeric_score)

    if numeric_score >= 81:
        accent_color = colors.HexColor("#ff4d6d")
    elif numeric_score >= 41:
        accent_color = colors.HexColor("#f0883e")
    else:
        accent_color = colors.HexColor("#2ea44f")

    title_style = ParagraphStyle(
        'DocTitle',
        fontName='Helvetica-Bold',
        fontSize=26,
        leading=30,
        textColor=colors.HexColor("#f0f6fc"),
        spaceAfter=4
    )

    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=14,
        textColor=colors.HexColor("#8b949e"),
        spaceAfter=10
    )

    score_style = ParagraphStyle(
        'ScoreDisplay',
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=26,
        textColor=accent_color,
        spaceAfter=22
    )

    section_heading = ParagraphStyle(
        'SectionHeading',
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        textColor=accent_color,
        spaceBefore=22,
        spaceAfter=12,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'ReportBody',
        fontName='Helvetica',
        fontSize=10.5,
        leading=18,
        textColor=colors.HexColor("#c9d1d9"),
        spaceAfter=14
    )

    protocol_style = ParagraphStyle(
        'ProtocolStyle',
        fontName='Helvetica',
        fontSize=10,
        leading=16,
        textColor=colors.HexColor("#8b949e"),
        spaceAfter=6
    )

    def format_verdict_tags(text):
        if not text:
            return ""
        text = re.sub(r'("(.*?)")', r'<b>\1</b>', text)
        keywords = ["coercion", "bias", "manipulation", "unverified scientific claims", "coercive group", "inflated", "coercivo", "manipulación", "pseudociencia"]
        for kw in keywords:
            text = re.compile(re.escape(kw), re.IGNORECASE).sub(f"<b>{kw}</b>", text)
        return text

    story.append(Paragraph("POLETHIC BEACON", title_style))
    story.append(Paragraph("REPORT", subtitle_style))
    story.append(Paragraph(f"Ethic-Score™: [{ethic_letter}]", score_style))

    story.append(Paragraph("1. RAW AUDIT VERDICT", section_heading))

    paragraphs = analysis.split('\n')
    for p_text in paragraphs:
        clean_text = p_text.strip()
        if clean_text:
            formatted_text = format_verdict_tags(clean_text)
            story.append(Paragraph(formatted_text, body_style))

    story.append(Paragraph("2. COGNITIVE SELF-DEFENSE PROTOCOL", section_heading))
    story.append(Paragraph("• <b>Objective:</b> Objective system analysis. We isolate structural data and reduce noise.", protocol_style))
    story.append(Paragraph("• <b>Action:</b> Separate emotional hooks from the statement. Cross-verify with empirical data.", protocol_style))
    story.append(Paragraph("• <b>Control:</b> Identify cognitive patterns and syntactic structures without judging intent.", protocol_style))

    def draw_background(canvas, document):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#0d1117"))
        canvas.rect(0, 0, document.pagesize[0], document.pagesize[1], fill=True, stroke=False)

        canvas.setStrokeColor(accent_color)
        canvas.setLineWidth(3)
        canvas.line(54, document.pagesize[1] - 30, document.pagesize[0] - 54, document.pagesize[1] - 30)
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_background, onLaterPages=draw_background)
    pdf_buffer.seek(0)

    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='Polethic_Beacon_Report.pdf'
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
