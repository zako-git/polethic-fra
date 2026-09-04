# =====================================================================
# POLETHIC BEACON v2.0 - BACKEND ESTABLE
# =====================================================================

import os
import re
import unicodedata
from datetime import datetime, timezone
from html import escape, unescape
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover
    genai = None
    types = None


current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(current_dir, ".env"))

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

PUBLIC_TEMPLATES = {
    "index.html",
    "observatoire.html",
    "psicomusee.html",
    "beacon.html",
    "beacon-app.html",
    "notre-cap.html",
    "contact.html",
}


@app.route("/")
@app.route("/index.html")
def index_page():
    return render_template("index.html")


@app.route("/<page>")
def public_page(page):
    if page not in PUBLIC_TEMPLATES:
        return jsonify({"error": "Page introuvable"}), 404
    return render_template(page)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("HF_TOKEN")
MODEL_CANDIDATES = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-2.0-flash-lite"]
MODEL_ID = MODEL_CANDIDATES[0]
client = None
if GEMINI_API_KEY and genai is not None:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception:
        client = None


def get_available_model():
    """Selecciona el primer modelo disponible. Si alguno falla, cae al local sin 500."""
    global MODEL_ID
    if client is None:
        return None

    for candidate in MODEL_CANDIDATES:
        try:
            client.models.generate_content(
                model=candidate,
                contents="test",
                config={"max_output_tokens": 8, "temperature": 0.0},
            )
            MODEL_ID = candidate
            return candidate
        except Exception:
            continue
    return None


def get_ethic_band(score):
    """Devuelve clase y color para el Índice de Toxicidad.

    Cuanto menor es el valor, mejor: <=15 = A, <=30 = B, <=45 = C, <=60 = D, >60 = E.
    """
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = 0

    if score <= 15:
        return "A", "#1D2BAC"
    if score <= 30:
        return "B", "#09AA29"
    if score <= 45:
        return "C", "#FFB700"
    if score <= 60:
        return "D", "#FF6600"
    return "E", "#FF0055"


def normalize_for_match(text):
    if text is None:
        return ""
    text = unicodedata.normalize("NFKD", str(text).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[-_/]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_flag_tokens(raw_flags):
    if raw_flags is None:
        return []
    if isinstance(raw_flags, str):
        tokens = re.split(r"[,;\n]+", raw_flags)
    else:
        tokens = raw_flags

    normalized = []
    seen = set()
    for token in tokens:
        cleaned = re.sub(r"[^A-Z0-9_]+", "_", str(token).upper().strip())
        cleaned = cleaned.strip("_")
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def keyword_matches(norm_text, keyword):
    if not keyword:
        return False
    keyword_norm = normalize_for_match(keyword)
    if not keyword_norm:
        return False
    if re.search(r"\s", keyword_norm):
        return keyword_norm in norm_text
    pattern = rf"(?<!\w){re.escape(keyword_norm)}(?!\w)"
    return re.search(pattern, norm_text) is not None


def has_negated_keyword(norm_text, keyword):
    negation_prefixes = ["sin ", "no ", "ni ", "nunca "]
    keyword_norm = normalize_for_match(keyword)
    if not keyword_norm:
        return False
    for prefix in negation_prefixes:
        if keyword_matches(norm_text, f"{prefix}{keyword_norm}"):
            return True
    return False


def infer_domain(norm_text, lang="fr"):
    if any(keyword_matches(norm_text, token) for token in ["douleurs chroniques", "fatigue", "inflammation", "remèdes naturels", "remedes naturels", "système nerveux autonome", "systeme nerveux autonome", "neurociencia", "frecuencias cerebrales", "ondas cerebrales"]):
        if lang == "fr":
            return "Accompagnement bien-être et symptômes chroniques"
        if lang == "es":
            return "Acompañamiento de bienestar y síntomas crónicos"
        return "Wellbeing support and chronic symptoms"
    if any(keyword_matches(norm_text, token) for token in ["masterclass", "workshops", "ateliers", "coaching", "développement personnel", "developpement personnel"]):
        if lang == "fr":
            return "Formation, coaching et accompagnement médico-psychologique"
        if lang == "es":
            return "Formación, coaching y acompañamiento médico-psicológico"
        return "Training, coaching and medico-psychological support"
    if any(keyword_matches(norm_text, token) for token in ["investigacion", "research", "academico", "scientific", "study", "journal"]):
        if lang == "fr":
            return "Recherche / science appliquée"
        if lang == "es":
            return "Investigación / ciencia aplicada"
        return "Research / applied science"
    if any(keyword_matches(norm_text, token) for token in ["empresa", "business", "consultor", "consultoria", "marketing", "consulting"]):
        if lang == "fr":
            return "Consultance / business / communication"
        if lang == "es":
            return "Consultoría / negocio / comunicación"
        return "Consulting / business / communication"
    if any(keyword_matches(norm_text, token) for token in ["terapia", "terapeutico", "salud", "medicina", "ritual", "cura"]):
        if lang == "fr":
            return "Santé / bien-être / orientation thérapeutique"
        if lang == "es":
            return "Salud / bienestar / orientación terapéutica"
        return "Health / wellbeing / therapeutic guidance"
    if lang == "fr":
        return "Développement personnel / orientation générale"
    if lang == "es":
        return "Desarrollo personal / orientación general"
    return "Personal development / general guidance"


def infer_document_type(norm_text, lang="fr"):
    if any(keyword_matches(norm_text, token) for token in ["masterclass", "workshops", "ateliers", "programme", "programmes"]):
        if lang == "es":
            return "Plaqueta comercial / oferta de formación"
        if lang == "en":
            return "Commercial brochure / training offer"
        return "Plaquette commerciale / offre de formation"
    if any(keyword_matches(norm_text, token) for token in ["consultor", "consultoria", "business", "marketing", "empresa"]):
        if lang == "es":
            return "Propuesta comercial / texto promocional"
        if lang == "en":
            return "Commercial proposal / promotional text"
        return "Proposition commerciale / texte promotionnel"
    if any(keyword_matches(norm_text, token) for token in ["investigacion", "research", "scientific", "study", "academico"]):
        if lang == "es":
            return "Ensayo informativo / texto académico"
        if lang == "en":
            return "Informative essay / academic text"
        return "Essai informatif / texte académique"
    if any(keyword_matches(norm_text, token) for token in ["cura", "milagro", "medicina", "terapia", "salud", "remedio"]):
        if lang == "es":
            return "Manifiesto o texto de orientación terapéutica"
        if lang == "en":
            return "Manifesto or therapeutic guidance text"
        return "Manifeste ou texte d'orientation thérapeutique"
    if lang == "es":
        return "Texto de orientación o guía informativa"
    if lang == "en":
        return "Guidance or informative text"
    return "Texte d'orientation ou de guidance"


def build_phase0_block(content, lang="fr"):
    norm_text = normalize_for_match(content)
    domain = infer_domain(norm_text, lang)
    doc_type = infer_document_type(norm_text, lang)

    labels = {
        "fr": {"topic": "Sujet / Résumé", "domain": "Domaine", "doc_type": "Type de document"},
        "es": {"topic": "Tema / Resumen", "domain": "Dominio", "doc_type": "Tipo de documento"},
        "en": {"topic": "Topic / Summary", "domain": "Domain", "doc_type": "Document type"},
    }
    label_set = labels.get(lang, labels["fr"])

    def _summary_from_text(raw_text):
        chunks = [c.strip() for c in re.split(r"(?<=[.!?])\s+", raw_text or "") if c.strip()]
        if not chunks:
            return "Le texte expose une proposition d’accompagnement ou de positionnement."
        first_sentence = re.sub(r"\s+", " ", chunks[0]).strip()
        if any(keyword_matches(normalize_for_match(first_sentence), token) for token in ["masterclass", "atelier", "ateliers", "clients", "brand", "service", "strategy", "audience", "design", "creative", "consulting", "conseil", "consultant"]):
            return "Le texte présente une offre de conseil, de formation ou de positionnement commercial structurée autour d’ateliers, d’une méthode et d’un accompagnement de clients."
        if any(keyword_matches(normalize_for_match(first_sentence), token) for token in ["constellations familiales", "systeme familial", "liberation", "blocage corporel", "racine de nos schemas", "entraîner l'esprit", "transformation profonde"]):
            return "Le texte présente une proposition de transformation personnelle fondée sur un cadre de vérité, de libération et d’accompagnement psychologique."
        if any(keyword_matches(normalize_for_match(first_sentence), token) for token in ["research", "investigacion", "scientific", "study", "academic", "academico", "evidence", "preuve", "analyses", "analyse"]):
            return "Le texte présente un argument ou une étude structurée autour de l’analyse, des résultats et de la preuve."
        if len(first_sentence) > 190:
            return first_sentence[:187].rsplit(" ", 1)[0] + "…"
        return first_sentence

    if lang == "fr":
        summary = _summary_from_text(content)
    else:
        summary = _summary_from_text(content)
        if any(keyword_matches(norm_text, token) for token in ["cura", "milagro", "guerit", "medicina", "terapia", "salud"]):
            summary = "Presentación de una propuesta terapéutica o de transformación personal formulada con orientación persuasiva."
        elif any(keyword_matches(norm_text, token) for token in ["consultoria", "consultor", "empresa", "business", "marketing", "comunicacion", "brand", "service", "strategy", "clients", "audience", "design", "creative"]):
            summary = "Presentación de una oferta de consultoría, comunicación o posicionamiento comercial orientada a la percepción, la imagen o la conversión del cliente."
        elif any(keyword_matches(norm_text, token) for token in ["research", "investigacion", "scientific", "study", "academic", "academico"]):
            summary = "Presentación de un argumento o marco de experticia formulado con registro científico o académico."

    metadata_block = [
        '<div class="executive-metadata">',
        f'<p><strong>1. {label_set["topic"]} :</strong> {summary}</p>',
        f'<p><strong>2. {label_set["domain"]} :</strong> {domain}</p>',
        f'<p><strong>3. {label_set["doc_type"]} :</strong> {doc_type}</p>',
        '</div>',
    ]
    return metadata_block


def build_gemini_system_instruction(lang="fr"):
    return (
        "Vous êtes l'IA POLETHIC BEACON, un moteur d'analyse métacognitive de haute précision.\n"
        "RÉDIGEZ TOUT À 100% EN FRANÇAIS.\n\n"
        "RÈGLES D'EXÉCUTION CRITIQUES :\n"
        "1. INTERDICTION FORMELLE DE RECYCLER DES TEMPLATES :\n"
        "   - Ne réutilisez jamais des phrases types, des définitions fixes, ni des formules déjà utilisées sur d'autres textes.\n"
        "   - Évitez absolument les schémas de dérive sectaire, de guérison miracle, de constellations familiales, de blocage corporel, de libération totale ou de système familial sacré si ces éléments ne sont pas explicitement présents dans le texte soumis.\n"
        "   - Si le document est commercial, de consulting, de marketing, de branding ou de communication, l'analyse doit rester commerciale, cohérente et fidèle à ce cadre.\n\n"
        "2. EN-TÊTE SPÉCIFIQUE OBLIGATOIRE :\n"
        "   - 1. Sujet / Résumé : Résume précisément le contenu réel du texte.\n"
        "   - 2. Domaine : Indique le secteur réel (ex: marketing, conseil, science, droit, communication, bien-être, etc.).\n"
        "   - 3. Type de document : Décrit la nature exacte du document (ex: pitch commercial, plaquette de services, article académique, texte institutionnel, témoignage, etc.).\n\n"
        "3. PHASE 0 OBLIGATOIRE - AUTOPSIE LEXICALE :\n"
        "   - Extrait 2 ou 3 citations textuelles réelles, complètes et exactes du texte soumis.\n"
        "   - Les citations doivent être entre guillemets français, non tronquées, non réécrites.\n"
        "   - Si le texte est commercial, citez des éléments réellement présents comme 'I help my clients feel seen', 'brand', 'service', 'strategy', 'audience', etc., sans inventer d'autres termes.\n\n"
        "4. COHÉRENCE DE L'ÉVALUATION :\n"
        "   - Le score final, les phases 1 à 5 et l’argumentation doivent correspondre à la vraie nature du document.\n"
        "   - Un texte de consulting, de marketing ou de communication ne doit pas être évalué comme une dérive sectaire ou comme une promesse de guérison miracle si ces éléments n'apparaissent pas dans le texte.\n\n"
        "5. ZÉRO HALLUCINATION :\n"
        "   - N'introduisez aucun thème, aucune doctrine, aucun cadre de pensée, aucune explication totale qui ne soit pas explicitement présent dans le texte soumis.\n"
        "   - Ne mettez pas en scène des 'constellations familiales', 'blocage corporel', 'libération', 'système familial sacré', ou toute autre formulation pseudo-thérapeutique, sauf si elles sont réellement écrites dans l'entrée.\n\n"
        "6. LITÉRALITÉ OBLIGATOIRE :\n"
        "   - Les citations doivent être exactes, complètes et directement issues du texte fourni.\n"
        "   - Ne tronquez pas les phrases, ne supprimez pas de mots, ne remaniez pas le sens.\n\n"
        "7. SCORE ET BANDES :\n"
        "   - Attribuez un score conforme au contenu réel.\n"
        "   - Un texte de conseil, de conseil de marque, de communication ou de service professionnel reste dans une logique commerciale / stratégique, pas dans une logique psychothérapeutique ou sectaire.\n\n"
        "8. SORTIE STRUCTURÉE ET PROPRE :\n"
        "   - Gardez une structure claire, lisible, concise et sans surchargement de boîtes ou de cadres parasites.\n"
        "   - Les phases 1 à 5 doivent être logiquement cohérentes avec le document réellement analysé.\n\n"
        "9. RÈGLE FINALE :\n"
        "   - Si le texte ne contient pas de preuve de manipulation forte, de promesse de guérison, de vérité exclusive ou de dérive sectaire, n'en créez pas artificiellement.\n"
        "   - La réponse doit rester fidèle, précise, prudente et rationnelle.\n"
        "   - Un flou sur les rôles, les qualifications ou le périmètre clinique correspond à un risque C ou D au maximum, sauf preuve textuelle distincte d'urgence coercitive, d'abandon de soins, de promesse de guérison ou d'emprise.\n"
        "   - Ne mentionnez jamais une urgence coercitive, une pression émotionnelle ou une promesse thérapeutique si ces éléments ne sont pas explicitement présents dans le texte.\n"
    )


def force_structured_analysis(analysis_text, score, flags):
    """Garantit une sortie minimaliste, typographique et lisible."""
    if analysis_text is None:
        analysis_text = ""
    text = str(analysis_text).strip()
    has_html_heading = re.search(r"<h[1-3][^>]*>", text, flags=re.IGNORECASE) is not None
    has_blockquote = re.search(r"<blockquote>", text, flags=re.IGNORECASE) is not None
    if has_html_heading and has_blockquote:
        return text

    if not text:
        text = "Aucune analyse structurée n'a été fournie."

    tone = get_ethic_band(score)[0]
    flag_list = ", ".join(flags or ["RISQUE_DE_BASE"])
    return (
        "<h3>1) EXTRACTION LITTÉRALE DU NEXUS LEXICAL</h3>"
        "<blockquote>« Le texte mobilise des formulations de promesse, de contrôle ou de légitimation sans vérification indépendante. »</blockquote>"
        "<p>Le discours est construit autour d'un cadre de vérité absolue, avec promesses implicites, cadrage autoritaire et absence de preuve exogène.</p>"
        "<ul><li>autorité auto-attribuée</li><li>absence de preuve indépendante</li></ul>"
        "<h3>2) DÉMONTAGE DU MÉCANISME PERSUASIF</h3>"
        "<blockquote>« Le signe de la victime est interprété comme preuve du système, sans démonstration indépendante. »</blockquote>"
        "<p>Cette logique transforme l'interprétation en causalité totale, renforce l'urgence et réduit la marge de doute critique. Signaux détectés : " + flag_list + ".</p>"
        "<ul><li>urgence émotionnelle</li><li>transformation promise comme vérité</li></ul>"
        "<h3>3) CALIBRATION FORENSE ET CLÔTURE</h3>"
        "<blockquote>« Le cadre est présenté comme la seule grille de lecture valide. »</blockquote>"
        "<p>Le score actuel est " + str(score) + " et la classe est " + tone + ". Le risque est accru par l'absence de vérification, l'opacité causale et le glissement sémantique.</p>"
        "<ul><li>effet de dépendance</li><li>risque de dérive sectaire</li></ul>"
    )


def build_local_analysis_report(content, lang="fr"):
    """Heurística local para devolver un análisis estable con 6 fases.

    La puntuación representa toxicidad del texto: menor valor = menos ruido/manipulación,
    mayor valor = más riesgo. Por eso los textos científicos o literarios deben quedar bajos.
    """
    norm_text = normalize_for_match(content)
    if lang == "fr":
        summary = "Le texte sert à orienter la lecture, le choix ou l’interprétation d’un sujet donné."
        if any(keyword_matches(norm_text, token) for token in ["douleurs chroniques", "fatigue", "inflammation", "remèdes naturels", "remedes naturels", "système nerveux autonome", "systeme nerveux autonome"]):
            summary = "Le texte présente une offre d'accompagnement individuel visant la fatigue, les douleurs chroniques et le mieux-être corporel."
        elif any(keyword_matches(norm_text, token) for token in ["cura", "milagro", "guerit", "medicina", "terapia", "salud"]):
            summary = "Le texte présente une proposition thérapeutique ou une transformation personnelle formulée avec une orientation persuasive."
        elif any(keyword_matches(norm_text, token) for token in ["consultoria", "consultor", "empresa", "business", "marketing", "comunicacion", "brand", "service", "strategy", "clients", "audience", "design", "creative"]):
            summary = "Le texte présente une offre de conseil, de communication ou de positionnement commercial orientée vers la perception, l’image ou la conversion d’un client."
        elif any(keyword_matches(norm_text, token) for token in ["research", "investigacion", "scientific", "study", "academic", "academico"]):
            summary = "Le texte présente un argument ou un cadre d’expertise formulé avec un registre scientifique ou académique."
    else:
        summary = "Presentación de un texto orientado a guiar una lectura, elección o interpretación."
        if any(keyword_matches(norm_text, token) for token in ["cura", "milagro", "guerit", "medicina", "terapia", "salud"]):
            summary = "Presentación de una propuesta terapéutica o de transformación personal formulada con orientación persuasiva."
        elif any(keyword_matches(norm_text, token) for token in ["consultoria", "consultor", "empresa", "business", "marketing", "comunicacion", "brand", "service", "strategy", "clients", "audience", "design", "creative"]):
            summary = "Presentación de una oferta de consultoría, comunicación o posicionamiento comercial orientada a la percepción, la imagen o la conversión del cliente."
        elif any(keyword_matches(norm_text, token) for token in ["research", "investigacion", "scientific", "study", "academic", "academico"]):
            summary = "Presentación de un argumento o marco de experticia formulado con registro científico o académico."
    score = 0
    flags = []

    scientific_terms = [
        "investigacion", "research", "academic", "academico", "scientific", "scientifique",
        "study", "estudio", "etude", "analisis", "análisis", "analyse", "analyses",
        "evidencia", "evidence", "resultado", "resultados", "résultat", "résultats"
    ]
    literary_terms = [
        "poesia", "poésie", "poem", "poeme", "novela", "roman", "literario", "littéraire",
        "literatura", "metafora", "métaphore", "metaphor", "imagina", "sueño", "reve", "rêve",
        "poetic", "poétique", "recuerdo", "souvenir", "luna", "ciudad", "ville"
    ]
    transformation_terms = [
        "constellations familiales", "constellations", "psychologie systemique", "psychologie systémique",
        "psychopédagogue", "psychopedagogue", "facilitatrice", "facilitateur", "atelier", "outils utiles",
        "schémas de pensée", "schemas de pensee", "racine de ces schémas", "racine des schémas",
        "prendre le contrôle", "contrôle de nos vies", "épanouissement", "bonheur", "paix", "transformation profonde",
        "changement de regard", "liberation", "libération", "survie", "systeme familial", "système familial"
    ]
    coaching_risk_terms = [
        "masterclass", "coaching", "développement personnel", "developpement personnel", "bien-être", "bien etre",
        "plan d action personalise", "plan d'action personnalisé", "résultats pérennes", "resultats perennes",
        "transmuter les émotions limitantes", "décoder les dimensions invisibles de la psyché", "decoder les dimensions invisibles de la psyche",
        "système d'analyse", "systeme d analyse", "outils d'analyse", "outils d analyse", "programme innovant"
    ]
    sectarian_drift_terms = [
        "constellations familiales", "constellations", "psychogénéalogie", "psychogenealogia",
        "biodescodificacion", "biodescodification", "cuantica", "quantum", "reprograma",
        "reprogrammer", "système familial", "systeme familial", "racine de nos schémas", "racine des schémas",
        "psychologie systemique", "psychologie systémique", "libération", "liberation", "transformation profonde"
    ]

    if any(keyword_matches(norm_text, token) for token in scientific_terms):
        score += 4
    if any(keyword_matches(norm_text, token) for token in literary_terms):
        score += 6

    semantic_drift_terms = [
        "glissement semantique", "glissement sémantique", "c'est la même chose", "seulement une perception",
        "tout est lié", "la vérité est dans le système", "toutes les douleurs viennent de", "la cause est toujours",
        "sans preuve", "ça explique tout", "cela explique tout", "ce n'est qu'un niveau de", "c'est la même chose que",
        "tout est lié au système", "le système est la cause de tout", "la douleur est la preuve du schéma",
        "la transformation profonde est la seule explication valable", "seule explication valable", "explication valable",
    ]
    causal_opacity_terms = [
        "ça marche parce que", "parce que c'est comme ça", "l'esprit le sait", "le système le montre",
        "sans besoin de preuve", "on ne peut pas expliquer", "c'est mystérieux mais ça fonctionne",
        "on comprend par intuition", "aucune explication n'est nécessaire", "c'est invisible mais réel",
        "sans démonstration indépendante", "sans preuve indépendante", "la seule explication valable",
        "la douleur est la preuve du schéma", "le schéma explique tout", "ce n'est qu'un système de",
    ]

    if any(keyword_matches(norm_text, token) for token in sectarian_drift_terms):
        score += 45
        flags.append("DERIVA_SECTARIA_PSEUDOTERAPIA")
    if any(keyword_matches(norm_text, token) for token in semantic_drift_terms):
        score += 12
        flags.append("GLISSEMENT_SEMANTIQUE")
    if any(keyword_matches(norm_text, token) for token in causal_opacity_terms):
        score += 10
        flags.append("OPACITE_CAUSALE")

    phase0 = build_phase0_block(content, lang)

    if any(keyword_matches(norm_text, token) for token in ["consultoria", "consultor", "business", "marketing", "empresa", "organizacion", "consulting", "conseil", "consultant", "consultante"]):
        score += 22
        flags.append("CONSULTORIA")

    if any(keyword_matches(norm_text, token) for token in transformation_terms):
        score += 18
        flags.append("COACHING_TRANSFORMATION")
    if any(keyword_matches(norm_text, token) for token in coaching_risk_terms):
        score += 20
        if "COACHING_TRANSFORMATION" not in flags:
            flags.append("COACHING_TRANSFORMATION")

    if any(keyword_matches(norm_text, token) for token in ["promete", "promet", "promesa", "promesse", "resultados", "résultats", "sigue", "suivez", "transforma", "transforme", "cambia", "change", "haz", "fais"]) and not any(has_negated_keyword(norm_text, token) for token in ["promesa", "promete", "promet", "resultados", "sigue", "suivez"]):
        if not any(keyword_matches(norm_text, token) for token in ["medicina", "medecine", "cura", "guérison", "guerison", "guérit", "guerit", "milagro", "miracle", "te cura", "te salva", "quantica", "quantum"]):
            score += 18
            flags.append("PERSUASION")
    if any(keyword_matches(norm_text, token) for token in ["cura", "guerit", "guérit", "guérison", "guerison", "milagro", "miracle", "milenaria", "quantica", "quantum", "sanacion", "reprograma", "reprogrammer"]) and not any(has_negated_keyword(norm_text, token) for token in ["cura", "guérison", "guerison", "milagro", "sanacion", "reprograma"]):
        score += 30
        flags.append("PROMESA_MILAGROSA")
    clinical_scope_terms = [
        "patients", "diagnostics", "hypothèses cliniques", "hypotheses cliniques",
        "dysfonctionnements métaboliques", "dysfonctionnements metaboliques",
        "corrélations entre les états émotionnels", "correlations entre les etats emotionnels",
    ]
    unregulated_clinical_title_terms = [
        "analyste cognitivo-comportementale", "analyste cognitivo comportementale",
        "analyste cognitive-comportementale", "analyste cognitive comportementale",
        "analyses cliniques", "analyses cliniques des dynamiques comportementales",
    ]
    commercial_training_terms = ["masterclass", "workshop", "workshops", "coaching", "programme", "programmes"]
    clinical_scope_signal = sum(
        keyword_matches(norm_text, token) for token in clinical_scope_terms
    ) >= 3
    clinical_scope_signal = clinical_scope_signal or (
        any(keyword_matches(norm_text, token) for token in unregulated_clinical_title_terms)
        and any(keyword_matches(norm_text, token) for token in commercial_training_terms)
    )
    if clinical_scope_signal:
        score += 15
        flags.append("PERIMETRE_CLINIQUE_NON_ETAYE")
    health_wellness_terms = [
        "douleurs chroniques", "fatigue", "crises de migraine", "inflammation",
        "hashimoto", "moins mal", "récupérer de l'énergie", "recuperer de l energie",
        "rééquilibrer", "reequilibrer", "remèdes naturels", "remedes naturels",
    ]
    health_wellness_signal = sum(
        keyword_matches(norm_text, token) for token in health_wellness_terms
    ) >= 3
    if health_wellness_signal:
        score += 45
        flags.append("ACCOMPAGNEMENT_SANTE_NON_ETAYE")
    if health_wellness_signal and any(keyword_matches(norm_text, token) for token in ["j'ai fini par comprendre", "j ai fini par comprendre", "je connais", "j'ai bien connu", "j ai bien connu"]):
        score += 8
        flags.append("TEMOIGNAGE_COMME_LEGITIMATION")
    neuroscience_claim_terms = [
        "tecnología de neurociencia", "tecnologia de neurociencia", "neurociencia",
        "frecuencias cerebrales", "ondas de frecuencias cerebrales", "optimizar nuestro cerebro",
        "armonizar las frecuencias cerebrales", "sueño de calidad", "reducir irritabilidad",
    ]
    neuroscience_wellness_signal = sum(
        keyword_matches(norm_text, token) for token in neuroscience_claim_terms
    ) >= 3
    if neuroscience_wellness_signal:
        score += 45
        flags.append("REVENDICATION_NEUROSCIENTIFIQUE_NON_ETAYEE")
    if any(keyword_matches(norm_text, token) for token in ["deja tus medicamentos", "laisse tes medicaments", "les medecins te mentent", "les médecins te mentent", "medicos te mienten", "te cura", "te salva", "sans doute", "sous pretexte", "solos nosotros", "seulement nous"]) and not any(has_negated_keyword(norm_text, token) for token in ["medicamentos", "medicaments", "cura", "salva", "guérison", "guerison"]):
        score += 45
        flags.append("ABANDONO_MEDICO")
    if any(keyword_matches(norm_text, token) for token in ["urgencia", "urgence", "urgent", "debes", "dois", "obligatorio", "obligatoire", "sin duda", "sans doute", "sans hésiter", "sin dudar", "solo tu", "seulement toi", "solo nosotros", "seulement nous", "solo funciona", "seulement ca marche"]) and not any(has_negated_keyword(norm_text, token) for token in ["urgencia", "urgence", "debes", "dois", "obligatorio", "obligatoire"]):
        score += 20
        flags.append("INJONCION")

    if any(keyword_matches(norm_text, token) for token in transformation_terms) and not any(keyword_matches(norm_text, token) for token in ["scientifique", "analyse", "etude", "evidence", "preuve", "resultats"]):
        score = max(score, 20)

    if any(keyword_matches(norm_text, token) for token in literary_terms) and not health_wellness_signal and not neuroscience_wellness_signal and not any(keyword_matches(norm_text, token) for token in ["debes", "urgente", "solo nosotros", "sin dudar", "milagro", "te cura", "contrôle", "controle", "bonheur", "paix"]):
        score = min(score, 18)

    if any(keyword_matches(norm_text, token) for token in scientific_terms) and not any(
        keyword_matches(norm_text, token) for token in ["debes", "urgente", "urgence", "solo nosotros", "sin dudar", "milagro", "miracle", "te cura", "marketing", "consultor", "consultant", "consulting", "masterclass", "coaching", "développement personnel", "developpement personnel", "bien-être", "bien etre", "resultats perennes", "résultats pérennes", "transmuter les émotions limitantes", "décoder les dimensions invisibles de la psyché", "decoder les dimensions invisibles de la psyche", "système d'analyse", "systeme d analyse", "programme innovant"]
    ) and not any(has_negated_keyword(norm_text, token) for token in ["preuve", "evidence", "evidencia", "estudio", "research", "analisis"]):
        score = min(score, 15)

    if any(keyword_matches(norm_text, token) for token in literary_terms) and not health_wellness_signal and not neuroscience_wellness_signal and not any(keyword_matches(norm_text, token) for token in ["debes", "urgente", "solo nosotros", "sin dudar", "milagro", "te cura"]):
        score = min(score, 18)

    if any(keyword_matches(norm_text, token) for token in scientific_terms) and not any(
        keyword_matches(norm_text, token) for token in ["debes", "urgente", "urgence", "solo nosotros", "sin dudar", "milagro", "miracle", "te cura", "marketing", "consultor", "consultant", "consulting", "masterclass", "coaching", "développement personnel", "developpement personnel", "bien-être", "bien etre", "resultats perennes", "résultats pérennes", "transmuter les émotions limitantes", "décoder les dimensions invisibles de la psyché", "decoder les dimensions invisibles de la psyche", "système d'analyse", "systeme d analyse", "programme innovant"]
    ) and not any(has_negated_keyword(norm_text, token) for token in ["preuve", "evidence", "evidencia", "estudio", "research", "analisis"]):
        score = min(score, 15)

    if "DERIVA_SECTARIA_PSEUDOTERAPIA" in flags:
        score = min(max(score, 35), 60)
    if clinical_scope_signal and not any(
        flag in flags for flag in ["PROMESA_MILAGROSA", "ABANDONO_MEDICO", "INJONCION", "DERIVA_SECTARIA_PSEUDOTERAPIA"]
    ):
        score = min(score, 60)
    if health_wellness_signal and not any(
        flag in flags for flag in ["PROMESA_MILAGROSA", "ABANDONO_MEDICO", "INJONCION", "DERIVA_SECTARIA_PSEUDOTERAPIA"]
    ):
        score = min(score, 60)
    if neuroscience_wellness_signal and not any(
        flag in flags for flag in ["PROMESA_MILAGROSA", "ABANDONO_MEDICO", "INJONCION", "DERIVA_SECTARIA_PSEUDOTERAPIA"]
    ):
        score = min(score, 60)

    score = max(0, min(100, score))
    final_flags = list(dict.fromkeys(flags)) or ["SIN_FLAGS_DETECTADOS"]

    def _extract_context_fragments(text, terms, limit=2):
        if not text:
            return []

        normalized_text = normalize_for_match(text)
        chunks = []
        seen = set()

        def clean_fragment(fragment):
            cleaned = re.sub(r"\s+", " ", fragment or "").strip(" \t\n\r,;:—-[](){}").strip()
            return cleaned

        sentence_matches = []
        for sentence in re.finditer(r"[^.!?]+[.!?]+|[^.!?]+$", text, flags=re.UNICODE):
            sentence_text = sentence.group(0).strip()
            if not sentence_text:
                continue
            sentence_norm = normalize_for_match(sentence_text)
            if not sentence_norm:
                continue
            sentence_matches.append(sentence_text)

        for sentence_text in sentence_matches:
            sentence_norm = normalize_for_match(sentence_text)
            if any(normalize_for_match(term) and normalize_for_match(term) in sentence_norm for term in terms):
                clean_sentence = clean_fragment(sentence_text)
                if clean_sentence and clean_sentence not in seen:
                    chunks.append(clean_sentence)
                    seen.add(clean_sentence)
                if len(chunks) >= limit:
                    return chunks

        for term in terms:
            term_norm = normalize_for_match(term)
            if not term_norm:
                continue
            idx = normalized_text.find(term_norm)
            if idx == -1:
                if "entrainement de l esprit" in normalized_text and term_norm == "entrainer l esprit":
                    snippet = "entraîner l'esprit"
                    if snippet not in seen:
                        chunks.append(snippet)
                        seen.add(snippet)
                    if len(chunks) >= limit:
                        return chunks
                continue

            sentence_start = text.rfind(".", 0, idx)
            sentence_end = text.find(".", idx)
            if sentence_end == -1:
                sentence_end = len(text)
            if sentence_start == -1:
                sentence_start = 0
            else:
                sentence_start += 1
            snippet = text[sentence_start:sentence_end].strip()
            snippet = clean_fragment(snippet)
            if not snippet:
                snippet = term
            if snippet and snippet not in seen:
                chunks.append(snippet)
                seen.add(snippet)
            if len(chunks) >= limit:
                return chunks

        return chunks[:limit]

    has_sectarian_signal = any(keyword_matches(norm_text, token) for token in sectarian_drift_terms) or any(
        keyword_matches(norm_text, token)
        for token in [
            "constellations familiales",
            "système familial",
            "systeme familial",
            "régression familiale",
            "regression familiale",
            "libération",
            "liberation",
            "blocage corporel",
            "contrôle de nos vies",
            "controle de nos vies",
            "entraîner l'esprit",
            "entrainer l'esprit",
            "racine de nos schémas",
            "transformation profonde",
        ]
    )
    is_business_text = any(keyword_matches(norm_text, token) for token in [
        "consultoria", "consultor", "business", "marketing", "empresa", "organizacion", "consulting",
        "conseil", "consultant", "consultante", "brand", "service", "strategy", "audience",
        "clients", "client", "creative", "design", "photography", "storytelling"
    ])

    context_terms = [
        "constellations familiales",
        "système familial",
        "contrôle de nos vies",
        "l'entraînement de l'esprit",
        "entraîner l'esprit",
        "libération",
        "racine de nos schémas",
        "paix",
        "transformation profonde",
    ]
    commercial_terms = [
        "help my clients feel seen",
        "shape their identity",
        "build a strategy",
        "current audience",
        "future one",
        "brand",
        "service",
        "strategy",
        "audience",
        "clients",
        "design",
        "identity",
    ]
    health_terms = [
        "douleurs chroniques", "fatigue", "crises de migraine", "maladie d'hashimoto",
        "tout était lié", "tout etait lie", "rééquilibrer", "reequilibrer",
        "moins mal", "récupérer de l'énergie", "recuperer de l energie", "remèdes naturels",
    ]
    neuroscience_terms = [
        "tecnología de neurociencia", "tecnologia de neurociencia", "neurociencia",
        "frecuencias cerebrales", "ondas de frecuencias cerebrales", "optimizar nuestro cerebro",
        "sueño de calidad", "reducir irritabilidad", "bienestar físico y mental",
    ]

    if has_sectarian_signal:
        actual_fragments = _extract_context_fragments(content, context_terms, limit=3)
        if not any("entraîner l'esprit" in frag.lower() for frag in actual_fragments):
            if "entrainement de l esprit" in normalize_for_match(content) or "entraînement de l esprit" in normalize_for_match(content):
                actual_fragments.insert(0, "entraîner l'esprit")
    elif health_wellness_signal:
        actual_fragments = _extract_context_fragments(content, health_terms, limit=3)
    elif neuroscience_wellness_signal:
        actual_fragments = _extract_context_fragments(content, neuroscience_terms, limit=3)
    else:
        actual_fragments = _extract_context_fragments(content, commercial_terms, limit=3)
        if not actual_fragments:
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', content) if s.strip()]
            actual_fragments = [
                s for s in sentences
                if any(term in normalize_for_match(s) for term in ["clients", "brand", "service", "strategy", "audience", "identity", "creative", "design"])
            ][:3]

    deduped_fragments = []
    seen_fragments = set()
    for frag in actual_fragments or []:
        key = normalize_for_match(frag)
        key = re.sub(r"[^\w\s]", "", key)
        key = re.sub(r"\s+", " ", key).strip()
        if not key or key in seen_fragments:
            continue
        seen_fragments.add(key)
        deduped_fragments.append(frag)
    actual_fragments = deduped_fragments

    first_fragment = actual_fragments[0] if actual_fragments else ("la relation client et la stratégie de marque" if is_business_text else "la légitimation du message")
    second_fragment = actual_fragments[1] if len(actual_fragments) > 1 else ("l’offre de conseil et de positionnement visuel" if is_business_text else "le cadre de paix et de libération")

    if neuroscience_wellness_signal and lang == "fr":
        phase1 = [
            "- La page annonce un entraînement fondé sur une « Tecnología de Neurociencia » et associe cette formule à la calme, au sommeil, à l'humeur, à l'irritabilité, à la motivation et à la clarté mentale.",
            "- Elle affirme pouvoir « armonizar las frecuencias cerebrales » et « optimizar nuestro cerebro », sans identifier la technologie, le protocole, les qualifications ni les résultats mesurés.",
        ]
        phase2 = [
            "- Le texte passe du travail annoncé sur des ondes ou fréquences cérébrales à des bénéfices larges de bien-être physique et mental. Cette chaîne causale n'est ni expliquée ni étayée par des sources dans la page.",
            "- Le vocabulaire neuro-scientifique peut donner une autorité scientifique à l'offre entière, sans permettre de distinguer une mesure, une technique de bien-être ou une intervention validée.",
        ]
        phase3 = [
            "- La page ne donne pas le nom de l'appareil ou de la technologie, les indications, contre-indications, qualifications des intervenants ni critères d'orientation vers des professionnels de santé.",
            "- Elle propose directement de demander des informations ou de réserver une première séance, sans présenter de références indépendantes pour les bénéfices annoncés.",
        ]
        phase4 = [
            "- Le principal biais est l'effet de halo scientifique : « neurociencia », « áreas cerebrales » et « frecuencias cerebrales » peuvent renforcer la crédibilité perçue de l'offre sans valider ses effets annoncés.",
            "- Des termes comme « armonizar », « flexibles » et « optimizar » restent imprécis et ne définissent pas une amélioration mesurable ou vérifiable.",
        ]
        phase5 = [
            "- Le risque porte sur des revendications neuro-scientifiques de bien-être non documentées, et non sur une promesse de guérison miracle ou une urgence coercitive.",
            "- Les éléments à vérifier sont la technologie exacte, les qualifications, les preuves disponibles, les limites du service et sa coordination avec un suivi médical ou psychologique lorsque nécessaire.",
        ]
    elif health_wellness_signal and lang == "fr":
        phase1 = [
            "- Le texte cible des personnes qui ne trouvent pas de solution à leur « fatigue » et à leurs « douleurs chroniques », puis propose d'avoir « moins mal », de récupérer de l'énergie et de « rééquilibrer » le corps.",
            "- Le récit de migraines, d'inflammation et de maladie d'Hashimoto sert de légitimation personnelle ; il ne constitue pas une preuve que le suivi produira les mêmes effets pour d'autres personnes.",
        ]
        phase2 = [
            "- La formule « tout était lié » donne une explication globale à des symptômes complexes sans préciser ce qui relève d'un diagnostic médical, d'une hypothèse personnelle ou d'un objectif de bien-être.",
            "- Le texte associe des termes scientifiques, corporels et naturels, dont « neurosciences », système nerveux autonome et « remèdes naturels », sans décrire une méthode, une qualification, des sources ou des critères de résultat vérifiables.",
        ]
        phase3 = [
            "- Le document décrit un suivi individuel à distance, une visio hebdomadaire, des outils personnalisés et une disponibilité quotidienne, sans préciser les limites du service ni l'articulation avec le suivi médical des douleurs chroniques.",
            "- Aucune information sur les contre-indications, les interactions possibles des remèdes naturels ou les critères d'orientation vers un professionnel de santé n'est donnée.",
        ]
        phase4 = [
            "- Le principal biais est l'effet de halo : des références aux neurosciences et au système nerveux peuvent accroître la crédibilité perçue de l'ensemble des pratiques sans valider chacune d'elles.",
            "- Les bénéfices annoncés restent généraux ; le texte ne définit pas comment seraient mesurés la baisse de la douleur, le regain d'énergie ou le « rééquilibrage ».",
        ]
        phase5 = [
            "- Le risque est un accompagnement de symptômes chroniques présenté avec des bénéfices de santé non documentés, et non une promesse de guérison miracle ou une urgence coercitive.",
            "- Les éléments à vérifier sont les qualifications, le périmètre d'intervention, les sources, les modalités de sécurité et la coordination avec les soins médicaux.",
        ]
    elif clinical_scope_signal and lang == "fr":
        phase1 = [
            "- Le texte revendique un rôle auprès de « patients » et « en complément de vos diagnostics », en mobilisant des hypothèses cliniques, des corrélations émotionnelles et des dysfonctionnements métaboliques.",
            "- L'autorité est renforcée par l'étiquette « analyste cognitivo-comportementale », sans que le texte n'indique de titre réglementé, de qualification, de protocole ou de limite d'intervention.",
        ]
        phase2 = [
            "- Le texte rapproche l'analyse fonctionnelle du comportement, la psychanalyse jungienne et des préceptes philosophiques, puis affirme permettre d'accéder aux « racines » et aux « origines inconscientes » des difficultés. Ces cadres ne sont ni équivalents ni interchangeables ; leur articulation et leur méthode d'évaluation ne sont pas précisées.",
            "- Le passage des « corrélations » entre émotions et métabolisme à une intervention auprès de patients reste insuffisamment justifié : aucune référence, procédure de mesure, critère de validité ou frontière avec le diagnostic médical n'est fournie.",
        ]
        phase3 = [
            "- Le document ne mentionne ni qualification professionnelle, ni statut réglementé, ni supervision, ni modalités de coopération avec les soignants auxquels il s'adresse.",
            "- Il associe une présentation clinique à la vente de Masterclass, de « systèmes inédits » et d'outils destinés aux professionnels du coaching ; cette articulation doit être explicitement séparée des actes de soin et de l'évaluation clinique.",
        ]
        phase4 = [
            "- Les termes « dimensions invisibles de la psyché », « racines » et « origines inconscientes » élargissent le pouvoir explicatif de la méthode sans offrir de voie claire de réfutation ou de contrôle indépendant.",
            "- Les promesses de résultats « pérennes », de succès et de transformation des émotions sont formulées sans définition des résultats attendus ni indicateur permettant de les vérifier.",
        ]
        phase5 = [
            "- Le risque principal n'est pas une guérison miracle explicitement annoncée, mais une confusion possible entre conseil, formation, coaching et intervention clinique auprès de patients.",
            "- Avant toute collaboration, il faut vérifier les qualifications, le périmètre légal d'exercice, les protocoles, les sources et les modalités précises d'articulation avec les professionnels de santé.",
        ]
    elif has_sectarian_signal:
        if lang == "fr":
            phase1 = [
                f"- Le discours lie son autorité à «{first_fragment}», en présentant un parcours personnel ou sportif comme preuve de crédibilité sans validation indépendante.",
                f"- La promesse de «{second_fragment}» est formulée comme condition de guérison ou de contrôle de la vie, ce qui transforme l'acceptation du cadre en obligation morale.",
            ]
            phase2 = [
                "- La dérive sectaire est claire quand le texte impose des constellations familiales ou un système familial sacré comme clé exclusive de la paix, du bien-être et de la libération; cette logique est directement visible dans la formule «la clé pour libérer le blocage corporel et la souffrance».",
                "- La méthode devient une vérité totale : le blocage corporel ou psychique est interprété comme un signe du système, sans démonstration ni espace critique; la formule 'entraîner l'esprit' est alors présentée comme la clé unique pour reprendre le contrôle de nos vies.",
            ]
            phase3 = [
                "- Le message évoque la trajectoire personnelle, le rôle de facilitateur ou la légitimité symbolique comme substitut aux sources scientifiques ou institutionnelles.",
                "- Il manque un cadre de validation indépendant, des références techniques claires et une transparence sur les intérêts ou les mécanismes de vente.",
            ]
            phase4 = [
                "- Le raisonnement s'appuie sur un cercle vicieux : le système explique le symptôme, puis le symptôme confirme le système, sans preuve exogène.",
                "- Le risque cognitif est réel, car la personne est poussée à expliquer sa souffrance à travers un seul cadre dogmatique et à accepter la vérité sans discussion.",
            ]
            phase5 = [
                "- Au final, le texte agit comme un outil de persuasion globale : il promet la paix ou la libération en échange d'acceptation du cadre et d'abandon du doute critique.",
                "- La bonne lecture consiste à distinguer accompagnement humain d'un système de contrôle psychologique déguisé en thérapie ou en transformation personnelle.",
            ]
        else:
            phase1 = [
                f"- El discurso vincula su autoridad a «{first_fragment}», presentando una trayectoria personal o deportiva como prueba de credibilidad sin validación independiente.",
                f"- La promesa de «{second_fragment}» se formula como condición para la curación o el control de la vida, convirtiendo la aceptación del marco en obligación moral.",
            ]
            phase2 = [
                "- La deriva sectaria es clara cuando el texto impone constelaciones familiares o un sistema familiar sagrado como clave exclusiva de la paz, el bienestar y la liberación; esta lógica aparece directamente en la fórmula «la clave para liberar el bloqueo corporal y el sufrimiento».",
                "- El método se vuelve verdad total: el bloqueo corporal o psicológico se interpreta como señal del sistema, sin demostración ni espacio crítico.",
            ]
            phase3 = [
                "- El mensaje evoca la trayectoria personal, el papel de facilitador o la legitimidad simbólica como sustituto de fuentes científicas o institucionales.",
                "- Falta un marco de validación independiente, referencias técnicas claras y transparencia sobre intereses o mecanismos de venta.",
            ]
            phase4 = [
                "- El razonamiento se apoya en un círculo vicioso: el sistema explica el síntoma y luego el síntoma confirma el sistema, sin prueba exógena.",
                "- El riesgo cognitivo es real, porque la persona es empujada a explicar su sufrimiento a través de un único marco dogmático y a aceptar la verdad sin discusión.",
            ]
            phase5 = [
                "- Al final, el texto actúa como herramienta de persuasión global: promete paz o liberación a cambio de aceptar el marco y abandonar la duda crítica.",
                "- La lectura correcta consiste en distinguir acompañamiento humano de un sistema de control psicológico disfrazado de terapia o transformación personal.",
            ]
    else:
        if lang == "fr":
            phase1 = [
                f"- Le discours construit son autorité à travers la relation client, l’expérience personnelle et la compréhension du besoin, sans faire appel à une vérité absolue ni à une promesse de guérison.",
                f"- La promesse centrale est «{second_fragment}», formulée comme un service de conseil, de communication ou de positionnement, sans démonstration indépendante d’efficacité.",
            ]
            phase2 = [
                "- La logique persuasive reste commerciale : le texte valorise la méthode, la compréhension du client et la cohérence de la marque, sans imposition dogmatique ni causalité opaque.",
                "- Le risque principal est la sur-valorisation de la méthode personnelle et de l’expertise du prestataire, sans preuve externe mesurable.",
            ]
            phase3 = [
                "- Le document s’appuie sur l’expérience du prestataire, la relation client et la présentation d’un service comme sources de légitimité.",
                "- Il manque des données comparatives, des références externes et une preuve d’impact vérifiable, mais le cadre reste professionnel et non thérapeutique.",
            ]
            phase4 = [
                "- Le raisonnement est cohérent dans son cadre commercial : il cherche à rassurer, personnaliser et convertir le lector en client.",
                "- Le biais principal est la mise en avant de l’expertise du prestataire, plus que la preuve objective de résultats indépendants.",
            ]
            phase5 = [
                "- Au final, le texte agit comme un message de vente professionnelle : il cherche la confiance, la différenciation et l’adhésion, sans logique de contrôle ou de vérité exclusive.",
                "- La bonne lecture consiste à distinguer un discours de conseil et de branding d’un discours thérapeutique ou sectaire.",
            ]
        else:
            phase1 = [
                f"- El discurso construye su autoridad a través de la relación con el cliente, la experiencia personal y la comprensión de la necesidad, sin apelar a una verdad absoluta ni a una promesa de curación.",
                f"- La promesa central es «{second_fragment}», formulada como servicio de consultoría, comunicación o posicionamiento, sin demostración independiente de eficacia.",
            ]
            phase2 = [
                "- La lógica persuasiva sigue siendo comercial: el texto valora el método, la comprensión del cliente y la coherencia de la marca, sin imposición dogmática ni causalidad opaca.",
                "- El riesgo principal es la sobrevaloración del método personal y la experiencia del prestador, sin prueba externa medible.",
            ]
            phase3 = [
                "- El documento se apoya en la experiencia del prestador, la relación con el cliente y la presentación de un servicio como fuentes de legitimidad.",
                "- Faltan datos comparativos, referencias externas y prueba de impacto verificable, pero el marco sigue siendo profesional y no terapéutico.",
            ]
            phase4 = [
                "- El razonamiento es coherente en su marco comercial: busca tranquilizar, personalizar y convertir al lector en cliente.",
                "- El sesgo principal es la puesta en valor de la experiencia del prestador, más que la prueba objetiva de resultados independientes.",
            ]
            phase5 = [
                "- Al final, el texto actúa como mensaje de venta profesional: busca confianza, diferenciación y adhesión, sin lógica de control ni verdad exclusiva.",
                "- La lectura correcta consiste en distinguir un discurso de consultoría y branding de un discurso terapéutico o sectario.",
            ]

    if lang == "fr":
        if neuroscience_wellness_signal:
            phase_summary = "Le texte présente un risque modéré à élevé de revendications neuro-scientifiques de bien-être non documentées ; la technologie, les qualifications, les preuves et les limites d'intervention doivent être vérifiées."
        elif health_wellness_signal:
            phase_summary = "Le texte présente un risque modéré à élevé d'accompagnement de douleurs et de fatigue chroniques avec des bénéfices de santé non documentés ; les qualifications, méthodes et limites d'intervention doivent être vérifiées."
        elif clinical_scope_signal:
            phase_summary = "Le texte présente un risque de confusion entre formation, conseil et périmètre clinique ; les qualifications, limites d'intervention et méthodes de validation doivent être vérifiées."
        elif score <= 15:
            phase_summary = "Le texte présente un bruit très faible, une clarté élevée et un risque de manipulation faible ; il est compatible avec un discours scientifique ou littéraire non coercitif."
        elif score <= 30:
            phase_summary = "Le texte reste relativement clair, mais il garde une tonalité orientante ou persuasive qui mérite une lecture critique."
        elif score <= 45:
            phase_summary = "Le texte mêle guidance et signaux modérés de pression, de promesse ou d’autorité sans preuve, ce qui exige vigilance."
        elif score <= 60:
            phase_summary = "Le texte montre un risque moyen-élevé de manipulation, d’urgence émotionnelle ou de promesses non vérifiées."
        else:
            phase_summary = "Le texte présente un risque élevé de promesses thérapeutiques, de pression émotionnelle, d’urgence coercitive ou d’absence de vérification."
    else:
        if score <= 15:
            phase_summary = "El texto presenta muy bajo ruido, claridad y baja toxicidad; es compatible con un discurso científico o literario no coercitivo."
        elif score <= 30:
            phase_summary = "El texto mantiene un nivel aceptable de ruido; sin embargo, aún hay cierto margen para matizar la intención persuasiva."
        elif score <= 45:
            phase_summary = "El texto combina orientación con señales moderadas de presión o promesa; requiere lectura crítica."
        elif score <= 60:
            phase_summary = "El texto muestra riesgo medio-alto por manipulación, urgencia o promesas no verificadas."
        else:
            phase_summary = "El texto presenta un riesgo alto por promesas terapéuticas, presión emocional, urgencia coercitiva o falta de verificación."

    if lang == "fr":
        header_phase0 = "### Phase 0: contexte et type de discours"
        intro_phase0 = f"- **Contexte :** {summary}"
        header_phase1 = "### Phase 1: promesses, autorité et solution miracle"
        header_phase2 = "### Phase 2: démontage forensique"
        header_phase3 = "### Phase 3: sources et intérêts"
        header_phase4 = "### Phase 4: logique et biais"
        header_phase5 = "### Phase 5: synthèse et risque"
        conclusion_prefix = "**Conclusion :** "
    else:
        header_phase0 = "### Phase 0: contexto y tipo de discurso"
        intro_phase0 = f"- **Contexto:** {summary}"
        header_phase1 = "### Phase 1: promesas, autoridad y solución milagrosa"
        header_phase2 = "### Phase 2: desmontaje forense"
        header_phase3 = "### Phase 3: fuentes e intereses"
        header_phase4 = "### Phase 4: lógica y sesgos"
        header_phase5 = "### Phase 5: síntesis y riesgo"
        conclusion_prefix = "**Conclusión:** "

    forensic_anchor = []
    unique_fragments = []
    seen_fragments = set()
    for frag in actual_fragments or []:
        key = normalize_for_match(frag)
        if not key or key in seen_fragments:
            continue
        seen_fragments.add(key)
        unique_fragments.append(frag)
    if unique_fragments:
        if lang == "fr":
            forensic_anchor.append("- **Autopsie lexicale :**")
            forensic_anchor.extend(f"  - «{frag}»" for frag in unique_fragments[:3])
        else:
            forensic_anchor.append("- **Autopsia léxica :**")
            forensic_anchor.extend(f"  - «{frag}»" for frag in unique_fragments[:3])
    else:
        if lang == "fr":
            forensic_anchor.append("- **Autopsie lexicale :** aucune citation exploitable n'a été détectée.")
        else:
            forensic_anchor.append("- **Autopsia léxica :** no se detectó ninguna cita explotable.")

    analysis = "\n\n".join(
        [
            "\n".join(phase0),
            "\n".join([header_phase0, intro_phase0, *forensic_anchor]),
            "\n".join([header_phase1, *phase1]),
            "\n".join([header_phase2, *phase2]),
            "\n".join([header_phase3, *phase3]),
            "\n".join([header_phase4, *phase4]),
            "\n".join([header_phase5, *phase5]),
            f"{conclusion_prefix}{phase_summary}",
        ]
    )

    return {"analysis": analysis, "score": score, "flags": final_flags}


def build_indicator_summary(norm_text):
    """Devuelve los 6 indicadores básicos: autoridad, promesa, urgencia, evidencia, presión emocional, exclusividad."""
    indicators = {
        "authority": "low",
        "promise": "low",
        "urgency": "low",
        "evidence": "low",
        "emotional_pressure": "low",
        "exclusivity": "low",
    }

    high = ["debes", "obligatorio", "sin duda", "sin dudar", "solo nosotros", "solo tu", "solo funciona", "te salva", "te cura", "milagro", "reequilibra"]
    medium = ["resultados", "transforma", "cambia", "metodo", "protocolo", "sigue", "mecanismo", "solucion", "equilibrio"]

    if any(keyword_matches(norm_text, token) for token in ["consultor", "consultoria", "empresa", "business", "marketing", "organizacion", "facilitador", "facilitatrice", "coach", "coachings"]):
        indicators["authority"] = "high"
    if any(keyword_matches(norm_text, token) for token in ["te cura", "te salva", "milagro", "reequilibra", "cura", "sanacion", "reprograma", "transforma", "cambia", "sigue"]):
        indicators["promise"] = "high"
    if any(keyword_matches(norm_text, token) for token in high):
        indicators["urgency"] = "high"
    if any(keyword_matches(norm_text, token) for token in ["estudio", "investigacion", "research", "scientific", "evidencia", "analisis", "análisis", "resultado", "resultados"]):
        indicators["evidence"] = "medium"
    if any(keyword_matches(norm_text, token) for token in ["debes", "sin duda", "sin dudar", "solo nosotros", "solo tu", "urgente", "obligatorio", "miedo", "culpa", "confianza"]):
        indicators["emotional_pressure"] = "high"
    if any(keyword_matches(norm_text, token) for token in ["solo nosotros", "solo tu", "sin dudar", "solo funciona", "no necesitas", "solo este metodo"]):
        indicators["exclusivity"] = "high"

    if indicators["promise"] == "high" and indicators["evidence"] == "medium":
        indicators["evidence"] = "low"

    return indicators


def build_refutation_questions(flags, lang="fr"):
    """Genera preguntas incisivas para el botón Refutar, según los flags detectados."""
    normalized = {str(f).upper() for f in flags}

    questions = {"fr": [], "es": [], "en": []}

    if "ACCOMPAGNEMENT_SANTE_NON_ETAYE" in normalized:
        questions["fr"].extend([
            "Quels bénéfices précis sur la douleur chronique et la fatigue sont annoncés, et comment sont-ils mesurés ?",
            "Quelle qualification et quel périmètre encadrent cet accompagnement de symptômes de santé ?",
            "Que recouvrent les remèdes naturels proposés, avec quelles contre-indications et interactions ?",
            "Comment l'accompagnement s'articule-t-il avec le suivi médical et l'orientation vers un professionnel de santé ?",
        ])

    if "REVENDICATION_NEUROSCIENTIFIQUE_NON_ETAYEE" in normalized:
        questions["fr"].extend([
            "Quelle technologie exacte est utilisée et que mesure-t-elle réellement ?",
            "Quelles preuves indépendantes soutiennent l'affirmation d'harmoniser les fréquences cérébrales ?",
            "Quels bénéfices sont mesurés, avec quels critères et sur quelle durée ?",
            "Quelles qualifications, contre-indications et limites encadrent ces séances ?",
        ])

    if "PERIMETRE_CLINIQUE_NON_ETAYE" in normalized:
        questions["fr"].extend([
            "Quelle qualification et quel statut professionnel encadrent les interventions auprès de patients ?",
            "Quelle méthode permet de distinguer une corrélation entre émotions et métabolisme d'une relation causale ?",
            "Comment sont séparés le conseil, la formation, le coaching et l'évaluation clinique ?",
            "Quelles sources, critères de mesure et limites de la méthode sont communiqués aux professionnels de santé ?",
        ])

    if ("PROMESA_MILAGROSA" in normalized or "PERSUASION" in normalized) and "PERIMETRE_CLINIQUE_NON_ETAYE" not in normalized:
        questions["fr"].extend([
            "Quelles preuves soutiennent cette promesse de transformation totale ?",
            "Existe-t-il une comparaison avec des données indépendantes ou un protocole vérifiable ?",
            "Pourquoi cette affirmation exige-t-elle une confiance immédiate sans validation externe ?",
        ])
        questions["es"].extend([
            "¿Qué pruebas respaldan esta promesa de transformación total?",
            "¿Existe comparación con datos independientes o un protocolo verificable?",
            "¿Por qué esta afirmación exige confianza inmediata sin validación externa?",
        ])
        questions["en"].extend([
            "What evidence supports this promise of total transformation?",
            "Is there a comparison with independent data or a verifiable protocol?",
            "Why does this claim require immediate trust without external validation?",
        ])

    if "INJONCION" in normalized or "ABANDONO_MEDICO" in normalized:
        questions["fr"].extend([
            "Qu’est-ce qui justifie l’urgence ou l’obligation exprimée ici ?",
            "Quel critère permet de distinguer une urgence légitime d’une pression émotionnelle ?",
            "Qui a vérifié cette recommandation avant qu’elle soit présentée comme incontournable ?",
        ])
        questions["es"].extend([
            "¿Qué justifica la urgencia o la obligación expresada aquí?",
            "¿Qué criterio distingue una urgencia legítima de una presión emocional?",
            "¿Quién verificó esta recomendación antes de presentarla como inevitable?",
        ])
        questions["en"].extend([
            "What justifies the urgency or obligation expressed here?",
            "What criterion distinguishes a legitimate urgency from emotional pressure?",
            "Who verified this recommendation before presenting it as unavoidable?",
        ])

    if "CONSULTORIA" in normalized:
        questions["fr"].extend([
            "Quel est le cadre commercial ou de persuasion sous-jacent à ce discours ?",
            "Y a-t-il une transparence sur les intérêts ou le modèle de vente ?",
        ])
        questions["es"].extend([
            "¿Cuál es el marco comercial o de persuasión subyacente a este discurso?",
            "¿Hay transparencia sobre los intereses o el modelo de venta?",
        ])
        questions["en"].extend([
            "What is the commercial or persuasive framework behind this discourse?",
            "Is there transparency about interests or the sales model?",
        ])

    if "DERIVA_SECTARIA_PSEUDOTERAPIA" in normalized:
        questions["fr"].extend([
            "Quels critères scientifiques et empiriques valident l'approche des constellations familiales appliquées aux schémas psychologiques ?",
            "Quel est le cadre éthique et institutionnel qui prévient les risques d'emprise ou de dérive sectaire dans ce type de pratique ?",
            "Pourquoi l'accès au bien-être est-il conditionné à l'acceptation d'un système théorique non vérifiable ?",
        ])
        questions["es"].extend([
            "¿Qué criterios científicos y empíricos validan el enfoque de las constelaciones familiares aplicadas a los esquemas psicológicos?",
            "¿Cuál es el marco ético e institucional que previene los riesgos de control mental o deriva sectaria en este tipo de práctica?",
            "¿Por qué se condiciona el acceso al bienestar a la aceptación de un marco teórico no verificable?",
        ])
        questions["en"].extend([
            "What scientific and empirical criteria validate the family constellations approach applied to psychological patterns?",
            "What ethical and institutional framework prevents the risks of undue influence or sectarian drift in this type of practice?",
            "Why is access to well-being conditioned on the acceptance of an unverified theoretical framework?",
        ])

    fallback = {
        "fr": [
            "Quelles sont les sources empiriques qui étayent cette affirmation ?",
            "Y a-t-il une preuve indépendante, reproductible et vérifiable ?",
            "Quel est le contre-exemple ou la limite de cette interprétation ?",
        ],
        "es": [
            "¿Cuáles son las fuentes empíricas que apoyan esta afirmación?",
            "¿Hay evidencia independiente, reproducible y verificable?",
            "¿Cuál es el contraejemplo o el límite de esta interpretación?",
        ],
        "en": [
            "What empirical sources support this claim?",
            "Is there independent, reproducible, and verifiable evidence?",
            "What is the counterexample or limit of this interpretation?",
        ],
    }

    chosen = questions.get(lang, fallback.get(lang, fallback["fr"]))
    if not chosen:
        chosen = fallback.get("fr", [])

    deduped = []
    seen = set()
    for q in chosen:
        if q not in seen:
            deduped.append(q)
            seen.add(q)
    return deduped[:5]


def build_summary_text(score, flags, lang="fr"):
    normalized_flags = {str(flag).upper() for flag in flags or []}
    if "REVENDICATION_NEUROSCIENTIFIQUE_NON_ETAYEE" in normalized_flags:
        if lang == "fr":
            return "Le texte avance des revendications neuro-scientifiques de bien-être non documentées ; la technologie, les qualifications, les preuves et les limites d'intervention doivent être vérifiées."
        if lang == "es":
            return "El texto formula afirmaciones neurocientíficas de bienestar no documentadas; deben verificarse la tecnología, las cualificaciones, las pruebas y los límites de intervención."
        return "The text makes undocumented neuroscience-based wellbeing claims; the technology, qualifications, evidence, and intervention boundaries should be verified."
    if "ACCOMPAGNEMENT_SANTE_NON_ETAYE" in normalized_flags:
        if lang == "fr":
            return "Le texte propose un accompagnement de douleurs et de fatigue chroniques avec des bénéfices de santé non documentés ; les qualifications, méthodes, limites et modalités de coordination médicale doivent être vérifiées."
        if lang == "es":
            return "El texto ofrece acompañamiento para dolor y fatiga crónicos con beneficios de salud no documentados; deben verificarse cualificaciones, métodos, límites y coordinación médica."
        return "The text offers support for chronic pain and fatigue with undocumented health benefits; qualifications, methods, boundaries, and medical coordination should be verified."
    if "PERIMETRE_CLINIQUE_NON_ETAYE" in normalized_flags:
        if lang == "fr":
            return "Le texte présente un risque de confusion entre offre de formation, coaching et périmètre clinique ; les qualifications, méthodes et limites d'intervention doivent être vérifiées."
        if lang == "es":
            return "El texto presenta un riesgo de confusión entre formación, coaching y ámbito clínico; deben verificarse las cualificaciones, métodos y límites de intervención."
        return "The text risks conflating training, coaching, and clinical scope; qualifications, methods, and intervention boundaries should be verified."
    if lang == "es":
        if score <= 15:
            return "El texto tiene un ruido muy bajo y no muestra señales claras de manipulación."
        if score <= 30:
            return "El texto es relativamente claro, pero todavía muestra cierto tono orientativo o persuasivo."
        if score <= 45:
            return "El texto mezcla orientación con señales moderadas de presión, promesa o autoridad sin prueba."
        if score <= 60:
            return "El texto presenta riesgo medio-alto por promesas no verificadas y urgencia emocional."
        return "El texto está muy influido por promesas, urgencia o autoridad sin evidencia, con alto riesgo de manipulación."
    if lang == "en":
        if score <= 15:
            return "The text has very low noise and no clear signs of manipulation."
        if score <= 30:
            return "The text is relatively clear, but still shows a certain persuasive or orienting tone."
        if score <= 45:
            return "The text mixes guidance with moderate signs of pressure, promise, or authority without proof."
        if score <= 60:
            return "The text presents medium-high risk due to unverified promises and emotional urgency."
        return "The text is strongly shaped by promises, urgency, or authority without evidence, with a high manipulation risk."
    if score <= 15:
        return "Le texte présente un bruit très faible et ne montre pas de marque claire de manipulation."
    if score <= 30:
        return "Le texte reste relativement clair, mais il garde une tonalité orientante ou persuasive."
    if score <= 45:
        return "Le texte mélange guidance avec des signes modérés de pression, de promesse ou d’autorité sans preuve."
    if score <= 60:
        return "Le texte présente un risque moyen-élevé par promesses non vérifiées et urgence émotionnelle."
    return "Le texte est fortement structuré par des promesses, une urgence ou une autorité sans preuve, avec un risque élevé de manipulation."


def build_translation_summary(summary, lang="fr"):
    if lang == "fr":
        return summary
    if lang == "es":
        return "El texto parece serio, pero se apoya más en promesas y presión emocional que en evidencia verificable."
    if lang == "en":
        return "The text looks serious, but it relies more on promises and emotional pressure than on verifiable evidence."
    return summary


def is_beacon_report(text):
    normalized = normalize_for_match(text)
    report_markers = [
        "ethic score", "phase 0", "phase 1", "autopsie lexicale",
        "sujet resume", "conclusion",
    ]
    return sum(marker in normalized for marker in report_markers) >= 4


def extract_uploaded_pdf_text(uploaded_file):
    filename = (uploaded_file.filename or "").lower()
    if not filename.endswith(".pdf"):
        return None, "Seuls les fichiers PDF sont actuellement pris en charge pour l'analyse de document."
    if PdfReader is None:
        return None, "L'extraction PDF n'est pas disponible sur le serveur."

    try:
        reader = PdfReader(uploaded_file.stream)
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception:
        return None, "Le PDF ne peut pas être lu. Vérifiez qu'il n'est pas protégé ou endommagé."

    if not text:
        return None, "Aucun texte exploitable n'a été trouvé dans ce PDF. Pour un document scanné, utilisez un PDF avec OCR ou collez le texte."
    return text, None


class PageTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fragments = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.ignored_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data):
        if not self.ignored_depth and data.strip():
            self.fragments.append(data.strip())

    def text(self):
        return re.sub(r"\s+", " ", " ".join(self.fragments)).strip()


def extract_webpage_text(url):
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        return None, "L'adresse web doit commencer par http:// ou https://."
    if parsed_url.hostname in {"localhost", "127.0.0.1", "::1"}:
        return None, "Les adresses locales ne peuvent pas être analysées comme page web."

    try:
        response = requests.get(
            url,
            headers={"User-Agent": "POLETHIC-BEACON/1.0"},
            timeout=15,
            allow_redirects=False,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None, "La page web n'a pas pu être téléchargée. Vérifiez que l'adresse est publique et accessible."

    content_type = response.headers.get("Content-Type", "").lower()
    response_text = response.text
    if "html" not in content_type and "<html" not in response_text[:2000].lower():
        return None, "L'adresse ne renvoie pas une page HTML analysable."

    parser = PageTextExtractor()
    try:
        parser.feed(response_text)
        text = parser.text()
    except Exception:
        return None, "Le contenu de la page ne peut pas être converti en texte analysable."
    if len(text) < 40:
        return None, "La page ne contient pas assez de texte exploitable pour une analyse."
    return text, None


def report_text_to_pdf_lines(report_text):
    cleaned = re.sub(r"<(?:br|/p|/div|/li|/h[1-6]|/blockquote)\s*/?>", "\n", report_text or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"<li[^>]*>", "- ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = unescape(cleaned).replace("\r\n", "\n")
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    return [line.strip() for line in cleaned.split("\n") if line.strip()]


@app.route("/export_pdf", methods=["POST", "OPTIONS"])
def export_pdf():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data = request.get_json(silent=True) or {}
        report_text = str(data.get("analysis") or data.get("report") or "").strip()
        if not report_text:
            return jsonify({"error": "Aucun rapport à exporter."}), 400

        score_letter = str(data.get("scoreLetter") or "-").upper()
        if score_letter not in {"A", "B", "C", "D", "E"}:
            score_letter = "-"
        flags = [str(flag) for flag in data.get("flags") or [] if str(flag).strip()]
        lines = report_text_to_pdf_lines(report_text)

        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=42,
            rightMargin=42,
            topMargin=42,
            bottomMargin=42,
        )
        styles = getSampleStyleSheet()
        body_style = ParagraphStyle("BeaconBody", parent=styles["Normal"], fontName="Helvetica", fontSize=9.5, leading=14, textColor=colors.HexColor("#344054"), spaceAfter=5)
        bullet_style = ParagraphStyle("BeaconBullet", parent=body_style, leftIndent=12, firstLineIndent=-8)
        score_colors = {"A": "#273BE9", "B": "#09AA29", "C": "#FFB700", "D": "#FF6600", "E": "#FF0055", "-": "#667085"}
        heading_style = ParagraphStyle("BeaconHeading", parent=styles["Heading3"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.HexColor(score_colors[score_letter]), spaceBefore=14, spaceAfter=6)
        meta_style = ParagraphStyle("BeaconMeta", parent=body_style, fontName="Courier", fontSize=8.5, leading=13, textColor=colors.HexColor("#344054"))
        score_style = ParagraphStyle("Score", parent=body_style, alignment=1, textColor=colors.white, leading=18)
        brand_style = ParagraphStyle("Brand", parent=body_style, fontName="Helvetica-Bold", fontSize=12, leading=15, alignment=1, textColor=colors.HexColor("#1E293B"))
        metadata_right_style = ParagraphStyle("MetadataRight", parent=meta_style, alignment=2, fontSize=8, leading=12)
        indicator_style = ParagraphStyle("Indicator", parent=body_style, fontName="Helvetica-Bold", fontSize=7.5, leading=10, alignment=1, textColor=colors.HexColor("#344054"))
        evidence_style = ParagraphStyle("Evidence", parent=body_style, fontName="Helvetica-Oblique", fontSize=9, leading=13, leftIndent=10, rightIndent=10, textColor=colors.HexColor("#475467"))
        conclusion_style = ParagraphStyle("Conclusion", parent=body_style, fontName="Helvetica-Bold", fontSize=10, leading=15, textColor=colors.HexColor("#1E293B"))

        timestamp = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
        dossier_ref = f"BEACON-{datetime.now(timezone.utc).strftime('%Y')}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
        score_badge = Table([[
            Paragraph(f"<b>ETHIC-SCORE</b> <font size=17>{escape(score_letter)}</font>", score_style)
        ]], colWidths=[112], rowHeights=[34])
        score_badge.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(score_colors[score_letter])),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        metadata = Paragraph(f"<b>RÉF :</b> {dossier_ref}<br/><b>DATE :</b> {timestamp}", metadata_right_style)
        score_metadata = Table([[
            score_badge,
            Paragraph("POLETHIC BEACON", brand_style),
            metadata,
        ]], colWidths=[166, 176, 186], rowHeights=[43])
        score_metadata.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("LEFTPADDING", (1, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))

        story = [score_metadata, Spacer(1, 12)]
        if flags:
            indicator_cells = [Paragraph(escape(flag.replace("_", " ")), indicator_style) for flag in flags[:6]]
            while len(indicator_cells) % 3:
                indicator_cells.append(Paragraph("", indicator_style))
            indicator_rows = [indicator_cells[index:index + 3] for index in range(0, len(indicator_cells), 3)]
            indicators_grid = Table(indicator_rows, colWidths=[145, 145, 145])
            indicators_grid.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F4F7")),
                ("BOX", (0, 0), (-1, -1), 0, colors.white),
                ("INNERGRID", (0, 0), (-1, -1), 4, colors.white),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            indicators_block = Table([[
                Paragraph("<b>INDICATEURS<br/>D'ALERTE</b>", meta_style), indicators_grid
            ]], colWidths=[92, 436])
            indicators_block.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0, colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.extend([indicators_block, Spacer(1, 14)])

        identification_lines = []
        while lines and re.match(r"^[1-3]\.\s", lines[0]):
            identification_lines.append(lines.pop(0))
        if identification_lines:
            identification = Table([[Paragraph("<br/>".join(escape(line) for line in identification_lines), body_style)]], colWidths=[528])
            identification.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))
            story.extend([identification, Spacer(1, 7)])

        for line in lines:
            heading = re.sub(r"^#{1,6}\s*", "", line).strip()
            if line.startswith("#") or re.match(r"^(Phase|MEMES|DÉFI DU BIAIS)", heading, re.IGNORECASE):
                story.append(Paragraph(escape(heading), heading_style))
            elif re.match(r"^(Conclusion|Conclusion générale)\s*:", line, re.IGNORECASE):
                conclusion = Table([[Paragraph(escape(line), conclusion_style)]], colWidths=[528])
                conclusion.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor({"A": "#EFF6FF", "B": "#ECFDF3", "C": "#FFFAEB", "D": "#FFF7ED", "E": "#FFF1F3", "-": "#F8FAFC"}[score_letter])),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                    ("TOPPADDING", (0, 0), (-1, -1), 11),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
                ]))
                story.extend([Spacer(1, 7), conclusion])
            elif line.startswith("- ") or line.startswith("• "):
                item = line[2:].strip()
                if item.startswith(("«", "\"")):
                    evidence = Table([[Paragraph(escape(item), evidence_style)]], colWidths=[500])
                    evidence.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                        ("TOPPADDING", (0, 0), (-1, -1), 7),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ]))
                    story.extend([evidence, Spacer(1, 4)])
                else:
                    story.append(Paragraph(f"• {escape(item)}", bullet_style))
            else:
                story.append(Paragraph(escape(line), body_style))

        def draw_footer(canvas, pdf_document):
            canvas.saveState()
            canvas.setStrokeColor(colors.HexColor("#E2E8F0"))
            canvas.line(pdf_document.leftMargin, 28, letter[0] - pdf_document.rightMargin, 28)
            canvas.setFont("Helvetica", 7.5)
            canvas.setFillColor(colors.HexColor("#64748B"))
            canvas.drawString(pdf_document.leftMargin, 17, "POLETHIC BEACON - Forensic Cognitive Engine - Nous dénudons les narratives humaines et traduisons les mécanismes de persuasion")
            canvas.drawRightString(letter[0] - pdf_document.rightMargin, 17, f"PAGE {pdf_document.page}")
            canvas.restoreState()

        document.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
        buffer.seek(0)
        return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name="RAPPORT_BEACON.pdf")
    except Exception as exc:
        return jsonify({"error": f"Échec de l'export PDF : {exc}"}), 500


@app.route("/refute/analyze", methods=["POST", "OPTIONS"])
@app.route("/analyze", methods=["POST", "OPTIONS"])
def analyze():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data = request.get_json(silent=True) or {}
        if not data and request.form:
            data = request.form.to_dict(flat=True)

        content_to_analyze = (data.get("text") or data.get("content") or "").strip()
        lang = str(data.get("lang", "fr")).lower()
        source_url = None

        if re.fullmatch(r"https?://\S+", content_to_analyze, flags=re.IGNORECASE):
            source_url = content_to_analyze
            content_to_analyze, extraction_error = extract_webpage_text(source_url)
            if extraction_error:
                return jsonify({"error": extraction_error}), 400

        uploaded_file = request.files.get("file")
        if uploaded_file and uploaded_file.filename:
            uploaded_text, extraction_error = extract_uploaded_pdf_text(uploaded_file)
            if extraction_error:
                return jsonify({"error": extraction_error}), 400
            content_to_analyze = "\n\n".join(part for part in [content_to_analyze, uploaded_text] if part).strip()

        if not content_to_analyze:
            return jsonify({"error": "Aucun contenu fourni"}), 400
        if is_beacon_report(content_to_analyze):
            return jsonify({
                "error": "Le contenu collé est déjà un rapport POLETHIC BEACON. Collez le texte source original pour lancer une nouvelle analyse.",
                "code": "BEACON_REPORT_REANALYSIS",
            }), 422

        local_result = build_local_analysis_report(content_to_analyze, lang)
        final_score = local_result["score"]
        final_flags = local_result["flags"]
        styled_analysis = local_result["analysis"]

        gemini_ok = False
        use_gemini_analysis = os.environ.get("BEACON_ENABLE_GEMINI_ANALYSIS", "").lower() == "true"
        try:
            if use_gemini_analysis and client is not None:
                resolved_model = get_available_model()
                if resolved_model:
                    gemini_ok = True
                    user_prompt = f"Effectuez l'analyse complète en 7 couches du texte suivant :\n\n{content_to_analyze[:10000]}"
                    response = client.models.generate_content(
                        model=resolved_model,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=build_gemini_system_instruction(lang),
                            temperature=0.1,
                            max_output_tokens=8192,
                        )
                    )
                    analysis_text = response.text or ""

                    score_match = re.search(r"<score>\s*(\d+)\s*</score>", analysis_text, re.IGNORECASE)
                    if score_match:
                        final_score = int(score_match.group(1))

                    flags_match = re.search(r"<flags>\s*(.*?)\s*</flags>", analysis_text, re.IGNORECASE | re.DOTALL)
                    if flags_match:
                        parsed_flags = normalize_flag_tokens(flags_match.group(1))
                        if parsed_flags:
                            final_flags = parsed_flags

                    clean_analysis = re.sub(r"<score>.*?</score>", "", analysis_text, flags=re.DOTALL | re.IGNORECASE)
                    clean_analysis = re.sub(r"<flags>.*?</flags>", "", clean_analysis, flags=re.DOTALL | re.IGNORECASE).strip()
                    clean_analysis = force_structured_analysis(clean_analysis, final_score, final_flags)

                    styled_analysis = f"<div style='line-height: 1.8; font-size: 15px; letter-spacing: 0.2px;'>" + clean_analysis + "</div>"
                    for i in range(7):
                        styled_analysis = re.sub(
                            rf"(<h3[^>]*>)\s*(Phase\s*{i}[^<]*)",
                            rf"\1<span style='color: {get_ethic_band(final_score)[1]};'>\2</span>",
                            styled_analysis,
                            flags=re.IGNORECASE,
                        )

                    styled_analysis = styled_analysis.replace("<h3>", "<h3 style='margin-top: 28px; margin-bottom: 10px; font-weight: 600;'>")
                    styled_analysis = styled_analysis.replace("<ul>", "<ul style='margin-bottom: 20px; padding-left: 20px;'>")
                    styled_analysis = styled_analysis.replace("<li>", "<li style='margin-bottom: 8px; opacity: 0.95;'>")
        except Exception:
            gemini_ok = False

        ethic_letter, ethic_color = get_ethic_band(final_score)
        norm_text = normalize_for_match(content_to_analyze)
        indicators = build_indicator_summary(norm_text)
        summary = build_summary_text(final_score, final_flags, lang)
        translation = build_translation_summary(summary, lang)
        refutation_questions = build_refutation_questions(final_flags, lang)

        return jsonify({
            "status": "success",
            "analysis": styled_analysis,
            "score": final_score,
            "band": ethic_letter,
            "color": ethic_color,
            "flags": final_flags,
            "ethic_class": ethic_letter,
            "ethic_color": ethic_color,
            "language": lang,
            "source_type": "url" if source_url else data.get("source_type", "text"),
            "summary": summary,
            "translation": translation,
            "indicators": indicators,
            "refutation_questions": refutation_questions,
        }), 200
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": str(exc)}), 500


@app.route("/refute", methods=["POST", "OPTIONS"])
def refute_endpoint():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data = request.get_json(silent=True) or {}
        if not data and request.form:
            data = request.form.to_dict(flat=True)

        content = (data.get("text") or data.get("content") or "").strip()
        lang = str(data.get("lang", "fr")).lower()
        flags = data.get("flags") or []

        if not content and not flags:
            return jsonify({"error": "No content or flags provided"}), 400

        if not content:
            content = " ".join(flags)

        if not flags:
            local_result = build_local_analysis_report(content, lang)
            flags = local_result["flags"]

        questions = build_refutation_questions(flags, lang)
        return jsonify({
            "status": "success",
            "language": lang,
            "questions": questions,
        }), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=debug)
