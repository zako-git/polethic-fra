import os
import re
import io
import sqlite3
import unicodedata
from datetime import datetime
from flask import Flask, jsonify, request, send_file
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors

# =====================================================================
# DICCIONARIOS Y FUNCIONES AUXILIARES PARA EL PDF
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
    """Calcula la letra del Ethic-Score según el rango numérico"""
    if score >= 85: return "A"
    if score >= 65: return "B"
    if score >= 40: return "C"
    return "D"

def translate_flags(flags_list, lang="fr"):
    """Traduce la lista de alertas/flags al idioma seleccionado"""
    lang_dict = FLAG_TRANSLATIONS.get(lang.lower(), FLAG_TRANSLATIONS["fr"])
    return [lang_dict.get(f.strip().lower(), f.strip().upper()) for f in flags_list]

def sanitize_for_pdf(text):
    """Limpia caracteres Markdown y asegura compatibilidad UTF-8 en ReportLab"""
    if not text: return ""
    text = text.replace("**", "").replace("<", "&lt;").replace(">", "&gt;")
    normalized = unicodedata.normalize('NFKD', text)
    return normalized.encode('ascii', 'ignore').decode('utf-8')

def is_heading_line(line):
    """Detecta si una línea del informe debe actuar como un título/encabezado"""
    line_upper = line.strip().upper()
    keywords = [
        "FASE", "PHASE", "NÚCLEO DE HECHOS", "NOYAU DE FAITS", "CORE FACTS",
        "DESMONTAJE COGNITIVO", "DÉMONTAGE COGNITIF", "COGNITIVE DECONSTRUCTION",
        "REENCUADRE CORTICAL", "RECADRAGE CORTICAL", "CORTICAL REFRAMING",
        "DÉFI DU BIAIS", "RÉFUTATION COGNITIVE", "DESAFÍO DEL SESGO"
    ]
    return any(kw in line_upper for kw in keywords) or line_upper.startswith("===")

# =====================================================================
# ENDPOINT: /export_pdf (GENERADOR DE INFORME PDF EN MEMORIA)
# =====================================================================
@app.route("/export_pdf", methods=["POST"])
def export_pdf():
    try:
        data = request.get_json() or {}
        raw_score = data.get("score", 0)
        raw_analysis = (data.get("analysis") or "").replace("<br>", "\n").replace("<br/>", "\n")
        raw_flags = data.get("flags", [])
        lang = str(data.get("lang", "es")).lower()
        
        # Referencia y Fecha
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
            pdf_buffer,
            pagesize=letter,
            rightMargin=40, leftMargin=40,
            topMargin=40, bottomMargin=40
        )

        story = []

        # Paleta de colores
        primary_blue = colors.HexColor("#0284c7")
        border_color = colors.HexColor("#cbd5e1")
        bg_card = colors.HexColor("#f8fafc")
        text_dark = colors.HexColor("#0f172a")

        score_colors = {"A": "#059669", "B": "#d97706", "C": "#ea580c", "D": "#dc2626"}
        score_color = colors.HexColor(score_colors.get(ethic_letter, "#dc2626"))

        # Estilos de texto
        header_title_style = ParagraphStyle(
            'HeaderTitle', fontName='Helvetica-Bold', fontSize=14, leading=18, textColor=primary_blue
        )
        header_sub_style = ParagraphStyle(
            'HeaderSub', fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor("#64748b")
        )
        meta_label_style = ParagraphStyle(
            'MetaLabel', fontName='Helvetica-Bold', fontSize=8, leading=11, textColor=colors.HexColor("#475569")
        )
        score_box_style = ParagraphStyle(
            'ScoreBox', fontName='Helvetica-Bold', fontSize=16, leading=18, textColor=score_color, alignment=1
        )
        heading_style = ParagraphStyle(
            'SectionHeading', fontName='Helvetica-Bold', fontSize=10.5, leading=14, textColor=text_dark, spaceBefore=10, spaceAfter=4
        )
        body_style = ParagraphStyle(
            'ReportBody', fontName='Helvetica', fontSize=9, leading=13, textColor=colors.HexColor("#334155")
        )

        # 1. Encabezado principal
        story.append(Paragraph("POLETHIC FRANCE — BEACON LAB", header_title_style))
        story.append(Paragraph("LABORATORIO DE AUTODEFENSA COGNITIVA", header_sub_style))
        story.append(Spacer(1, 10))

        # 2. Formatear etiquetas de Flags para el PDF
        flags_html = " ".join([
            f'<font color="#0284c7"><b>[ {f} ]</b></font>' for f in translated_flags
        ]) if translated_flags else "<i>Sin alertas específicas</i>"

        # 3. Cuadro de Meta-Información (Score + Referencia + Flags)
        meta_text = (
            f"<b>REFERENCIA:</b> {ref_id}<br/>"
            f"<b>FECHA Y HORA:</b> {current_time_str}<br/>"
            f"<b>ALERTAS / FLAGS:</b> {flags_html}"
        )

        score_text = f"<b>ETHIC-SCORE</b><br/><font fontSize=22>{ethic_letter}</font><br/><font fontSize=8>({numeric_score}/100)</font>"

        card_data = [
            [Paragraph(score_text, score_box_style), Paragraph(meta_text, meta_label_style)]
        ]

        card_table = Table(card_data, colWidths=[130, 400])
        card_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), bg_card),
            ('BOX', (0, 0), (-1, -1), 1, border_color),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, border_color),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))

        story.append(card_table)
        story.append(Spacer(1, 14))

        # 4. Cuerpo del Análisis
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
                story.append(Spacer(1, 3))

        doc.build(story)
        pdf_buffer.seek(0)

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'Audit_BEACON_{ref_id}.pdf'
        )
    except Exception as e:
        print(f"[export_pdf error]: {e}")
        return jsonify({"error": str(e)}), 500
