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


# =====================================================================
# SANEADO DE TEXTO PARA PDF (ReportLab)
# =====================================================================
import unicodedata

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # símbolos, pictogramas, emoji varios
    "\U00002600-\U000027BF"  # símbolos misceláneos / dingbats
    "\U0001F1E6-\U0001F1FF"  # banderas
    "\U0000FE0F"             # variation selector (el "️" de 🏷️)
    "]+",
    flags=re.UNICODE
)


def sanitize_for_pdf(text):
    """
    Prepara texto libre (venido del LLM) para insertarlo en un
    reportlab.Paragraph, que interpreta el contenido como XML:
    1) Quita emojis/pictogramas que Helvetica (WinAnsi) no sabe dibujar
       y que pueden romper la codificación -> texto/página en blanco.
    2) Escapa &, < y > para que no rompan el parser XML de Paragraph.
    3) Convierte **negrita** (markdown) en <b>negrita</b> real.
    """
    if not text:
        return ""

    # 1) fuera emojis/pictogramas
    text = _EMOJI_PATTERN.sub("", text)

    # 2) fuera cualquier otro carácter no soportado por WinAnsiEncoding
    #    (deja intactas las tildes/ñ/ü que sí soporta Latin-1)
    text = "".join(
        ch for ch in text
        if unicodedata.category(ch)[0] != "C"  # caracteres de control
        and (ord(ch) < 0x2500 or ch in "™")     # descarta symbol blocks raros
    )

    # 3) escapar XML antes de reinsertar nuestras propias etiquetas
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 4) **negrita** -> <b>negrita</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    return text.strip()


def is_heading_line(original_line):
    """Detecta líneas de cabecera de fase (van envueltas en ** **)."""
    stripped = _EMOJI_PATTERN.sub("", original_line).strip()
    return stripped.startswith("**") and stripped.rstrip().endswith("**")


@app.route("/export_pdf", methods=["POST"])
def export_pdf():
    try:
        data = request.get_json() or {}
        raw_score = data.get("score", 0)
        raw_analysis = (data.get("analysis") or "").replace("<br>", "\n").replace("<br/>", "\n")

        if not raw_analysis.strip():
            return jsonify({"error": "No hay análisis para exportar."}), 400

        # Extraer número o asignar 0 por defecto de forma segura
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

        # Colores
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

        # Estilos
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

        # Construcción PDF
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
        raw_analysis = (data.get("analysis") or "").replace("<br>", "\n").replace("<br/>", "\n")

        if not raw_analysis.strip():
            return jsonify({"error": "No hay análisis para exportar."}), 400

        pdf_buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=letter,
            rightMargin=40, leftMargin=40,
            topMargin=40, bottomMargin=40
        )

        story = []

        try:
            numeric_score = int(re.sub(r"[^\d]", "", str(score)))
        except ValueError:
            numeric_score = 0

        ethic_letter = get_ethic_letter(numeric_score)

        # Colores para fondo claro
        primary_blue = colors.HexColor("#0284c7")
        text_body = colors.HexColor("#334155")
        heading_color = colors.HexColor("#0f172a")

        # Color del Score según la severidad
        if ethic_letter == "A":
            score_color = colors.HexColor("#059669")  # Verde
        elif ethic_letter == "B":
            score_color = colors.HexColor("#d97706")  # Amarillo
        elif ethic_letter == "C":
            score_color = colors.HexColor("#ea580c")  # Naranja
        else:
            score_color = colors.HexColor("#dc2626")  # Rojo

        # Estilos tipográficos
        title_style = ParagraphStyle(
            'DocTitle',
            fontName='Helvetica-Bold',
            fontSize=18,
            leading=22,
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
            fontSize=14,
            leading=18,
            textColor=score_color,
            alignment=2
        )
        heading_style = ParagraphStyle(
            'SectionHeading',
            fontName='Helvetica-Bold',
            fontSize=11.5,
            leading=16,
            textColor=heading_color,
            spaceBefore=10,
            spaceAfter=4,
            borderColor=primary_blue,
            borderWidth=0,
        )
        body_style = ParagraphStyle(
            'ReportBody',
            fontName='Helvetica',
            fontSize=10,
            leading=15,
            textColor=text_body
        )

        # Construcción del documento
        story.append(Paragraph("POLETHIC FRANCE — BEACON LAB", title_style))
        story.append(Paragraph("RAPPORT D'AUDIT METACOGNITIF ET METACONTEXTUEL", subtitle_style))
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"ETHIC-SCORE: {ethic_letter} ({numeric_score}/100)", score_style))
        story.append(Spacer(1, 15))

        for raw_line in raw_analysis.split('\n'):
            if not raw_line.strip():
                continue
            clean_line = sanitize_for_pdf(raw_line)
            if not clean_line:
                continue
            if is_heading_line(raw_line):
                story.append(Paragraph(clean_line, heading_style))
            else:
                story.append(Paragraph(clean_line, body_style))
                story.append(Spacer(1, 6))

        doc.build(story)
        pdf_buffer.seek(0)

        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'Audit_BEACON_{ethic_letter}.pdf'
        )
    except Exception as e:
        print(f"[export_pdf] error: {e}")
        return jsonify({"error": str(e)}), 500


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
