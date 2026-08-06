import os
import re
import json
from datetime import datetime
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from huggingface_hub import InferenceClient
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

app = Flask(__name__)
# ✅ Habilitar CORS explícito para permitir peticiones AJAX desde cualquier origen
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# =====================================================================
# CONFIGURACIÓN Y CLIENTE HUGGINGFACE
# =====================================================================
HF_TOKEN = os.environ.get("HF_TOKEN", "")
MODEL_ID = "meta-llama/Llama-3.3-70B-Instruct"

client = None
if HF_TOKEN:
    try:
        client = InferenceClient(token=HF_TOKEN)
    except Exception as e:
        print(f"[WARN] Error al inicializar HuggingFace Client: {e}")

AUDIT_FILE = "beacon_audits.json"

# =====================================================================
# DICCIONARIO DE ENCABEZADOS ESTRUCTURADOS SEGÚN EL IDIOMA
# =====================================================================
SECTION_HEADERS = {
    "fr": {
        "h1": "**1. CLASSIFICATION (Phase 0)**",
        "h2": "**2. NOYAU DE FAITS / PRÉMISSES (Phase 1)**",
        "h3": "**3. DÉMONTAGE COGNITIF ET LIMBIQUE (Phase 2)**",
        "h4": "**4. RECADRAGE CORTICAL ET STRATÉGIE (Phase 3)**"
    },
    "es": {
        "h1": "**1. CLASIFICACIÓN (Fase 0)**",
        "h2": "**2. NÚCLEO DE HECHOS / PREMISAS (Fase 1)**",
        "h3": "**3. DESMONTAJE COGNITIVO Y LÍMBICO (Fase 2)**",
        "h4": "**4. REENCUADRE CORTICAL Y ESTRATEGIA (Fase 3)**"
    },
    "en": {
        "h1": "**1. CLASSIFICATION (Phase 0)**",
        "h2": "**2. CORE FACTS / PREMISES (Phase 1)**",
        "h3": "**3. COGNITIVE AND LIMBIC DECONSTRUCTION (Phase 2)**",
        "h4": "**4. CORTICAL REFRAMING & STRATEGY (Phase 3)**"
    }
}

# =====================================================================
# TEMPLATES DE PROMPTS 100% MONOLINGÜES
# =====================================================================
TEMPLATES = {
    "fr": {
        "system": (
            "Vous êtes POLETHIC BEACON, un moteur d'analyse métacognitive.\n"
            "RÈGLE ABSOLUE: Vous devez répondre TOUT le texte (titres, sous-titres, explications) EXCLUSIVEMENT EN FRANÇAIS.\n"
            "Il est STRICTEMENT INTERDIT de mettre des mots ou des titres en espagnol ou en anglais.\n\n"
            "FORMAT DE SORTIE IMPÉRATIF ET OBLIGATOIRE :\n\n"
            "  **1. CLASSIFICATION (Phase 0)**\n"
            "- Type de texte:\n"
            "- Objectif de l'émetteur:\n\n"
            "  **2. NOYAU DE FAITS / PRÉMISSES (Phase 1)**\n"
            "- Données et affirmations filtrées sans bruit:\n\n"
            "  **3. DÉMONTAGE COGNITIF ET LIMBIQUE (Phase 2)**\n"
            "- Déclencheur émotionnel / Biais détecté:\n"
            "- Intention vs Réalité (Analyse du langage):\n\n"
            "  **4. RECADRAGE CORTICAL ET STRATÉGIE (Phase 3)**\n"
            "- Diagnostic synthétique final et recommandation d'action:\n\n"
            "<flags>[Liste séparée par des virgules: fakenews, myth, bluff, coercion, dogma, pseudoscience, authority_transfer, psnc]</flags>\n"
            "<score>[Nombre entier de 0 à 100]</score>"
        ),
        "refute_prompt": (
            "Générez exactement 3 questions chirurgicales, précises et incisives en FRANÇAIS "
            "pour réfuter ou remettre en question l'argument principal du texte analysé."
        )
    },
    "es": {
        "system": (
            "Eres POLETHIC BEACON, un motor de análisis metacognitivo.\n"
            "REGLA ABSOLUTA: Debes responder TODO el texto (títulos, subtítulos, explicaciones) EXCLUSIVAMENTE EN ESPAÑOL.\n"
            "Está ESTRICTAMENTE PROHIBIDO usar palabras o títulos en francés o inglés.\n\n"
            "FORMATO DE SALIDA IMPERATIVO Y OBLIGATORIO :\n\n"
            "  **1. CLASIFICACIÓN (Fase 0)**\n"
            "- Tipo de texto:\n"
            "- Propósito del emisor:\n\n"
            "  **2. NÚCLEO DE HECHOS / PREMISAS (Fase 1)**\n"
            "- Datos y afirmaciones filtradas sin ruido:\n\n"
            "  **3. DESMONTAJE COGNITIVO Y LÍMBICO (Fase 2)**\n"
            "- Disparador emocional / Sesgo detectado:\n"
            "- Intención vs Realidad (Análisis del lenguaje):\n\n"
            "  **4. REENCUADRE CORTICAL Y ESTRATEGIA (Fase 3)**\n"
            "- Diagnóstico sintético final y recomendación de acción:\n\n"
            "<flags>[Lista separada por comas: fakenews, myth, bluff, coercion, dogma, pseudoscience, authority_transfer, psnc]</flags>\n"
            "<score>[Número entero de 0 a 100]</score>"
        ),
        "refute_prompt": (
            "Genera exactamente 3 preguntas quirúrgicas, precisas e incisivas en ESPAÑOL "
            "para refutar o poner a prueba la argumentación principal del texto analizado."
        )
    },
    "en": {
        "system": (
            "You are POLETHIC BEACON, a metacognitive analysis engine.\n"
            "ABSOLUTE RULE: You MUST answer ALL text (titles, subtitles, explanations) EXCLUSIVELY IN ENGLISH.\n"
            "It is STRICTLY FORBIDDEN to use Spanish or French words or headers.\n\n"
            "MANDATORY OUTPUT FORMAT:\n\n"
            "  **1. CLASSIFICATION (Phase 0)**\n"
            "- Text Type:\n"
            "- Sender Purpose:\n\n"
            "  **2. CORE FACTS / PREMISES (Phase 1)**\n"
            "- Noise-filtered data:\n\n"
            "  **3. COGNITIVE AND LIMBIC DECONSTRUCTION (Phase 2)**\n"
            "- Emotional Trigger / Bias Detected:\n"
            "- Intent vs. Reality:\n\n"
            "  **4. CORTICAL REFRAMING & STRATEGY (Phase 3)**\n"
            "- Final synthetic diagnosis and action recommendation:\n\n"
            "<flags>[Comma-separated list: fakenews, myth, bluff, coercion, dogma, pseudoscience, authority_transfer, psnc]</flags>\n"
            "<score>[Integer from 0 to 100]</score>"
        ),
        "refute_prompt": (
            "Generate exactly 3 surgical, precise, and incisive questions in ENGLISH "
            "to challenge or refute the main argument of the analyzed text."
        )
    }
}

# =====================================================================
# FUNCIONES AUXILIARES DE LIMPIEZA Y FORMATEO
# =====================================================================
def force_language_headings(analysis_text, target_lang="fr"):
    lang = target_lang if target_lang in SECTION_HEADERS else "fr"
    headers = SECTION_HEADERS[lang]

    patterns = [
        (r'\*\*?1\.\s*(CLASIFICACIÓN|CLASSIFICATION).*?\*\*?', headers["h1"]),
        (r'\*\*?2\.\s*(NÚCLEO DE HECHOS|NOYAU DE FAITS|CORE FACTS).*?\*\*?', headers["h2"]),
        (r'\*\*?3\.\s*(DESMONTAJE|DÉMONTAGE|COGNITIVE).*?\*\*?', headers["h3"]),
        (r'\*\*?4\.\s*(REENCUADRE|RECADRAGE|CORTICAL).*?\*\*?', headers["h4"])
    ]

    clean_text = analysis_text
    for pattern, correct_header in patterns:
        clean_text = re.sub(pattern, correct_header, clean_text, flags=re.IGNORECASE)

    return clean_text

def get_ethic_letter(score):
    if score >= 85:
        return "A"
    elif score >= 70:
        return "B"
    elif score >= 50:
        return "C"
    elif score >= 30:
        return "D"
    return "F"

def is_heading_line(original_line):
    if not original_line:
        return False
    line_upper = original_line.strip().upper()
    return any(phase in line_upper for phase in [
        "PHASE 0", "PHASE 1", "PHASE 2", "PHASE 3", 
        "FASE 0", "FASE 1", "FASE 2", "FASE 3"
    ])

def save_audit(source_type, content_type, raw_text, score, analysis):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "source_type": source_type,
        "content_type": content_type,
        "raw_text": raw_text[:200] + "...",
        "score": score,
        "analysis": analysis
    }
    data = []
    if os.path.exists(AUDIT_FILE):
        try:
            with open(AUDIT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
    data.append(entry)
    with open(AUDIT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =====================================================================
# ENDPOINT PRINCIPAL: /analyze
# =====================================================================
@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    data = request.json or {}
    content_to_analyze = data.get("text", "") or data.get("content", "")
    source_type = data.get("sourceType", "text")
    lang = data.get("lang", "fr").lower()

    if not content_to_analyze:
        return jsonify({"error": "No content provided"}), 400

    template = TEMPLATES.get(lang, TEMPLATES["fr"])
    analysis_text = ""
    final_score = 50
    final_flags = []

    if client:
        try:
            lang_names = {"fr": "FRENCH", "es": "SPANISH", "en": "ENGLISH"}
            target_lang_name = lang_names.get(lang, "FRENCH")

            user_prompt = (
                f"CRITICAL REQUIREMENT: WRITE EVERYTHING 100% IN {target_lang_name}.\n"
                f"DO NOT MIX LANGUAGES. USE ONLY {target_lang_name} FOR HEADERS AND CONTENT.\n\n"
                f"Content to analyze:\n{content_to_analyze}"
            )

            response = client.chat.completions.create(
                model=MODEL_ID,
                messages=[
                    {"role": "system", "content": template["system"]},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=1200,
                temperature=0.0
            )
            analysis_text = response.choices[0].message.content
        except Exception as hf_err:
            print(f"[HF Error]: {hf_err}")
            return jsonify({"error": f"Error in LLM analysis service: {str(hf_err)}"}), 500
    else:
        return jsonify({"error": "HF_TOKEN not configured on server"}), 500

    # Extraer score y flags de la respuesta
    score_match = re.search(r"<score>(\d+)</score>", analysis_text)
    if score_match:
        final_score = int(score_match.group(1))

    flags_match = re.search(r"<flags>(.*?)</flags>", analysis_text)
    if flags_match:
        final_flags = [f.strip() for f in flags_match.group(1).split(",") if f.strip()]

    # Limpiar tags XML del texto resultante
    clean_analysis = re.sub(r"<score>.*?</score>", "", analysis_text, flags=re.DOTALL)
    clean_analysis = re.sub(r"<flags>.*?</flags>", "", clean_analysis, flags=re.DOTALL).strip()

    # FORZAR ENCABEZADOS EN EL IDIOMA OBJETIVO
    clean_analysis = force_language_headings(clean_analysis, target_lang=lang)

    ethic_letter = get_ethic_letter(final_score)
    save_audit("CORE", source_type, content_to_analyze, final_score, clean_analysis)

    return jsonify({
        "analysis": clean_analysis,
        "report": clean_analysis,
        "score": final_score,
        "numericScore": final_score,
        "flags": final_flags,
        "ethic_letter": ethic_letter,
        "scoreLetter": ethic_letter
    }), 200

# =====================================================================
# ENDPOINT SECUNDARIO: /challenge (Réfutation Cognitive)
# =====================================================================
@app.route("/challenge", methods=["POST"])
def challenge():
    try:
        data = request.get_json(silent=True) or {}   # silent=True evita el 400 crudo
        text_to_challenge = data.get("analysis", "") or data.get("text", "")
        lang = data.get("lang", "fr").lower()

        template = TEMPLATES.get(lang, TEMPLATES["fr"])
        refutation_text = ""

        if not text_to_challenge:
            return jsonify({"challenge": "", "error": "No analysis text provided."}), 200

        if not client:
            return jsonify({"challenge": "", "error": "HF client not initialized (missing HF_TOKEN)."}), 200

        try:
            response = client.chat.completions.create(
                model=MODEL_ID,
                messages=[
                    {"role": "system", "content": "You are POLETHIC BEACON Metacognitive Refutation Engine."},
                    {"role": "user", "content": f"{template['refute_prompt']}\n\nContext:\n{text_to_challenge}"}
                ],
                max_tokens=600,
                temperature=0.2
            )
            refutation_text = response.choices[0].message.content
        except Exception as err:
            print(f"[Challenge HF Error]: {err}")
            return jsonify({"challenge": "", "error": f"HF inference failed: {err}"}), 502

        return jsonify({"challenge": refutation_text}), 200

    except Exception as outer_err:
        print(f"[Challenge Route Error]: {outer_err}")
        return jsonify({"challenge": "", "error": str(outer_err)}), 500

    # ✅ Devolver la propiedad "challenge" y compatibilidad con "refutation"
    return jsonify({
        "status": "success",
        "challenge": refutation_text,
        "refutation": refutation_text
    }), 200

# =====================================================================
# ENDPOINT PDF: /export_pdf
# =====================================================================
@app.route("/export_pdf", methods=["POST", "OPTIONS"])
def export_pdf():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    data = request.json or {}
    analysis_text = data.get("analysis", "")
    refutation_text = data.get("refutation", "")
    score = data.get("score", 50)
    flags = data.get("flags", [])
    lang = data.get("lang", "fr").lower()

    analysis_text = force_language_headings(analysis_text, target_lang=lang)

    pdf_filename = f"RAPPORT_BEACON_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf_path = os.path.join("/tmp", pdf_filename)

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    style_header_title = ParagraphStyle('HeaderTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=colors.HexColor("#00E5FF"))
    style_header_sub = ParagraphStyle('HeaderSub', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=11, textColor=colors.HexColor("#00E5FF"))
    style_meta = ParagraphStyle('MetaText', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, leading=12, textColor=colors.HexColor("#FFFFFF"))
    style_heading = ParagraphStyle('Heading', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor("#00E5FF"), spaceBefore=10, spaceAfter=4)
    style_body = ParagraphStyle('Body', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=13, textColor=colors.HexColor("#D0D7DE"), spaceAfter=4)
    style_bullet = ParagraphStyle('Bullet', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=13, textColor=colors.HexColor("#D0D7DE"), leftIndent=12, firstLineIndent=-8, spaceAfter=2)
    style_warn_title = ParagraphStyle('WarnTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, leading=11, textColor=colors.HexColor("#FFB703"))
    style_warn_body = ParagraphStyle('WarnBody', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor("#D0D7DE"))
    style_footer = ParagraphStyle('Footer', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10, textColor=colors.HexColor("#8B949E"), alignment=1)

    disclaimers = {
        "fr": {
            "warn_title": "AVERTISSEMENT D'ANALYSE CRITIQUE ET DÉCONSTRUCTION",
            "warn_body": "Ce module applique les principes de la logique formelle et de la méthode scientifique. Le résultat peut générer une dissonance cognitive. La plateforme n'est pas responsable de la friction émotionnelle résultant de cette analyse.",
            "refute_title": "DÉFI DU BIAIS (RÉFUTATION COGNITIVE) :"
        },
        "es": {
            "warn_title": "ADVERTENCIA DE ANÁLISIS CRÍTICO Y DECONSTRUCCIÓN",
            "warn_body": "Este módulo aplica principios de lógica formal, exégesis histórica y método científico. El resultado puede generar disonancia cognitiva al cuestionar dogmas. La plataforma no se responsabiliza de la fricción emocional resultante.",
            "refute_title": "DESAFÍO DEL SESGO (REFUTACIÓN COGNITIVA) :"
        },
        "en": {
            "warn_title": "CRITICAL ANALYSIS AND DECONSTRUCTION WARNING",
            "warn_body": "This module applies principles of formal logic and scientific method. The result may cause cognitive dissonance. The platform is not responsible for emotional friction resulting from this analysis.",
            "refute_title": "BIAS CHALLENGE (COGNITIVE REFUTATION) :"
        }
    }
    disc = disclaimers.get(lang, disclaimers["fr"])

    story = []

    story.append(Paragraph("POLETHIC BEACON", style_header_title))
    story.append(Paragraph("LABORATOIRE D'AUTODÉFENSE COGNITIVE", style_header_sub))
    story.append(Spacer(1, 10))

    beacon_ref = f"BEACON-{datetime.now().year}-{int(datetime.now().timestamp()) % 1000000:06d}"
    flags_str = ", ".join(flags).upper() if flags else "NONE"
    
    meta_data = [
        [
            Paragraph(f"ETHIC-SCORE: {score}/100 ({get_ethic_letter(score)})", style_meta),
            Paragraph(f"NIVEAU: {get_ethic_letter(score)}", style_meta)
        ],
        [
            Paragraph(f"RÉF: {beacon_ref}", style_meta),
            Paragraph(f"HORODATAGE: {datetime.now().strftime('%d/%m/%Y %H:%M')}", style_meta)
        ],
        [
            Paragraph(f"INDICATEURS: {flags_str}", style_meta),
            Paragraph("", style_meta)
        ]
    ]
    t_meta = Table(meta_data, colWidths=[270, 270])
    t_meta.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#0D1117")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#00E5FF")),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 12))

    for line in analysis_text.split('\n'):
        line_s = line.strip()
        if not line_s:
            continue
        
        clean_line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line_s)
        
        if is_heading_line(line_s):
            heading_p = Paragraph(clean_line, style_heading)
            t_head = Table([[heading_p]], colWidths=[540])
            t_head.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#161B22")),
                ('LINELEFT', (0,0), (-1,-1), 3, colors.HexColor("#00E5FF")),
                ('PADDING', (0,0), (-1,-1), 4),
            ]))
            story.append(Spacer(1, 6))
            story.append(t_head)
            story.append(Spacer(1, 4))
        elif line_s.startswith(('-', '•', '*')):
            item_text = re.sub(r'^[-•\*]\s*', '', clean_line)
            story.append(Paragraph(f"• {item_text}", style_bullet))
        else:
            story.append(Paragraph(clean_line, style_body))

    if refutation_text:
        story.append(Spacer(1, 10))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#FFB703"), spaceBefore=5, spaceAfter=10))
        story.append(Paragraph(disc["refute_title"], style_heading))
        
        warn_content = [
            Paragraph(disc["warn_title"], style_warn_title),
            Spacer(1, 2),
            Paragraph(disc["warn_body"], style_warn_body)
        ]
        t_warn = Table([[warn_content]], colWidths=[540])
        t_warn.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#1A1400")),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#FFB703")),
            ('PADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(t_warn)
        story.append(Spacer(1, 8))

        for line in refutation_text.split('\n'):
            line_s = line.strip()
            if line_s:
                clean_ref = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line_s)
                story.append(Paragraph(clean_ref, style_body))

    story.append(Spacer(1, 15))
    story.append(Paragraph("POLETHIC BEACON — Analyse et autodéfense cognitive", style_footer))

    def background_canvas(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#050811"))
        canvas.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
        canvas.restoreState()

    doc.build(story, onFirstPage=background_canvas, onLaterPages=background_canvas)
    return send_file(pdf_path, as_attachment=True, download_name=pdf_filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
