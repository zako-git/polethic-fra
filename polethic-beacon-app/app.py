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
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from PIL import Image

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

app = Flask(__name__)
# Habilitar CORS explícito para permitir peticiones AJAX desde cualquier origen
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# =====================================================================
# CONFIGURACIÓN Y CLIENTE HUGGINGFACE
# =====================================================================
HF_TOKEN = os.environ.get("HF_TOKEN", "")
# Modelo pequeño (8B) para mantenerse dentro de la cuota gratuita de Inference Providers.
# El modelo anterior (Llama-3.3-70B-Instruct) agotaba la cuota gratuita en pocas llamadas
# y devolvía 402 Payment Required.
MODEL_ID = "meta-llama/Llama-3.1-8B-Instruct"

client = None
if HF_TOKEN:
    try:
        client = InferenceClient(token=HF_TOKEN)
    except Exception as e:
        print(f"[WARN] Error al inicializar HuggingFace Client: {e}")

# Modo de prueba sin gastar cuota de HF: activa con la variable de entorno MOCK_LLM=true
# (en Render: Settings > Environment > Add Environment Variable). Con esto puedes probar
# todo el flujo (frontend, PDF, refutación) aunque HF esté sin cuota o de baja.
MOCK_LLM = os.environ.get("MOCK_LLM", "false").lower() == "true"

if not HF_TOKEN and not MOCK_LLM:
    print("[WARN] HF_TOKEN not configured; falling back to MOCK_LLM mode for local/demo use.")
    MOCK_LLM = True

MOCK_ANALYSIS = {
    "fr": (
        "**1. CLASSIFICATION (Phase 0)**\n"
        "- Type de texte: Exemple de test (mode MOCK)\n"
        "- Objectif de l'émetteur: Démonstration sans appel réel au LLM\n\n"
        "**2. NOYAU DE FAITS / PRÉMISSES (Phase 1)**\n"
        "- Données et affirmations filtrées sans bruit: Ceci est une réponse simulée.\n\n"
        "**3. DÉMONTAGE COGNITIF ET LIMBIQUE (Phase 2)**\n"
        "- Déclencheur émotionnel / Biais détecté: Aucun (mode test)\n"
        "- Intention vs Réalité (Analyse du langage): N/A\n\n"
        "**4. RECADRAGE CORTICAL ET STRATÉGIE (Phase 3)**\n"
        "- Diagnostic synthétique final et recommandation d'action: Ceci est un résultat de test généré localement, sans consommer de crédits Hugging Face.\n"
    ),
    "es": (
        "**1. CLASIFICACIÓN (Fase 0)**\n"
        "- Tipo de texto: Ejemplo de prueba (modo MOCK)\n"
        "- Propósito del emisor: Demostración sin llamada real al LLM\n\n"
        "**2. NÚCLEO DE HECHOS / PREMISAS (Fase 1)**\n"
        "- Datos y afirmaciones filtradas sin ruido: Esta es una respuesta simulada.\n\n"
        "**3. DESMONTAJE COGNITIVO (Fase 2)**\n"
        "- Disparador emocional / Sesgo detectado: Ninguno (modo prueba)\n"
        "- Intención vs Realidad (Análisis del lenguaje): N/D\n\n"
        "**4. REENCUADRE CORTICAL Y ESTRATEGIA (Fase 3)**\n"
        "- Diagnóstico sintético final y recomendación de acción: Este es un resultado de prueba generado localmente, sin consumir créditos de Hugging Face.\n"
    ),
    "en": (
        "**1. CLASSIFICATION (Phase 0)**\n"
        "- Text Type: Test example (MOCK mode)\n"
        "- Sender Purpose: Demonstration without a real LLM call\n\n"
        "**2. CORE FACTS / PREMISES (Phase 1)**\n"
        "- Noise-filtered data: This is a simulated response.\n\n"
        "**3. COGNITIVE DECONSTRUCTION (Phase 2)**\n"
        "- Emotional Trigger / Bias Detected: None (test mode)\n"
        "- Intent vs. Reality: N/A\n\n"
        "**4. CORTICAL REFRAMING & STRATEGY (Phase 3)**\n"
        "- Final synthetic diagnosis and action recommendation: This is a locally generated test result, without consuming Hugging Face credits.\n"
    ),
}

MOCK_REFUTATION = {
    "fr": "1. Ceci est une question de test n°1.\n2. Ceci est une question de test n°2.\n3. Ceci est une question de test n°3.",
    "es": "1. Esta es una pregunta de prueba n.º 1.\n2. Esta es una pregunta de prueba n.º 2.\n3. Esta es una pregunta de prueba n.º 3.",
    "en": "1. This is test question #1.\n2. This is test question #2.\n3. This is test question #3.",
}

# Guardar en la carpeta temporal para evitar fallos de permisos en servidores tipo Render
AUDIT_FILE = os.path.join("/tmp", "beacon_audits.json")

# =====================================================================
# DICCIONARIO DE ENCABEZADOS ESTRUCTURADOS SEGÚN EL IDIOMA
# =====================================================================
SECTION_HEADERS = {
    "fr": {
        "h1": "**1. CLASSIFICATION (Phase 0)**",
        "h2": "**2. NOYAU DE FAITS / PRÉMISSES (Phase 1)**",
        "h3": "**3. DÉMONTAGE COGNITIF (Phase 2)**",
        "h4": "**4. RECADRAGE CORTICAL ET STRATÉGIE (Phase 3)**"
    },
    "es": {
        "h1": "**1. CLASIFICACIÓN (Fase 0)**",
        "h2": "**2. NÚCLEO DE HECHOS / PREMISAS (Fase 1)**",
        "h3": "**3. DESMONTAJE COGNITIVO (Fase 2)**",
        "h4": "**4. REENCUADRE CORTICAL Y ESTRATEGIA (Fase 3)**"
    },
    "en": {
        "h1": "**1. CLASSIFICATION (Phase 0)**",
        "h2": "**2. CORE FACTS / PREMISES (Phase 1)**",
        "h3": "**3. COGNITIVE DECONSTRUCTION (Phase 2)**",
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
            "  **3. DÉMONTAGE COGNITIF (Phase 2)**\n"
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
            "  **3. DESMONTAJE COGNITIVO (Fase 2)**\n"
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
            "  **3. COGNITIVE DECONSTRUCTION (Phase 2)**\n"
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
    """Guarda una copia de la auditoría de forma segura sin romper la aplicación"""
    try:
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
    except Exception as e:
        print(f"[WARN] No se pudo escribir en el archivo de auditoría: {e}")

URL_REGEX = re.compile(r'https?://[^\s<>"\)]+', re.IGNORECASE)
YOUTUBE_DOMAINS = ('youtube.com', 'youtu.be')

class VisibleTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._texts = []
        self._ignore = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self._ignore = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self._ignore = False
        if tag in ('p', 'br', 'div', 'li', 'h1', 'h2', 'h3', 'h4'):
            self._texts.append('\n')

    def handle_data(self, data):
        if not self._ignore:
            text = data.strip()
            if text:
                self._texts.append(text)

    def get_text(self):
        return ' '.join(self._texts).replace('\n ', '\n').strip()


def extract_urls(text):
    return URL_REGEX.findall(text or "")


def is_youtube_url(url):
    parsed = urlparse(url)
    return any(domain in parsed.netloc for domain in YOUTUBE_DOMAINS)


def get_youtube_video_id(url):
    parsed = urlparse(url)
    if 'youtu.be' in parsed.netloc:
        return parsed.path.lstrip('/')
    if 'youtube.com' in parsed.netloc:
        query = dict([part.split('=') for part in parsed.query.split('&') if '=' in part])
        return query.get('v')
    return None


def fetch_youtube_transcript(url):
    if YouTubeTranscriptApi is None:
        print('[YouTube Transcript Warning] youtube_transcript_api no está instalado.')
        return None

    video_id = get_youtube_video_id(url)
    if not video_id:
        return None

    try:
        transcript_items = YouTubeTranscriptApi.get_transcript(video_id, languages=['es', 'fr', 'en'])
        transcript_text = ' '.join([item.get('text', '') for item in transcript_items])
        return transcript_text.strip()
    except Exception as err:
        print(f"[YouTube Transcript Error] {url}: {err}")
        return None


def extract_visible_text_from_html(html):
    parser = VisibleTextExtractor()
    parser.feed(html)
    return parser.get_text()


def fetch_url_text(url):
    try:
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; BeaconBot/1.0)'})
        with urlopen(req, timeout=12) as response:
            content_type = response.headers.get('Content-Type', '')
            data = response.read()
            if 'text' not in content_type.lower():
                return None
            html_text = data.decode('utf-8', errors='ignore')
            text = extract_visible_text_from_html(html_text)
            return text.strip()[:2000]
    except (HTTPError, URLError, Exception) as err:
        print(f"[URL Fetch Error] {url}: {err}")
        return None


def ocr_image_file(file_storage):
    if not pytesseract:
        print('[OCR Warning] pytesseract no está instalado.')
        return None

    try:
        file_storage.stream.seek(0)
        image = Image.open(file_storage.stream)
        image = image.convert('RGB')
        extracted = pytesseract.image_to_string(image, lang='spa+fra+eng')
        return extracted.strip() or None
    except Exception as err:
        print(f"[OCR Error] {err}")
        return None

# =====================================================================
# ENDPOINT PRINCIPAL: /analyze
# =====================================================================
@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        request_data = request.get_json(silent=True)
        data = request_data or {}

        # Soporte para formularios multipart/form-data desde el frontend
        if not data and request.form:
            data = request.form.to_dict(flat=True)

        content_to_analyze = data.get("text", "") or data.get("content", "")
        source_type = data.get("sourceType", "text")
        lang = data.get("lang", "fr").lower()

        uploaded_file = request.files.get("image")
        if uploaded_file and uploaded_file.filename:
            source_type = "image"
            filename_lower = uploaded_file.filename.lower()
            if filename_lower.endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp')):
                ocr_text = ocr_image_file(uploaded_file)
                if ocr_text:
                    if content_to_analyze:
                        content_to_analyze = f"{content_to_analyze}\n\n[OCR text extracted from image:]\n{ocr_text}"
                    else:
                        content_to_analyze = ocr_text
                else:
                    if not content_to_analyze:
                        content_to_analyze = f"[IMAGE FILE: {uploaded_file.filename}]"
            else:
                if content_to_analyze:
                    content_to_analyze = f"[FILE: {uploaded_file.filename}]\n\n{content_to_analyze}"
                else:
                    content_to_analyze = f"[FILE: {uploaded_file.filename}]"

        urls = extract_urls(content_to_analyze)
        if urls:
            extracted_parts = []
            for url in urls[:2]:
                if is_youtube_url(url):
                    transcript = fetch_youtube_transcript(url)
                    if transcript:
                        extracted_parts.append(f"[YouTube transcript from {url}]\n{transcript}")
                else:
                    page_text = fetch_url_text(url)
                    if page_text:
                        extracted_parts.append(f"[Extracted text from {url}]\n{page_text}")

            if extracted_parts:
                content_to_analyze = f"{content_to_analyze}\n\n" + "\n\n".join(extracted_parts)
                if source_type == 'text':
                    source_type = 'url'

        if not content_to_analyze:
            return jsonify({"error": "No content provided"}), 400

        template = TEMPLATES.get(lang, TEMPLATES["fr"])
        analysis_text = ""
        final_score = 50
        final_flags = []

        if MOCK_LLM:
            analysis_text = MOCK_ANALYSIS.get(lang, MOCK_ANALYSIS["fr"])
            analysis_text += "\n\n<flags>fakenews,myth</flags>\n<score>55</score>"
        elif client:
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
                return jsonify({"error": f"Error in LLM analysis service: {str(hf_err)}"}), 502
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

    except Exception as err:
        print(f"[Analyze Route Error]: {err}")
        return jsonify({"error": "Internal Server Error", "details": str(err)}), 500

# =====================================================================
# ENDPOINT SECUNDARIO: /refute (Réfutation Cognitive)
# =====================================================================
@app.route("/refute", methods=["POST", "OPTIONS"])
def challenge():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data = request.get_json(silent=True) or {}
        text_to_challenge = data.get("analysis", "") or data.get("text", "")
        lang = data.get("lang", "fr").lower()

        template = TEMPLATES.get(lang, TEMPLATES["fr"])
        refutation_text = ""

        if not text_to_challenge:
            return jsonify({"challenge": "", "error": "No analysis text provided."}), 400

        if MOCK_LLM:
            refutation_text = MOCK_REFUTATION.get(lang, MOCK_REFUTATION["fr"])
        else:
            if not client:
                return jsonify({"challenge": "", "error": "HF client not initialized (missing HF_TOKEN)."}), 500

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

        return jsonify({
            "status": "success",
            "challenge": refutation_text,
            "refutation": refutation_text
        }), 200

    except Exception as outer_err:
        print(f"[Challenge Route Error]: {outer_err}")
        return jsonify({"challenge": "", "error": str(outer_err)}), 500

# =====================================================================
# ENDPOINT PDF: /export_pdf
# =====================================================================
@app.route("/export_pdf", methods=["POST", "OPTIONS"])
def export_pdf():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data = request.get_json(silent=True) or {}
        if not data and request.form:
            data = request.form.to_dict(flat=True)

        analysis_text = data.get("analysis") or data.get("report") or ""
        refutation_text = data.get("refutation") or data.get("challenge") or ""
        score_raw = data.get("score", 50)
        try:
            score = int(score_raw or 50)
        except (TypeError, ValueError):
            score = 50
        flags = data.get("flags") or []
        lang = (data.get("lang") or "fr").lower()

        if not analysis_text:
            return jsonify({"error": "No analysis text provided for PDF export."}), 400

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

        style_header_title = ParagraphStyle('HeaderTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=colors.HexColor("#0D2B55"))
        style_header_sub = ParagraphStyle('HeaderSub', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=11, textColor=colors.HexColor("#0D2B55"))
        style_meta = ParagraphStyle('MetaText', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, leading=12, textColor=colors.HexColor("#111111"))
        style_heading = ParagraphStyle('Heading', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor("#0D2B55"), spaceBefore=10, spaceAfter=4)
        style_body = ParagraphStyle('Body', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=13, textColor=colors.HexColor("#111111"), spaceAfter=4)
        style_bullet = ParagraphStyle('Bullet', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=13, textColor=colors.HexColor("#111111"), leftIndent=12, firstLineIndent=-8, spaceAfter=2)
        style_warn_title = ParagraphStyle('WarnTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, leading=11, textColor=colors.HexColor("#8A5E00"))
        style_warn_body = ParagraphStyle('WarnBody', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor("#333333"))
        style_footer = ParagraphStyle('Footer', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=10, textColor=colors.HexColor("#475569"), alignment=1)

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

        style_title = ParagraphStyle('DocTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=colors.HexColor('#0F172A'), spaceAfter=4)
        style_subtitle_sm = ParagraphStyle('DocSubtitle', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=12, textColor=colors.HexColor('#475569'), spaceAfter=12)
        style_card_label = ParagraphStyle('CardLabel', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.white, alignment=1, uppercase=True)
        style_card_value = ParagraphStyle('CardValue', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=16, leading=18, textColor=colors.white, alignment=1)
        style_meta_key = ParagraphStyle('MetaKey', parent=styles['Normal'], fontName='Courier-Bold', fontSize=8, leading=10, textColor=colors.HexColor('#0F172A'))
        style_meta_value = ParagraphStyle('MetaValue', parent=styles['Normal'], fontName='Courier', fontSize=8, leading=10, textColor=colors.HexColor('#0F172A'))
        style_indicator_title = ParagraphStyle('IndicatorTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor('#334155'))
        style_indicator_pill = ParagraphStyle('IndicatorPill', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor('#0F172A'), alignment=1)
        style_section_title = ParagraphStyle('SectionTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.HexColor('#0F172A'), spaceBefore=12, spaceAfter=6)
        style_section_body = ParagraphStyle('SectionBody', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=12, textColor=colors.HexColor('#0F172A'), spaceAfter=4)
        style_small_bullet = ParagraphStyle('SmallBullet', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=12, textColor=colors.HexColor('#0F172A'), leftIndent=10, bulletIndent=0, spaceAfter=2)

        story = []
        story.append(Paragraph("POLETHIC BEACON", style_title))
        story.append(Paragraph("LABORATOIRE D'AUTODÉFENSE COGNITIVE", style_subtitle_sm))

        beacon_ref = f"BEACON-{datetime.now().year}-{int(datetime.now().timestamp()) % 1000000:06d}"
        flags_str = ", ".join(flags).upper() if flags else "NONE"

        badge_table = Table([
            [Paragraph("ETHIC-SCORE", style_card_label)],
            [Paragraph(f"NIVEAU {get_ethic_letter(score)}", style_card_value)]
        ], colWidths=[120])
        badge_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FF6600')),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TEXTCOLOR', (0,0), (-1,-1), colors.white),
            ('INNERPADDING', (0,0), (-1,-1), 6),
            ('BOX', (0,0), (-1,-1), 0, colors.white),
        ]))

        meta_lines = [
            f"<font face='Courier-Bold'>RÉF :</font> {beacon_ref}",
            f"<font face='Courier-Bold'>HORODATAGE :</font> {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        ]
        meta_paragraph = Paragraph('<br />'.join(meta_lines), style_meta_value)

        top_row = Table([
            [badge_table, meta_paragraph]
        ], colWidths=[140, 380])
        top_row.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8f9fa')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#e2e8f0')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 12),
            ('BOTTOMPADDING', (0,0), (-1,-1), 12),
        ]))

        indicator_tags = flags if flags else ['NONE']
        tag_cells = [[Paragraph(tag, style_indicator_pill) for tag in indicator_tags]]
        tags_table = Table(tag_cells, colWidths=[None] * len(indicator_tags))
        tags_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#e2e8f0')),
            ('BOX', (0,0), (-1,-1), 0, colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('INNERPADDING', (0,0), (-1,-1), 4),
            ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor('#0F172A')),
        ]))

        indicator_row = Table([
            [Paragraph("INDICATEURS:", style_indicator_title), tags_table]
        ], colWidths=[90, 430])
        indicator_row.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8f9fa')),
            ('BOX', (0,0), (-1,-1), 0, colors.white),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))

        card_wrapper = Table([
            [top_row],
            [HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#cbd5e1'), spaceBefore=10, spaceAfter=10)],
            [indicator_row]
        ], colWidths=[520])
        card_wrapper.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8f9fa')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#e2e8f0')),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))

        story.append(card_wrapper)
        story.append(Spacer(1, 18))

        for line in analysis_text.split('\n'):
            line_s = line.strip()
            if not line_s:
                continue

            clean_line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line_s)

            if is_heading_line(line_s):
                story.append(Paragraph(clean_line.upper(), style_section_title))
            elif line_s.startswith('- '):
                story.append(Paragraph(clean_line[2:], style_small_bullet, bulletText='•'))
            else:
                story.append(Paragraph(clean_line, style_section_body))

        if refutation_text:
            story.append(Spacer(1, 12))
            story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#94a3b8'), spaceBefore=10, spaceAfter=10))
            story.append(Paragraph(disc["refute_title"], style_section_title))

            warn_content = [
                Paragraph(disc["warn_title"], style_warn_title),
                Spacer(1, 2),
                Paragraph(disc["warn_body"], style_warn_body)
            ]
            t_warn = Table([[warn_content]], colWidths=[520])
            t_warn.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#fff7ed")),
                ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#f97316")),
                ('LEFTPADDING', (0,0), (-1,-1), 10),
                ('RIGHTPADDING', (0,0), (-1,-1), 10),
                ('TOPPADDING', (0,0), (-1,-1), 8),
                ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ]))
            story.append(t_warn)
            story.append(Spacer(1, 8))

            for line in refutation_text.split('\n'):
                line_s = line.strip()
                if line_s:
                    clean_ref = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line_s)
                    story.append(Paragraph(clean_ref, style_section_body))

        story.append(Spacer(1, 15))

        def draw_page_footer(canvas, doc):
            canvas.saveState()
            canvas.setFillColor(colors.HexColor('#475569'))
            canvas.setFont('Helvetica', 8)
            canvas.drawString(36, 20, 'POLETHIC BEACON - Analyse et autodéfense cognitive')
            canvas.drawRightString(letter[0] - 36, 20, f'Page {doc.page}')
            canvas.restoreState()

        def draw_page_background(canvas, doc):
            canvas.saveState()
            canvas.setFillColor(colors.white)
            canvas.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
            draw_page_footer(canvas, doc)
            canvas.restoreState()

        doc.build(story, onFirstPage=draw_page_background, onLaterPages=draw_page_background)
        return send_file(pdf_path, as_attachment=True, download_name=pdf_filename, mimetype='application/pdf')

    except Exception as pdf_err:
        print(f"[Export PDF Error]: {pdf_err}")
        return jsonify({"error": "Failed to generate PDF", "details": str(pdf_err)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
