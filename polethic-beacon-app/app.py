import os
import re
import io
import sqlite3
import unicodedata
from datetime import datetime
from flask import Flask, jsonify, request, send_file, render_template
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

# Importaciones para generación de PDF
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors

app = Flask(__name__)
CORS(app)

DATABASE = os.path.join(os.path.dirname(__file__), 'beacon.db')

def get_db_connection():
    """Conexión rápida a tu base de datos SQLite (beacon.db)"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# =====================================================================
# DICCIONARIOS DE TRADUCCIÓN DE FLAGS
# =====================================================================
FLAG_TRANSLATIONS = {
    "es": {
        "fakenews": "NOTICIA FALSA", "myth": "MITO", "bluff": "MARKETING / HYPE",
        "coercion": "COERCION", "dogma": "DOGMA", "pseudoscience": "SEUDOCIENCIA",
        "authority_transfer": "TRANSFERENCIA AUTORIDAD", "psnc": "SESGO COGNITIVO",
        "persuasif": "PERSUASIVO", "marketing": "MARKETING", "biais leger": "SESGO LEVE",
        "promesse": "PROMESA"
    },
    "fr": {
        "fakenews": "FAUX BRUIT", "myth": "MYTHE", "bluff": "BLUFF / HYPE",
        "coercion": "COERCITION", "dogma": "DOGME", "pseudoscience": "PSEUDOSCIENCE",
        "authority_transfer": "TRANSFERT D'AUTORITÉ", "psnc": "BIAIS COGNITIF",
        "persuasif": "PERSUASIF", "marketing": "MARKETING", "biais leger": "BIAIS LÉGER",
        "promesse": "PROMESSE"
    },
    "en": {
        "fakenews": "FAKE NEWS", "myth": "MYTH", "bluff": "BLUFF / HYPE",
        "coercion": "COERCION", "dogma": "DOGMA", "pseudoscience": "PSEUDOSCIENCE",
        "authority_transfer": "AUTHORITY TRANSFER", "psnc": "COGNITIVE BIAS",
        "persuasif": "PERSUASIVE", "marketing": "MARKETING", "biais leger": "LIGHT BIAS",
        "promesse": "PROMISE"
    }
}

def get_ethic_letter(score):
    if score >= 85: return "A"
    if score >= 65: return "B"
    if score >= 40: return "C"
    return "D"

def translate_flags(flags_list, lang="fr"):
    lang_dict = FLAG_TRANSLATIONS.get(lang.lower(), FLAG_TRANSLATIONS["fr"])
    return [lang_dict.get(f.strip().lower(), f.strip().upper()) for f in flags_list]

def sanitize_for_pdf(text):
    if not text: return ""
    text = text.replace("**", "").replace("<", "&lt;").replace(">", "&gt;")
    normalized = unicodedata.normalize('NFKD', text)
    return normalized.encode('ascii', 'ignore').decode('utf-8')

def is_heading_line(line):
    line_upper = line.strip().upper()
    keywords = [
        "FASE", "PHASE", "NÚCLEO DE HECHOS", "NOYAU DE FAITS", "CORE FACTS",
        "DESMONTAJE COGNITIVO", "DÉMONTAGE COGNITIF", "COGNITIVE DECONSTRUCTION",
        "REENCUADRE CORTICAL", "RECADRAGE CORTICAL", "CORTICAL REFRAMING",
        "DÉFI DU BIAIS", "RÉFUTATION COGNITIVE", "DESAFÍO DEL SESGO"
    ]
    return any(kw in line_upper for kw in keywords) or line_upper.startswith("===")

# =====================================================================
# RUTA PRINCIPAL (FRONTEND HTML)
# =====================================================================
@app.route("/")
def index():
    """Sirve la página HTML desde la carpeta templates/"""
    return render_template("index.html") # o beacon-app.html según lo hayas nombrado

# =====================================================================
# ENDPOINTS API
# =====================================================================
@app.route("/transcript", methods=["GET"])
def get_youtube_transcript():
    video_id = request.args.get("videoId")
    if not video_id:
        return jsonify({"error": "Parámetro 'videoId' requerido"}), 400

    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['fr', 'es', 'en'])
        full_text = " ".join([item['text'] for item in transcript_list])
        return jsonify({"fullText": full_text, "text": full_text})
    except (TranscriptsDisabled, NoTranscriptFound):
        return jsonify({"error": "No se encontraron subtítulos disponibles para este video."}), 404
    except Exception as e:
        return jsonify({"error": f"Error al extraer subtítulos: {str(e)}"}), 500

@app.route("/analyze", methods=["POST"])
def analyze_text():
    data = request.get_json() or {}
    text = data.get("text", "").strip()
    lang = data.get("lang", "fr")

    if not text:
        return jsonify({"error": "Texto no proporcionado"}), 400

    # Aquí se integra la respuesta o llamada a tu motor/DB
    mock_analysis = (
        "PHASE 1: CLASSIFICATION METACONCEPTUELLE\n"
        "Score d'intégrité cognitive: 78/100\n\n"
        "PHASE 2: NOYAU DE FAITS & VÉRIFICABILITÉ\n"
        "- Analyse du contenu textuel et vérification des sources.\n\n"
        "PHASE 3: DÉMONTAGE COGNITIF DES BIAIS\n"
        "- Identification des figures de style persuasives.\n\n"
        "PHASE 4: RECADRAGE CORTICAL\n"
        "- Synthèse neutralisée."
    )

    return jsonify({
        "ethic_letter": "B",
        "score": 78,
        "flags": ["persuasif", "marketing", "biais leger"],
        "analysis": mock_analysis
    })

@app.route("/refute", methods=["POST"])
def refute_analysis():
    data = request.get_json() or {}
    analysis = data.get("analysis", "")

    if not analysis:
        return jsonify({"error": "Falta el análisis"}), 400

    mock_refutation = (
        "RÉFUTATION COGNITIVE (DÉFI DU BIAIS):\n"
        "1. Examen des hypothèses alternatives non prises en compte.\n"
        "2. Déconstruction des biais de confirmation décelés."
    )
    return jsonify({"refutation": mock_refutation})

@app.route("/export_pdf", methods=["POST"])
def export_pdf():
    try:
        data = request.get_json() or {}
        raw_score = data.get("score", 0)
        raw_analysis = (data.get("analysis") or "").replace("<br>", "\n").replace("<br/>", "\n")
        raw_flags = data.get("flags", [])
        lang = str(data.get("lang", "es")).lower()
        
        ref_id = data.get("reference", f"BEACON-2026-{datetime.now().strftime('%M%S%f')[:6]}")
        current_time_str = datetime.now().strftime("%d/%m/%Y, %H:%M")

        if not raw_analysis.strip():
            return jsonify({"error": "No hay análisis para exportar."}), 400

        try:
            digits = re.sub(r"[^\d]", "", str(raw_score))
            numeric_score = int(digits) if digits else 0
        except ValueError:
            numeric_score = 0

        ethic_letter = data.get("ethic_letter") or get_ethic_letter(numeric_score)
        translated_flags = translate_flags(raw_flags, lang)

        pdf_buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            pdf_buffer, pagesize=letter,
            rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40
        )

        story = []
        primary_blue = colors.HexColor("#0284c7")
        border_color = colors.HexColor("#cbd5e1")
        bg_card = colors.HexColor("#f8fafc")
        text_dark = colors.HexColor("#0f172a")

        score_colors = {"A": "#059669", "B": "#d97706", "C": "#ea580c", "D": "#dc2626"}
        score_color = colors.HexColor(score_colors.get(ethic_letter, "#dc2626"))

        header_title_style = ParagraphStyle('HeaderTitle', fontName='Helvetica-Bold', fontSize=14, leading=18, textColor=primary_blue)
        header_sub_style = ParagraphStyle('HeaderSub', fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor("#64748b"))
        meta_label_style = ParagraphStyle('MetaLabel', fontName='Helvetica-Bold', fontSize=8, leading=11, textColor=colors.HexColor("#475569"))
        score_box_style = ParagraphStyle('ScoreBox', fontName='Helvetica-Bold', fontSize=16, leading=18, textColor=score_color, alignment=1)
        heading_style = ParagraphStyle('SectionHeading', fontName='Helvetica-Bold', fontSize=10.5, leading=14, textColor=text_dark, spaceBefore=10, spaceAfter=4)
        body_style = ParagraphStyle('ReportBody', fontName='Helvetica', fontSize=9, leading=13, textColor=colors.HexColor("#334155"))

        story.append(Paragraph("POLETHIC FRANCE — BEACON LAB", header_title_style))
        story.append(Paragraph("LABORATORIO DE AUTODEFENSA COGNITIVA", header_sub_style))
        story.append(Spacer(1, 10))

        flags_html = " ".join([f'<font color="#0284c7"><b>[ {f} ]</b></font>' for f in translated_flags]) if translated_flags else "<i>Sin alertas específicas</i>"

        meta_text = f"<b>REFERENCIA:</b> {ref_id}<br/><b>FECHA Y HORA:</b> {current_time_str}<br/><b>ALERTAS / FLAGS:</b> {flags_html}"
        score_text = f"<b>ETHIC-SCORE</b><br/><font fontSize=22>{ethic_letter}</font><br/><font fontSize=8>({numeric_score}/100)</font>"

        card_table = Table([[Paragraph(score_text, score_box_style), Paragraph(meta_text, meta_label_style)]], colWidths=[130, 400])
        card_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), bg_card),
            ('BOX', (0, 0), (-1, -1), 1, border_color),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, border_color),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))

        story.append(card_table)
        story.append(Spacer(1, 14))

        for raw_line in raw_analysis.split('\n'):
            line_str = raw_line.strip()
            if not line_str: continue
            clean_line = sanitize_for_pdf(line_str)
            if not clean_line: continue

            if is_heading_line(line_str):
                story.append(Paragraph(clean_line, heading_style))
            else:
                story.append(Paragraph(clean_line, body_style))
                story.append(Spacer(1, 3))

        doc.build(story)
        pdf_buffer.seek(0)

        return send_file(
            pdf_buffer, mimetype='application/pdf', as_attachment=True, download_name=f'Audit_BEACON_{ref_id}.pdf'
        )
    except Exception as e:
        print(f"[export_pdf error]: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
