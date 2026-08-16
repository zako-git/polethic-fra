import os
import re
import json
import hashlib
import unicodedata
from datetime import datetime, timezone
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
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

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

LOCAL_RISK_RULES = [
    {
        "flag": "PSEUDO-SCIENCE",
        "score": 12,
        "keywords": [
            "constellations familiales", "bert hellinger", "psychologie systemique",
            "biodescodificacion", "bioneuroemocion", "quantum hypnosis",
            "ancestral healing", "med beds", "quantique", "tecnica cuantica",
            "técnica cuántica", "método cuántico", "metodo cuantico"
        ],
    },
    {
        "flag": "BIAIS D'AUTORITE",
        "score": 10,
        "keywords": [
            "psychopedagogue", "professeure", "diplome", "certified",
            "coach", "facilitatrice", "therapeute", "expert"
        ],
    },
    {
        "flag": "CROYANCE TRANSGENERATIONNELLE",
        "score": 10,
        "keywords": [
            "systeme familial", "transgeneration", "constellations familiales",
            "memoire cellulaire", "loyautes invisibles", "karma familial"
        ],
    },
    {
        "flag": "PROMESSE IMPLICITE",
        "score": 8,
        "keywords": [
            "prendre le controle", "bonheur", "epanouissement", "paix",
            "seule voie", "tres difficile", "changer", "solo funciona",
            "only works", "without doubt", "sin dudar", "promete resultados",
            "promet resultados", "resultados si sigues", "results if you follow"
        ],
    },
    {
        "flag": "RHETORIQUE COERCITIVE",
        "score": 10,
        "keywords": [
            "nous devons", "must", "debes", "partage avant", "share before",
            "diffuse avant", "escape the matrix", "high-ticket", "liberte financiere",
            "oportunidad unica", "opportunite unique", "sin dudar", "without doubt",
            "solo funciona", "only works"
        ],
    },
    {
        "flag": "SENSATIONNALISME",
        "score": 10,
        "keywords": [
            "breaking", "urgent", "incroyable", "choquant", "revelation",
            "ultima hora", "urgente", "increible", "shocking"
        ],
    },
    {
        "flag": "CADRAGE CONSPIRATIONNISTE",
        "score": 12,
        "keywords": [
            "ils ne veulent pas que vous sachiez", "ils veulent vous cacher",
            "scientists don't want you to know", "they don't want you to know",
            "share before they delete", "before they delete this", "censurent",
            "nos quieren ocultar", "no quieren que sepas", "lo van a borrar"
        ],
    },
    {
        "flag": "PROMESSE MIRACLE",
        "score": 10,
        "keywords": [
            "one simple trick", "astuce simple", "solution miracle", "remede miracle",
            "truco simple", "solucion milagro", "one secret", "secret technique"
        ],
    },
    {
        "flag": "MANIPULATION EMOTIONNELLE",
        "score": 8,
        "keywords": [
            "doctors are furious", "furious about", "medecins furieux", "expertos furiosos",
            "you won't believe", "vous n'allez pas croire", "no vas a creer"
        ],
    },
    {
        "flag": "PROMESSE THERAPEUTIQUE",
        "score": 40,
        "keywords": [
            "guerit", "guérison", "cure cancer", "cure le cancer", "cures cancer",
            "heals cancer", "cures hashimoto", "cure hashimoto", "cura el cancer",
            "cura hashimoto", "elimina la migraña", "guarigione"
        ],
    },
    {
        "flag": "PSEUDO-MEDECINE",
        "score": 40,
        "keywords": [
            "med beds", "quantum healing", "healing frequencies", "frequences guerisseuses",
            "frecuencias curativas", "biodescodificacion", "bioneuroemocion", "miracle supplement"
        ],
    },
    {
        "flag": "INJONCTION AU DECROCHAGE MEDICAL",
        "score": 58,
        "keywords": [
            "arretez vos medicaments", "abandonnez votre traitement", "stop taking your medication",
            "stop chemotherapy", "doctors are lying", "los medicos te mienten",
            "deja tu tratamiento", "no vayas al medico"
        ],
    },
    {
        "flag": "EMPRISE PSYCHOLOGIQUE",
        "score": 58,
        "keywords": [
            "coupez les ponts", "quittez votre famille", "leave your family", "cut off your family",
            "rompe con tu familia", "solo nosotros", "only we can save you"
        ],
    },
]

# Steven Hassan's BITE model: behavioral, informational, thought, and emotional
# control. Each axis is detected independently in French, Spanish, and English.
BITE_AXIS_RULES = {
    "CONTROLE COMPORTEMENTAL": [
        "obey without question", "must attend", "control your schedule", "sleep deprivation",
        "obéis sans discuter", "devez assister", "controle votre emploi du temps", "prive de sommeil",
        "obedece sin cuestionar", "debes asistir", "controla tu horario", "privacion de sueño"
    ],
    "CONTROLE INFORMATIONNEL": [
        "do not read outside sources", "don't listen to outsiders", "all media are lies",
        "ne lisez pas de sources externes", "n'ecoutez pas les critiques", "les medias mentent tous",
        "no leas fuentes externas", "no escuches a los criticos", "todos los medios mienten"
    ],
    "CONTROLE DE LA PENSEE": [
        "doubt is the enemy", "do not question the method", "only our truth",
        "le doute est l'ennemi", "ne remettez pas la methode en question", "seule notre verite",
        "la duda es el enemigo", "no cuestiones el metodo", "solo nuestra verdad"
    ],
    "CONTROLE EMOTIONNEL": [
        "if you leave you will fail", "you betray us", "fear of losing the group",
        "si vous partez vous echouerez", "vous nous trahissez", "peur de perdre le groupe",
        "si te vas fracasaras", "nos traicionas", "miedo a perder el grupo"
    ],
}

# Matrice principale d'integrite: A est le niveau le plus fiable, E le plus fragile.
# Les signaux locaux soustraient des points a la base de 82; les indices academiques
# verifiables peuvent etre rehausses par les branches positives ci-dessous.
SCORE_MATRIX = {
    "A": {"range": (88, 100), "fr": "Integrite factuelle elevee", "es": "Integridad factual alta", "en": "High factual integrity"},
    "B": {"range": (75, 87), "fr": "Communication globalement solide, vigilance legere", "es": "Comunicacion globalmente solida, vigilancia leve", "en": "Generally sound communication, light vigilance"},
    "C": {"range": (56, 74), "fr": "Ambiguite ou cadrage persuasif notable", "es": "Ambiguedad o encuadre persuasivo notable", "en": "Notable ambiguity or persuasive framing"},
    "D": {"range": (35, 55), "fr": "Manipulation rhetorique ou risque d'influence eleve", "es": "Manipulacion retorica o riesgo de influencia alto", "en": "Rhetorical manipulation or high influence risk"},
    "E": {"range": (0, 34), "fr": "Integrite argumentative tres faible", "es": "Integridad argumental muy baja", "en": "Very low argumentative integrity"},
}

# Niveau minimal impose par les signaux: la lettre finale est toujours celle du
# flag le plus grave detecte, quel que soit le score intermediaire du pipeline.
FLAG_SEVERITY = {
    "AMBIGUITE METHODOLOGIQUE": "B",
    "GLISSEMENT D'EXPERTISE": "B",
    "CADRAGE PERSUASIF LEGER": "B",
    "PSEUDO-SCIENCE": "C",
    "BIAIS D'AUTORITE": "C",
    "CROYANCE TRANSGENERATIONNELLE": "C",
    "PROMESSE IMPLICITE": "C",
    "CAPTATION DE VULNERABILITE": "C",
    "RHETORIQUE COERCITIVE": "D",
    "SENSATIONNALISME": "D",
    "CADRAGE CONSPIRATIONNISTE": "D",
    "PROMESSE MIRACLE": "D",
    "MANIPULATION EMOTIONNELLE": "D",
    "PROMESSE THERAPEUTIQUE": "D",
    "BIAIS D'ANECDOTE": "D",
    "PSEUDO-MEDECINE": "D",
    "VALIDATION CROISEE": "D",
    "INJONCTION AU DECROCHAGE MEDICAL": "E",
    "EMPRISE PSYCHOLOGIQUE": "E",
    "THEORIE DU COMPLOT MEDICAL": "E",
    "CULT-LIKE RHETORIC": "E",
    "CONTROLE COMPORTEMENTAL": "D",
    "CONTROLE INFORMATIONNEL": "D",
    "CONTROLE DE LA PENSEE": "D",
    "CONTROLE EMOTIONNEL": "D",
    "BLANCHIMENT SCIENTIFIQUE": "C",
    "APPLICATION A UNE PATHOLOGIE PHYSIQUE": "D",
}

SEVERITY_SCORE = {"A": 92, "B": 78, "C": 60, "D": 40, "E": 20}

ACADEMIC_INSTITUTION_KEYWORDS = [
    "university", "universite", "medical school", "hospital", "harvard",
    "northeastern", "massachusetts general hospital", "cnrs", "inserm",
    "laboratory", "centre for", "center for", "department", "faculty",
    "college", "school of", "institute", "institut", "lab", "clinic"
]

ACADEMIC_RESEARCH_KEYWORDS = [
    "research", "recherche", "scientist", "science", "psychology",
    "psychologie", "neuroscience", "neurosciences", "peer-review",
    "publication", "publications", "bibliometric", "citation", "cited",
    "peer reviewed", "journal", "journals", "study", "studies",
    "published", "laboratoire", "clinical", "academique", "academic"
]

ACADEMIC_TITLE_KEYWORDS = [
    "phd", "doctorate", "professor", "professeure", "professeur",
    "distinguished professor", "chief scientific officer", "associate professor",
    "assistant professor", "dr ", "doctor", "md", "researcher", "chercheur"
]


def strip_accents(text):
    if not text:
        return ""
    normalized = unicodedata.normalize("NFD", text)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def normalize_for_match(text):
    clean = strip_accents((text or "").lower())
    clean = re.sub(r"[-_/]+", " ", clean)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def keyword_matches(norm_text, keyword):
    normalized_keyword = normalize_for_match(keyword)
    if not normalized_keyword:
        return False
    if re.search(r"[\s\-]", normalized_keyword):
        return normalized_keyword in norm_text
    return re.search(rf"\b{re.escape(normalized_keyword)}\b", norm_text) is not None


def detect_bite_axes(norm_text):
    hits = []
    for axis, keywords in BITE_AXIS_RULES.items():
        matched_keywords = [keyword for keyword in keywords if keyword_matches(norm_text, keyword)]
        if matched_keywords:
            hits.append({"flag": axis, "score": 12, "keywords": matched_keywords})

    if len(hits) >= 3:
        hits.append({
            "flag": "EMPRISE PSYCHOLOGIQUE",
            "score": 58,
            "keywords": ["trois axes BITE ou plus detectes"],
        })

    return hits


def detect_scientific_washing(norm_text):
    prestige_terms = [
        "neurosciences", "neuroscience", "neurobiologie", "neurobiology",
        "physique quantique", "quantum physics", "fisica cuantica", "neurociencias",
        "systeme nerveux autonome", "sistema nervioso autonomo", "fascias", "fascia",
        "epigenetique", "epigenetica", "reprogrammation cellulaire", "reprogramacion celular",
        "scientifiquement prouve", "cientificamente probado", "protocoles neuro-somatiques",
        "protocolos neuro-somaticos"
    ]
    alternative_practices = [
        "remedes naturels", "remede naturel", "natural remedies", "remedios naturales",
        "lectures energetiques", "lecture energetique", "energy readings", "lecturas energeticas",
        "healing frequencies", "frequences guerisseuses", "frecuencias curativas",
        "quantum healing", "bioneuroemocion", "biodescodificacion"
    ]
    official_credentials = [
        "medical doctor", "medecin", "docteur en medecine", "doctor of medicine",
        "neurologue", "neurologist", "neuroscientifique", "neuroscientist",
        "phd in neuroscience", "doctorat en neurosciences", "doctorado en neurociencias",
        "chercheur en neurosciences", "investigador en neurociencias", "neuroscience researcher"
    ]
    physical_conditions = [
        "cancer", "hashimoto", "migraine", "maladie chronique", "chronic illness",
        "autoimmune", "auto-immune", "autoinmune", "thyroide", "thyroid"
    ]

    prestige_hits = [term for term in prestige_terms if keyword_matches(norm_text, term)]
    practice_hits = [term for term in alternative_practices if keyword_matches(norm_text, term)]
    credential_hits = [term for term in official_credentials if keyword_matches(norm_text, term)]
    condition_hits = [term for term in physical_conditions if keyword_matches(norm_text, term)]

    if not prestige_hits or not practice_hits or credential_hits:
        return []

    hits = [
        {
            "flag": "BLANCHIMENT SCIENTIFIQUE",
            "score": 18,
            "keywords": prestige_hits + practice_hits,
        },
        {
            "flag": "BIAIS D'AUTORITE",
            "score": 10,
            "keywords": prestige_hits,
        },
    ]

    if condition_hits:
        hits.append({
            "flag": "APPLICATION A UNE PATHOLOGIE PHYSIQUE",
            "score": 40,
            "keywords": condition_hits,
        })

    return hits


def detect_beacon_lexical_clusters(norm_text):
    health_terms = [
        "maladie d'hashimoto", "enfermedad de hashimoto", "hashimoto", "migraines", "migranas",
        "douleurs chroniques", "dolores cronicos", "inflammation", "urgences", "curacion", "guerison",
        "reequilibrer le corps", "reestablecer el equilibrio", "retablir l'equilibre",
        "subir la douleur", "remedes naturels", "remedios naturales", "remedia naturales",
        "micronutrition", "brote autoinmune", "autoimmune flare", "hs"
    ]
    systemic_terms = [
        "memoire cellulaire", "memoria celular", "lignee familiale", "linaje familiar",
        "origine transgenerationnelle", "origen transgeneracional", "constellations", "constelaciones",
        "loyautes invisibles", "lealtades invisibles", "blocages inconscients", "bloqueos inconscientes",
        "racines du probleme", "raiz del problema", "karma familial", "karma familiar",
        "noeuds emotionnels", "nudos emocionales", "energies invisibles", "energias invisibles"
    ]
    vulnerability_terms = [
        "tu as tout essaye", "rien ne marche", "tu es fatigue", "tu es hs", "solution miracle",
        "acces a la racine", "sans effort", "en douceur", "methode exclusive",
        "has intentado todo", "nada funciona", "estas agotado", "estas reventado",
        "solucion milagrosa", "acceso a la raiz", "sin esfuerzo", "metodo exclusivo",
        "you have tried everything", "nothing works", "miracle solution", "without effort", "exclusive method"
    ]
    private_channel_terms = [
        "contact en mp", "contacte moi en mp", "contactez moi en mp", "message prive", "par message prive", "disponibilite chaque jour",
        "por mensaje privado", "mensaje privado", "disponibilidad diaria", "dm me", "private message",
        "available every day"
    ]

    health_hits = [term for term in health_terms if keyword_matches(norm_text, term)]
    systemic_hits = [term for term in systemic_terms if keyword_matches(norm_text, term)]
    vulnerability_hits = [term for term in vulnerability_terms if keyword_matches(norm_text, term)]
    private_channel_hits = [term for term in private_channel_terms if keyword_matches(norm_text, term)]
    hits = []

    if health_hits:
        hits.append({
            "flag": "PROMESSE THERAPEUTIQUE",
            "score": 40,
            "keywords": health_hits,
        })
    if systemic_hits:
        hits.append({
            "flag": "CROYANCE TRANSGENERATIONNELLE",
            "score": 10,
            "keywords": systemic_hits,
        })
    if vulnerability_hits and private_channel_hits:
        keywords = vulnerability_hits + private_channel_hits
        hits.extend([
            {"flag": "PROMESSE IMPLICITE", "score": 8, "keywords": keywords},
            {"flag": "CAPTATION DE VULNERABILITE", "score": 12, "keywords": keywords},
        ])

    return hits


def detect_academic_context(norm_text):
    institution_hits = [kw for kw in ACADEMIC_INSTITUTION_KEYWORDS if kw in norm_text]
    research_hits = [kw for kw in ACADEMIC_RESEARCH_KEYWORDS if kw in norm_text]
    title_hits = [kw for kw in ACADEMIC_TITLE_KEYWORDS if kw in norm_text]
    signal_score = (len(institution_hits) * 2) + len(research_hits) + len(title_hits)

    verified = (
        (len(institution_hits) >= 1 and len(research_hits) >= 2)
        or (len(institution_hits) >= 2 and len(title_hits) >= 1)
        or ("top 0.1%" in norm_text and len(institution_hits) >= 1)
    )
    probable = not verified and (
        signal_score >= 4
        or (len(institution_hits) >= 1 and len(title_hits) >= 1)
        or (len(research_hits) >= 3 and len(title_hits) >= 1)
    )

    return {
        "verified": verified,
        "probable": probable,
        "signal_score": signal_score,
        "institution_hits": institution_hits,
        "research_hits": research_hits,
        "title_hits": title_hits,
    }


def local_match_rules(raw_text, academic_context=None):
    norm_text = normalize_for_match(raw_text)
    hits = []
    for rule in LOCAL_RISK_RULES:
        matched_keywords = [kw for kw in rule["keywords"] if keyword_matches(norm_text, kw)]
        if rule["flag"] == "BIAIS D'AUTORITE" and academic_context and academic_context["verified"]:
            matched_keywords = [kw for kw in matched_keywords if kw not in {"professeure", "expert"}]
        if matched_keywords:
            hits.append({
                "flag": rule["flag"],
                "score": rule["score"],
                "keywords": matched_keywords,
            })
    hits.extend(detect_bite_axes(norm_text))
    hits.extend(detect_scientific_washing(norm_text))
    hits.extend(detect_beacon_lexical_clusters(norm_text))

    merged_hits = {}
    for hit in hits:
        existing = merged_hits.get(hit["flag"])
        if existing is None:
            merged_hits[hit["flag"]] = {
                "flag": hit["flag"],
                "score": hit["score"],
                "keywords": list(hit["keywords"]),
            }
            continue

        existing["score"] = max(existing["score"], hit["score"])
        existing["keywords"] = list(dict.fromkeys(existing["keywords"] + hit["keywords"]))

    return list(merged_hits.values())


def get_risk_level_comment(score, lang="fr"):
    if lang == "es":
        if score >= 85:
            return "Conforme - Alto nivel de integridad factual"
        if score >= 70:
            return "Solido - Credibilidad globalmente respaldada"
        if score >= 50:
            return "Prudente - Algunos puntos merecen verificacion"
        if score >= 30:
            return "Reservado - Varios marcadores de fragilidad"
        return "Alerta - Integridad argumental baja"

    if lang == "en":
        if score >= 85:
            return "Compliant - High factual integrity"
        if score >= 70:
            return "Solid - Credibility broadly supported"
        if score >= 50:
            return "Cautious - Some points need verification"
        if score >= 30:
            return "Reserved - Several fragility markers detected"
        return "Alert - Low argumentative integrity"

    if score >= 85:
        return "Conforme - Haut niveau d'integrite factuelle"
    if score >= 70:
        return "Solide - Credibilite globalement etayee"
    if score >= 50:
        return "Prudent - Quelques points meritent verification"
    if score >= 30:
        return "Reserve - Plusieurs marqueurs de fragilite"
    return "Alerte - Faible integrite argumentative"


def infer_domain(norm_text):
    if detect_academic_context(norm_text)["verified"]:
        return "Neurosciences / Psychologie academique / Recherche scientifique"
    if detect_academic_context(norm_text)["probable"]:
        return "Recherche academique / Expertise scientifique"
    if any(token in norm_text for token in [
        "empresa", "empresas", "marketing", "comunicacion", "lideres", "equipos", "organizaciones", "consultor", "conflictos",
        "entreprise", "entreprises", "communication", "consultant", "conflits", "equipes", "dirigeants", "entreprise familiale",
        "business", "family business", "organizational", "organisational", "consulting", "leaders", "teams", "conflicts"
    ]):
        return "Conseil en entreprise / Marketing & communication / Mediation d'entreprise familiale"
    if any(token in norm_text for token in ["sport", "competition", "entrainer l'esprit"]):
        return "Communication d'accompagnement / Performance / Psychologie systemique"
    if any(token in norm_text for token in ["invest", "affiliate", "financiere"]):
        return "Coaching business / Narratif motivationnel"
    return "Developpement personnel"


def detect_business_promo_context(norm_text):
    expertise_hits = [
        token for token in [
            "marketing", "comunicacion", "consultor", "consultoria", "consultoría", "consulting",
            "experto", "experiencia", "organizacion", "organización", "organizacional",
            "communication", "consultant", "expert", "experience", "business"
        ]
        if token in norm_text
    ]
    mediation_hits = [
        token for token in [
            "empresas familiares", "conflictos", "dinamicas internas", "roles superpuestos", "equipos", "lideres",
            "entreprises familiales", "conflits", "dynamiques internes", "roles superposes", "equipes", "dirigeants",
            "family business", "internal dynamics", "teams", "leaders", "conflicts"
        ]
        if token in norm_text
    ]
    persuasion_hits = [
        token for token in [
            "estrategias personalizadas", "armonia", "crecimiento empresarial", "enfoque en resultados", "oportunidades de mejora",
            "strategies personnalisees", "harmonie", "croissance", "axes d'amelioration", "resultats",
            "personalized strategies", "harmony", "growth", "results-driven", "improvement opportunities"
        ]
        if token in norm_text
    ]

    active = len(expertise_hits) >= 2 and len(mediation_hits) >= 1

    return {
        "active": active,
        "expertise_hits": expertise_hits,
        "mediation_hits": mediation_hits,
        "persuasion_hits": persuasion_hits,
    }


def infer_document_type(norm_text, lang="fr"):
    if any(token in norm_text for token in [
        "marketing", "consultor", "consultoria", "consultoría", "consulting", "coaching",
        "business", "commercial", "promo", "promotional", "proposition", "strategy"
    ]):
        if lang == "es":
            return "Propuesta comercial / texto promocional"
        if lang == "en":
            return "Commercial proposal / promotional text"
        return "Proposition commerciale / texte promotionnel"

    if any(token in norm_text for token in [
        "recherche", "research", "scientific", "scientifique", "study", "studies",
        "publication", "journal", "academy", "academie", "academico", "academic"
    ]):
        if lang == "es":
            return "Ensayo informativo / texto académico"
        if lang == "en":
            return "Informative essay / academic text"
        return "Essai informatif / texte académique"

    if any(token in norm_text for token in [
        "therapeutic", "therapeutique", "therapeutic", "cure", "guerit", "guarir",
        "medication", "medicament", "medicina", "medical", "médical"
    ]):
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
    domain = infer_domain(norm_text)
    doc_type = infer_document_type(norm_text, lang)

    labels = {
        "fr": {"topic": "Sujet / Résumé", "domain": "Domaine", "doc_type": "Type de document"},
        "es": {"topic": "Tema / Resumen", "domain": "Dominio", "doc_type": "Tipo de documento"},
        "en": {"topic": "Topic / Summary", "domain": "Domain", "doc_type": "Document type"},
    }
    label_set = labels.get(lang, labels["fr"])

    if any(token in norm_text for token in ["promesse", "promise", "promesa", "miracle", "milagro", "guerit", "cure", "cura", "medical", "medic", "medication", "tecnica", "technique", "method", "methode", "método"]):
        summary = {
            "fr": "Présentation d'une proposition de transformation personnelle ou thérapeutique formulée avec un cadre de guidance et de persuasion.",
            "es": "Presentación de una propuesta de transformación personal o terapéutica formulada con un marco de orientación y persuasión.",
            "en": "Presentation of a personal or therapeutic transformation proposal framed as guidance and persuasion.",
        }[lang]
    elif any(token in norm_text for token in ["marketing", "consultor", "consultoria", "consulting", "business", "communication", "empresa", "entreprise"]):
        summary = {
            "fr": "Présentation d'une offre de conseil, de communication ou de positionnement commercial orientée vers l'amélioration de l'organisation ou de la perception.",
            "es": "Presentación de una oferta de asesoría, comunicación o posicionamiento comercial orientada a mejorar la organización o la percepción.",
            "en": "Presentation of a consulting, communication, or commercial positioning offer aimed at improving organization or perception.",
        }[lang]
    elif any(token in norm_text for token in ["recherche", "research", "scientific", "academ", "univers", "publications", "journal", "study"]):
        summary = {
            "fr": "Présentation d'un argument ou d'un cadre d'expertise formulé dans un registre scientifique, académique ou professionnel.",
            "es": "Presentación de un argumento o marco de experticia formulado en un registro científico, académico o profesional.",
            "en": "Presentation of an argument or expertise framework expressed in a scientific, academic, or professional register.",
        }[lang]
    else:
        summary = {
            "fr": "Présentation d'un texte de guidance ou de persuasion visant à orienter une lecture, un choix ou une interprétation.",
            "es": "Presentación de un texto de orientación o persuasión orientado a guiar una lectura, una elección o una interpretación.",
            "en": "Presentation of guidance or persuasion text intended to steer a reading, choice, or interpretation.",
        }[lang]

    return [
        f"• {label_set['topic']}: {summary}",
        f"• {label_set['domain']}: {domain}",
        f"• {label_set['doc_type']}: {doc_type}",
    ]


def normalize_phase0_structure(analysis_text, content, lang="fr"):
    headers = SECTION_HEADERS.get(lang, SECTION_HEADERS["fr"])
    if not analysis_text:
        return ""

    phase0_lines = build_phase0_block(content, lang)
    if headers["h2"] in analysis_text:
        before, after = analysis_text.split(headers["h2"], 1)
        existing_lines = [line for line in before.splitlines() if line.strip()]
        if existing_lines and normalize_for_match(existing_lines[0]) == normalize_for_match(headers["h1"]):
            existing_lines = existing_lines[1:]
        if existing_lines:
            existing_lines = [
                line for line in existing_lines
                if not normalize_for_match(line).startswith("ethic score")
                and not normalize_for_match(line).startswith("- flags")
                and not normalize_for_match(line).startswith("flags detect")
            ]

        new_block = [headers["h1"], *phase0_lines, ""]
        return "\n".join(new_block + [headers["h2"], after]).strip()

    return "\n".join([headers["h1"], *phase0_lines, "", analysis_text]).strip()


def build_local_analysis_report(content, lang="fr"):
    norm_text = normalize_for_match(content)
    academic_context = detect_academic_context(norm_text)
    business_context = detect_business_promo_context(norm_text)
    hits = local_match_rules(content, academic_context=academic_context)
    score = 92

    def finalize_report(analysis_text, score_value, flags_value):
        return {
            "analysis": normalize_phase0_structure(analysis_text, content, lang),
            "score": score_value,
            "flags": flags_value,
        }
    if business_context["active"]:
        score = 82
    elif academic_context["verified"]:
        score = 90
    elif academic_context["probable"]:
        score = 86

    if any(hit["flag"] == "PROMESSE IMPLICITE" for hit in hits):
        score = max(75, score - 8)
    if any(hit["flag"] == "RHETORIQUE COERCITIVE" for hit in hits):
        score = max(56, score - 10)

    for hit in hits:
        score -= hit["score"]

    score = max(5, min(95, score))
    letter = get_ethic_letter(score)
    flags = [hit["flag"] for hit in hits] or [get_default_flag_label(lang)]
    headers = SECTION_HEADERS.get(lang, SECTION_HEADERS["fr"])
    viral_clickbait_flags = {
        "SENSATIONNALISME",
        "CADRAGE CONSPIRATIONNISTE",
        "PROMESSE MIRACLE",
        "MANIPULATION EMOTIONNELLE",
        "RHETORIQUE COERCITIVE",
    }
    viral_clickbait_detected = len(viral_clickbait_flags.intersection(flags)) >= 3

    if viral_clickbait_detected and not any(h["flag"] == "PSEUDO-SCIENCE" for h in hits):
        # Several signals can describe one clickbait device; D captures the high
        # influence risk without treating the headline alone as an E-level claim.
        score = min(score, 38)
        letter = get_ethic_letter(score)

        if lang == "es":
            analysis = "\n".join([
                headers["h1"],
                f"- Ethic-Score: {letter} - {get_risk_level_comment(score, lang)}",
                "- Dominio: Titular viral / Desinformacion de salud o ciencia",
                f"- Flags detectados: {' | '.join(flags)}",
                "",
                headers["h2"],
                "- El titular no presenta una afirmacion verificable, una fuente ni un mecanismo explicativo; usa urgencia y secreto como sustitutos de evidencia.",
                "- La referencia generica a cientificos y medicos instrumentaliza la autoridad sin identificar estudio, institucion o dato comprobable.",
                "",
                headers["h3"],
                "- Se combinan sensacionalismo, marco de censura, promesa de solucion simple y llamada urgente a compartir para reducir la pausa critica del lector.",
                "- La formulacion busca activar miedo a perder informacion y reaccion emocional antes de una verificacion independiente.",
                "",
                headers["h4"],
                "- No compartir de forma impulsiva: pedir fuente primaria, estudio identificable, fecha, contexto y mecanismo verificable.",
                "- Separar una alerta viral de una evidencia cientifica: el enfado atribuido a una autoridad no demuestra la validez de la afirmacion.",
            ])
        elif lang == "en":
            analysis = "\n".join([
                headers["h1"],
                f"- Ethic-Score: {letter} - {get_risk_level_comment(score, lang)}",
                "- Domain: Viral headline / Health or science misinformation",
                f"- Flags detected: {' | '.join(flags)}",
                "",
                headers["h2"],
                "- The headline provides no verifiable claim, source, or explanatory mechanism; urgency and secrecy stand in for evidence.",
                "- Generic references to scientists and doctors instrumentalize authority without identifying a study, institution, or checkable data.",
                "",
                headers["h3"],
                "- Sensationalism, censorship framing, a simple-solution promise, and an urgent sharing command are combined to bypass critical reflection.",
                "- The wording is designed to trigger fear of missing information and an emotional response before independent verification.",
                "",
                headers["h4"],
                "- Do not share impulsively: request a primary source, identifiable study, date, context, and verifiable mechanism.",
                "- Separate a viral alert from scientific evidence: attributed anger from an authority does not validate the claim.",
            ])
        else:
            analysis = "\n".join([
                headers["h1"],
                f"- Ethic-Score: {letter} - {get_risk_level_comment(score, lang)}",
                "- Domaine: Titulaire viral / Desinformation sante ou science",
                f"- Flags detectes: {' | '.join(flags)}",
                "",
                headers["h2"],
                "- Le titre ne fournit ni fait verifiable, ni source, ni mecanisme explicatif: l'urgence et le secret remplacent la preuve.",
                "- La reference generique aux scientifiques et aux medecins instrumentalise l'autorite sans citer d'etude, d'institution ou de donnee controlable.",
                "",
                headers["h3"],
                "- Sensationnalisme, cadrage de censure, promesse de solution simple et injonction de partage sont combines pour court-circuiter la pause critique.",
                "- La formulation cherche a activer la peur de manquer une information et une reaction emotionnelle avant toute verification independante.",
                "",
                headers["h4"],
                "- Ne pas partager impulsivement: demander une source primaire, une etude identifiable, une date, un contexte et un mecanisme verifiable.",
                "- Distinguer une alerte virale d'une preuve scientifique: la colere attribuee a une autorite ne valide pas l'affirmation.",
            ])

        return finalize_report(analysis, score, flags)

    bite_axis_flags = [flag for flag in flags if flag in BITE_AXIS_RULES]
    if bite_axis_flags:
        evidence_lines = []
        for hit in hits:
            if hit["flag"] in BITE_AXIS_RULES:
                evidence_lines.append(f"- {hit['flag']}: {', '.join(hit['keywords'][:2])}")

        if lang == "es":
            analysis = "\n".join([
                headers["h1"],
                f"- Ethic-Score: {letter} - {get_risk_level_comment(score, lang)}",
                "- Dominio: Dinamica de influencia coercitiva / Evaluacion BITE",
                f"- Flags detectados: {' | '.join(flags)}",
                "",
                headers["h2"],
                "- Evaluacion BITE: el texto muestra senales de control conductual, informacional, del pensamiento o emocional segun el modelo de Steven Hassan.",
                *evidence_lines,
                "",
                headers["h3"],
                "- La combinacion de ejes busca reducir la autonomia: regula conductas, limita fuentes externas, desalienta la duda o utiliza miedo, culpa y pertenencia como palancas.",
                "- La presencia de tres o mas ejes activa una alerta de posible emprise psicologica.",
                "",
                headers["h4"],
                "- Recuperar fuentes externas, mantener contacto con apoyos independientes y no aceptar instrucciones que limiten tratamiento, informacion o relaciones personales.",
            ])
        elif lang == "en":
            analysis = "\n".join([
                headers["h1"],
                f"- Ethic-Score: {letter} - {get_risk_level_comment(score, lang)}",
                "- Domain: Coercive influence dynamics / BITE assessment",
                f"- Flags detected: {' | '.join(flags)}",
                "",
                headers["h2"],
                "- BITE assessment: the text shows behavioral, informational, thought, or emotional control signals in Steven Hassan's model.",
                *evidence_lines,
                "",
                headers["h3"],
                "- Combined axes reduce autonomy by regulating behavior, limiting outside sources, discouraging doubt, or leveraging fear, guilt, and belonging.",
                "- Three or more axes trigger a psychological-control alert.",
                "",
                headers["h4"],
                "- Restore access to external sources, maintain independent support, and do not accept instructions that restrict treatment, information, or personal relationships.",
            ])
        else:
            analysis = "\n".join([
                headers["h1"],
                f"- Ethic-Score: {letter} - {get_risk_level_comment(score, lang)}",
                "- Domaine: Dynamique d'influence coercitive / Evaluation BITE",
                f"- Flags detectes: {' | '.join(flags)}",
                "",
                headers["h2"],
                "- Evaluation BITE: le texte montre des signaux de controle comportemental, informationnel, de la pensee ou emotionnel selon le modele de Steven Hassan.",
                *evidence_lines,
                "",
                headers["h3"],
                "- La combinaison des axes reduit l'autonomie: regulation des conduites, limitation des sources externes, decouragement du doute ou mobilisation de peur, culpabilite et appartenance.",
                "- La presence de trois axes ou plus declenche une alerte d'emprise psychologique.",
                "",
                headers["h4"],
                "- Retablir l'acces a des sources externes, maintenir des soutiens independants et refuser toute instruction limitant soins, information ou liens personnels.",
            ])

        return finalize_report(analysis, score, flags)

    scientific_washing_detected = "BLANCHIMENT SCIENTIFIQUE" in flags
    if scientific_washing_detected:
        evidence_lines = []
        for hit in hits:
            if hit["flag"] in {
                "BLANCHIMENT SCIENTIFIQUE",
                "BIAIS D'AUTORITE",
                "APPLICATION A UNE PATHOLOGIE PHYSIQUE",
            }:
                evidence_lines.append(f"- {hit['flag']}: indices detectes ({', '.join(hit['keywords'][:3])})")

        physical_application = "APPLICATION A UNE PATHOLOGIE PHYSIQUE" in flags
        if lang == "es":
            domain = "Afirmacion de bienestar" if not physical_application else "Afirmacion terapeutica sobre una patologia fisica"
            premise = "- El extracto asocia vocabulario de prestigio cientifico con practicas alternativas sin aportar aqui una credencial clinica o neurocientifica verificable ni evidencia primaria de eficacia."
            deconstruction = "- La referencia a neurociencia, neurobiologia o fisica cuantica puede crear una apariencia de validacion; por si sola no demuestra relevancia clinica, mecanismo ni eficacia de la practica propuesta."
            strategy = [
                "- Solicitar identidad profesional, institucion, cualificacion exacta y estudios primarios reproducibles sobre la practica concreta.",
                "- Separar una explicacion metaforica o comercial de una afirmacion cientifica o clinica comprobable.",
            ]
            if physical_application:
                strategy.append("- No sustituir seguimiento medico ni tratamiento indicado para una patologia fisica; contrastar cualquier afirmacion terapeutica con un profesional sanitario cualificado.")
            analysis = "\n".join([
                headers["h1"],
                f"- Ethic-Score: {letter} - {get_risk_level_comment(score, lang)}",
                f"- Dominio: {domain}",
                f"- Flags detectados: {' | '.join(flags)}",
                "",
                headers["h2"],
                premise,
                *evidence_lines,
                "",
                headers["h3"],
                deconstruction,
                "",
                headers["h4"],
                *strategy,
            ])
        elif lang == "en":
            domain = "Wellness claim" if not physical_application else "Therapeutic claim about a physical condition"
            premise = "- The excerpt pairs science-prestige language with alternative practices without supplying a verifiable clinical or neuroscience credential or primary efficacy evidence."
            deconstruction = "- Referring to neuroscience, neurobiology, or quantum physics can create an appearance of validation; it does not by itself establish clinical relevance, a mechanism, or effectiveness for the proposed practice."
            strategy = [
                "- Request the practitioner's identity, institution, exact qualification, and reproducible primary studies for the specific practice.",
                "- Separate a metaphorical or commercial explanation from a testable scientific or clinical claim.",
            ]
            if physical_application:
                strategy.append("- Do not replace medical monitoring or prescribed treatment for a physical condition; check therapeutic claims with a qualified health professional.")
            analysis = "\n".join([
                headers["h1"],
                f"- Ethic-Score: {letter} - {get_risk_level_comment(score, lang)}",
                f"- Domain: {domain}",
                f"- Flags detected: {' | '.join(flags)}",
                "",
                headers["h2"],
                premise,
                *evidence_lines,
                "",
                headers["h3"],
                deconstruction,
                "",
                headers["h4"],
                *strategy,
            ])
        else:
            domain = "Affirmation de bien-etre" if not physical_application else "Affirmation therapeutique sur une pathologie physique"
            premise = "- L'extrait associe un vocabulaire de prestige scientifique a des pratiques alternatives sans fournir ici de credential clinique ou neuroscientifique verifiable, ni de preuve primaire d'efficacite."
            deconstruction = "- La reference aux neurosciences, a la neurobiologie ou a la physique quantique peut donner une apparence de validation; elle ne demontre pas a elle seule la pertinence clinique, un mecanisme ni l'efficacite de la pratique proposee."
            strategy = [
                "- Demander l'identite professionnelle, l'institution, la qualification exacte et des etudes primaires reproductibles sur la pratique precise.",
                "- Distinguer une explication metaphorique ou commerciale d'une affirmation scientifique ou clinique testable.",
            ]
            if physical_application:
                strategy.append("- Ne pas remplacer le suivi medical ou un traitement prescrit pour une pathologie physique; confronter toute affirmation therapeutique a un professionnel de sante qualifie.")
            analysis = "\n".join([
                headers["h1"],
                f"- Ethic-Score: {letter} - {get_risk_level_comment(score, lang)}",
                f"- Domaine: {domain}",
                f"- Flags detectes: {' | '.join(flags)}",
                "",
                headers["h2"],
                premise,
                *evidence_lines,
                "",
                headers["h3"],
                deconstruction,
                "",
                headers["h4"],
                *strategy,
            ])

        return finalize_report(analysis, score, flags)

    if lang == "fr":
        domain = infer_domain(norm_text)

        if business_context["active"] and not any(h["flag"] in {"PSEUDO-SCIENCE", "CROYANCE TRANSGENERATIONNELLE", "RHETORIQUE COERCITIVE"} for h in hits):
            score = 78
            letter = get_ethic_letter(score)
            flags = ["AMBIGUITE METHODOLOGIQUE", "CADRAGE PERSUASIF LEGER"]
            risk_comment = get_risk_level_comment(score, lang)

            analysis = "\n".join([
                headers["h1"],
                f"- Ethic-Score: {letter} - {risk_comment}",
                f"- Domaine: {domain}",
                f"- Flags detectes: {' | '.join(flags)}",
                "",
                headers["h2"],
                "- Glissement d'expertise: le texte relie une experience en marketing et communication a une capacite d'intervention sur des conflits internes et des dynamiques d'entreprise familiale, alors que ces competences ne se recouvrent pas automatiquement.",
                "- Vocabulaire seduisant mais methodologie peu precisee: causes sous-jacentes, strategies personnalisees, harmonie, croissance et resultats sont invoques sans protocole d'audit, cadre de mediation ni indicateurs objectivables.",
                "- Absence de promesses dangereuses: le discours reste dans un cadre de conseil operationnel et n'invoque ni guerison, ni causalites invisibles, ni schema transgenerationnel dur.",
                "",
                headers["h3"],
                "- Distinguer l'aisance communicationnelle d'un consultant marketing de la competence technique effective en mediation de conflits et en restructuration organisationnelle.",
                "- L'argumentaire est persuasif mais reste insuffisant pour etablir a lui seul l'efficacite de l'intervention proposee.",
                "",
                headers["h4"],
                "- Exiger une methodologie d'intervention explicite, des cas comparables et des criteres de succes mesurables avant tout engagement.",
                "- Verifier comment les conflits, la cohesion et l'amelioration operationnelle sont effectivement diagnostiques puis evalues.",
            ])

            return finalize_report(analysis, score, flags)

        if academic_context["verified"] and not hits:
            score = 94
            letter = get_ethic_letter(score)
            flags = ["CREDIBILITE ACADEMIQUE AVEREE"]
            risk_comment = get_risk_level_comment(score, lang)

            institution_list = academic_context["institution_hits"][:3]
            evidence_scope = ", ".join(institution_list) if institution_list else "institutions academiques de premier plan"

            analysis = "\n".join([
                headers["h1"],
                f"- Ethic-Score: {letter} - {risk_comment}",
                f"- Domaine: {domain}",
                f"- Flags detectes: {' | '.join(flags)}",
                "",
                headers["h2"],
                "- Validation scientifique et citations: le texte mobilise des reperes bibliometriques et de recherche compatibles avec une reconnaissance academique verifiable.",
                f"- Affiliations institutionnelles officielles: les fonctions mentionnees renvoient a {evidence_scope}, avec des cadres de recherche et d'evaluation etablis.",
                "- Distinction entre credibilite et biais d'autorite: ici, les titres et affiliations renforcent une expertise directement reliee au champ de recherche cite, sans servir a vendre une methode non testee.",
                "- Evidences locales:",
                "- Credibilite academique: presence combinee d'affiliations institutionnelles, de fonctions de recherche et de marqueurs bibliometriques.",
                "",
                headers["h3"],
                "- Note d'autodefense cognitive: meme face a un profil d'excellence, l'evaluation doit porter sur la qualite des travaux, leurs preuves empiriques et leurs limites, et non sur le seul prestige institutionnel.",
                "- Les debats de replication, de consensus et d'applicabilite clinique restent des questions legitimes dans tout cadre scientifique.",
                "",
                headers["h4"],
                "- Verifier la nature exacte des indicateurs cites: publications, citations, perimetre disciplinaire et niveau de consensus sur les theories associees.",
                "- Distinguer la valeur d'un parcours scientifique etabli de l'extension eventuelle de certaines hypotheses au-dela des donnees disponibles.",
                "- Maintenir une lecture epistemique: preuves, reproductibilite, limites et conditions d'application.",
            ])

            return finalize_report(analysis, score, flags)

        if academic_context["probable"] and not hits:
            score = 86
            letter = get_ethic_letter(score)
            flags = ["CREDIBILITE ACADEMIQUE SIGNALEE"]
            risk_comment = get_risk_level_comment(score, lang)

            evidence_tokens = (
                academic_context["institution_hits"]
                + academic_context["title_hits"]
                + academic_context["research_hits"]
            )[:4]
            evidence_scope = ", ".join(evidence_tokens) if evidence_tokens else "indices academiques convergents"

            analysis = "\n".join([
                headers["h1"],
                f"- Ethic-Score: {letter} - {risk_comment}",
                f"- Domaine: {domain}",
                f"- Flags detectes: {' | '.join(flags)}",
                "",
                headers["h2"],
                "- Le texte presente plusieurs marqueurs de credibilite academique ou scientifique compatibles avec une source institutionnelle serieuse.",
                f"- Indices releves: {evidence_scope}.",
                "- A ce stade, rien n'indique une rhétorique pseudo-scientifique ou une promesse de transformation typique des contenus a risque.",
                "- Evidences locales:",
                "- Credibilite academique: presence de titres, d'ancrages institutionnels ou de vocabulaire de recherche.",
                "",
                headers["h3"],
                "- Vigilance epistemique: un profil academique plausible augmente la confiance initiale, mais n'exonere pas d'examiner les methodes, les publications et la portee exacte des conclusions.",
                "- La verification des travaux cites, du consensus disciplinaire et du contexte d'application reste necessaire.",
                "",
                headers["h4"],
                "- Confirmer les affiliations et la production scientifique si le texte sert d'argument d'autorite.",
                "- Evaluer la qualite des preuves et distinguer biographie institutionnelle, resultats empiriques et interpretation publique.",
                "- Maintenir une lecture critique sans rabattre automatiquement le texte vers une suspicion de derive.",
            ])

            return finalize_report(analysis, score, flags)

        risk_comment = get_risk_level_comment(score, lang)

        authority_note = (
            "- Cumul de titres et effet d'autorite: le texte associe des marqueurs de legitimite "
            "academique/professionnelle avec des methodes a validation scientifique contestee."
            if any(h["flag"] == "BIAIS D'AUTORITE" for h in hits)
            else "- Aucun transfert d'autorite majeur detecte dans l'extrait."
        )

        pseudo_note = (
            "- Causalite simplifiee et croyance systemique: attribution de blocages complexes a une "
            "origine transgenerationnelle avec niveau de preuve empirique limite."
            if any(h["flag"] in {"PSEUDO-SCIENCE", "CROYANCE TRANSGENERATIONNELLE"} for h in hits)
            else "- Affirmation de sante: l'extrait mobilise une pathologie ou une intervention corporelle sans presenter ici de validation clinique verifiable."
            if any(h["flag"] in {"PROMESSE THERAPEUTIQUE", "PSEUDO-MEDECINE", "APPLICATION A UNE PATHOLOGIE PHYSIQUE"} for h in hits)
            else "- Le texte ne montre pas de noyau pseudoscientifique clairement dominant."
        )

        promise_note = (
            "- Rhétorique de solution unique: formulation implicite selon laquelle la methode proposee "
            "devient la voie privilegiee vers le bien-etre, ce qui peut augmenter la suggestibilite."
            if any(h["flag"] == "PROMESSE IMPLICITE" for h in hits)
            else "- Pas de promesse implicite forte de resultat universel detectee."
        )

        if any(h["flag"] in {"PROMESSE THERAPEUTIQUE", "PSEUDO-MEDECINE", "APPLICATION A UNE PATHOLOGIE PHYSIQUE"} for h in hits):
            phase3_lines = [
                "- Une pathologie ou une amelioration corporelle est associee a une approche dont l'efficacite clinique n'est pas etablie dans l'extrait.",
                "- L'enjeu n'est pas seulement persuasif: toute promesse ou orientation therapeutique exige des preuves adaptees et ne doit pas se substituer a un parcours de soin.",
            ]
        elif any(h["flag"] in {"PSEUDO-SCIENCE", "CROYANCE TRANSGENERATIONNELLE"} for h in hits):
            phase3_lines = [
                "- Le texte combine des elements legitimes (discipline, effort, preparation mentale) avec des postulats",
                "  systemiques difficiles a verifier cliniquement.",
            ]
            if any(h["flag"] == "PROMESSE IMPLICITE" for h in hits):
                phase3_lines.append("- Le levier persuasif principal repose sur la promesse d'un acces a la 'racine' du probleme.")
            else:
                phase3_lines.append("- Le risque principal tient a une causalite systemique simplifiee, sans promesse implicite supplementaire detectee.")
        elif any(h["flag"] in {"BIAIS D'AUTORITE", "PROMESSE IMPLICITE"} for h in hits):
            phase3_lines = [
                "- Le discours s'appuie sur des marqueurs de credibilite et de transformation personnelle qui peuvent orienter l'interpretation.",
                "- Une verification des preuves et des limites de la methode reste necessaire avant toute conclusion forte.",
            ]
        else:
            phase3_lines = [
                "- Le texte reste principalement descriptif et ne montre pas de mecanisme persuasif majeur dans cet extrait.",
                "- Aucun saut explicatif important ni promesse de transformation globale n'est detecte ici.",
            ]

        flags_text = " | ".join(flags)
        evidence_lines = []
        for hit in hits:
            sample = ", ".join(hit["keywords"][:3])
            evidence_lines.append(f"- {hit['flag']}: indices detectes ({sample})")

        if not evidence_lines:
            evidence_lines.append("- Aucune correspondance de risque locale forte sur cet extrait.")

        strategy_lines = [
            "- Poser des demandes de preuve: etudes comparatives, effets mesures, limites et risques d'induction.",
        ]
        if any(h["flag"] in {"PSEUDO-SCIENCE", "CROYANCE TRANSGENERATIONNELLE"} for h in hits):
            strategy_lines.insert(0, "- Distinguer les pratiques adossees a des etudes reproductibles des approches symboliques non valides.")
        if any(h["flag"] in {"PROMESSE THERAPEUTIQUE", "PSEUDO-MEDECINE", "APPLICATION A UNE PATHOLOGIE PHYSIQUE"} for h in hits):
            strategy_lines.insert(0, "- Ne pas remplacer un diagnostic, un suivi medical ou un traitement prescrit; verifier toute affirmation therapeutique avec un professionnel de sante qualifie.")
        if any(h["flag"] == "BIAIS D'AUTORITE" for h in hits):
            strategy_lines.append("- Eviter tout engagement base principalement sur un argument d'autorite plutot que sur des preuves controlees.")
        if any(h["flag"] == "PROMESSE IMPLICITE" for h in hits):
            strategy_lines.append("- Examiner toute promesse de transformation, de paix ou de resolution globale avant de s'engager dans la methode proposee.")
        if not any(h["flag"] in {"BIAIS D'AUTORITE", "PROMESSE IMPLICITE"} for h in hits):
            strategy_lines.append("- Adapter la vigilance aux seuls marqueurs effectivement detectes dans cet extrait.")

        analysis = "\n".join([
            headers["h1"],
            f"- Ethic-Score: {letter} - {risk_comment}",
            f"- Domaine: {domain}",
            f"- Flags detectes: {flags_text}",
            "",
            headers["h2"],
            authority_note,
            pseudo_note,
            promise_note,
            "- Evidences locales:",
            *evidence_lines,
            "",
            headers["h3"],
            *phase3_lines,
            "",
            headers["h4"],
            *strategy_lines,
        ])
    elif lang == "es":
        domain = infer_domain(norm_text)
        flags_text = " | ".join(flags)

        if business_context["active"] and not any(h["flag"] in {"PSEUDO-SCIENCE", "CROYANCE TRANSGENERATIONNELLE", "RHETORIQUE COERCITIVE"} for h in hits):
            score = 78
            flags = ["AMBIGUEDAD METODOLOGICA", "ENCUADRE PERSUASIVO LEVE"]
            flags_text = " | ".join(flags)

            phase2_line = "- Deslizamiento de experticia: el texto conecta experiencia en marketing y comunicacion con capacidad para intervenir en conflictos internos y dinamicas familiares de empresa, aunque esas competencias no son equivalentes por si mismas."
            phase3_line = "- Vocabulario persuasivo con metodologia poco explicitada: aparecen formulas atractivas como estrategias personalizadas, armonia, crecimiento y causas subyacentes, pero no se detallan protocolos de diagnostico, marcos de mediacion ni metricas de resultado."
            phase4_line = "- Prevencion operativa: no hay deriva pseudocientifica clara ni promesas de curacion, pero conviene exigir metodologia de intervencion, casos comparables y criterios objetivos de exito antes de contratar el servicio."

            analysis = "\n".join([
                headers["h1"],
                f"- Ethic-Score: {get_ethic_letter(score)} - {get_risk_level_comment(score, 'es')}",
                f"- Dominio: {domain}",
                f"- Flags detectados: {flags_text}",
                "",
                headers["h2"],
                phase2_line,
                "- Ausencia de promesas peligrosas: el texto se mantiene en un marco de consultoria empresarial y no invoca leyes invisibles, sanacion total ni causalidades metafisicas.",
                "",
                headers["h3"],
                phase3_line,
                "",
                headers["h4"],
                phase4_line,
            ])

            return finalize_report(analysis, score, flags)

        if any(h["flag"] in {"PSEUDO-SCIENCE", "CROYANCE TRANSGENERATIONNELLE"} for h in hits):
            phase2_line = "- Hechos y premisas detectadas: se mezclan marcos de acompanamiento con postulados dificiles de validar empiricamente."
            phase3_line = "- Sesgos detectados: causalidad simplificada, transferencia de legitimidad y posible promesa de acceso a una causa raiz."
            phase4_line = "- Recomendacion: pedir evidencia comparativa, separar metafora de validacion empirica y revisar limites del metodo propuesto."
        elif any(h["flag"] == "BIAIS D'AUTORITE" for h in hits):
            phase2_line = "- Hechos y premisas detectadas: el texto presenta competencias profesionales y una propuesta de acompanamiento, pero conviene distinguir experiencia comercial de validacion metodologica."
            phase3_line = "- Sesgos detectados: posible sesgo de autoridad o de credibilizacion si los titulos sustituyen pruebas de eficacia."
            phase4_line = "- Recomendacion: solicitar casos comparables, criterios de evaluacion y resultados medibles antes de aceptar afirmaciones amplias."
        elif "consultoria organizacional" in normalize_for_match(domain):
            phase2_line = "- Hechos y premisas detectadas: el texto describe un servicio de consultoria para empresas familiares centrado en conflictos, coordinacion interna y mejora operativa."
            phase3_line = "- Lectura cognitiva: no aparecen marcadores fuertes de pseudociencia, pero el texto sigue siendo una autopresentacion profesional y no prueba por si solo la eficacia de la intervencion."
            phase4_line = "- Recomendacion: comprobar metodologia, indicadores de resultado, alcance real del acompanamiento y limites de aplicacion en distintos contextos empresariales."
        else:
            phase2_line = "- Hechos y premisas detectadas: el texto combina lenguaje profesional con afirmaciones generales de mejora que requieren delimitacion operativa."
            phase3_line = "- Lectura cognitiva: la credibilidad inicial parece moderada, pero el texto no aporta por si mismo evidencia externa suficiente."
            phase4_line = "- Recomendacion: pedir definiciones claras, ejemplos verificables y criterios de exito antes de extraer conclusiones fuertes."

        analysis = "\n".join([
            headers["h1"],
            f"- Ethic-Score: {get_ethic_letter(score)} - {get_risk_level_comment(score, 'es')}",
            f"- Dominio: {domain}",
            f"- Flags detectados: {flags_text}",
            "",
            headers["h2"],
            phase2_line,
            "",
            headers["h3"],
            phase3_line,
            "",
            headers["h4"],
            phase4_line,
        ])
    else:
        analysis = "\n".join([
            headers["h1"],
            "- Text Type: persuasive guidance content with mixed epistemic signals.",
            f"- Ethic-Score: {get_ethic_letter(score)} - {get_risk_level_comment(score, 'en')}",
            "",
            headers["h2"],
            "- Core Premises: legitimate psychology vocabulary blended with non-validated systemic claims.",
            "",
            headers["h3"],
            "- Detected Biases: authority transfer, implicit promise, simplified causality.",
            "",
            headers["h4"],
            "- Recommendation: request comparative evidence and separate metaphorical framing from clinical claims.",
        ])

    return finalize_report(analysis, score, flags)


def build_local_refutation(context_text, lang="fr"):
    norm_text = normalize_for_match(context_text)
    academic_context = detect_academic_context(norm_text)
    has_systemic_claim = any(k in norm_text for k in ["constellations", "bert hellinger", "systeme familial", "transgeneration"])
    has_authority_claim = any(k in norm_text for k in ["psychopedagogue", "professeure", "diplome", "certified", "expert"])
    has_promise_claim = any(k in norm_text for k in ["bonheur", "paix", "prendre le controle", "seule voie", "epanouissement"])
    has_business_consulting = any(k in norm_text for k in ["empresa", "empresas", "lideres", "equipos", "organizaciones", "marketing", "consultor", "conflictos"])

    if lang == "fr":
        if has_business_consulting and not has_systemic_claim:
            return "\n".join([
                "1. Par quels outils, protocoles d'audit ou cadres d'intervention un expert en marketing identifie-t-il concretement les causes sous-jacentes de conflits internes dans une entreprise familiale?",
                "2. Quels indicateurs objectivables permettent de mesurer l'amelioration reelle de l'harmonie, de la cohesion ou de la performance apres intervention?",
                "3. Comment distingue-t-on ici une competence de communication et de positionnement commercial d'une competence technique verifiee en mediation organisationnelle?",
            ])

        if academic_context["verified"] and not has_systemic_claim and not has_promise_claim:
            return "\n".join([
                "1. Quelles hypotheses ou parties du modele theorique defendu font encore l'objet de debats, de replications partielles ou de desaccords dans la litterature?",
                "2. Les conclusions issues de la recherche fondamentale presentee sont-elles directement transposables a la pratique clinique, ou exigent-elles des validations supplementaires?",
                "3. Quels sont les principaux angles morts methodologiques a surveiller ici: selection des echantillons, reproductibilite, validite ecologique ou extrapolation hors contexte?",
            ])

        q1 = (
            "1. Quelles etudes cliniques comparatives montrent que les blocages actuels viennent du 'systeme familial' "
            "plutot que de facteurs neurobiologiques, sociaux ou developpementaux?"
            if has_systemic_claim else
            "1. Quelles donnees reproductibles soutiennent concretement l'efficacite de la methode proposee?"
        )
        q2 = (
            "2. En quoi les titres professionnels mentionnes valident-ils scientifiquement la methode defendue, "
            "au-dela d'un argument d'autorite?"
            if has_authority_claim else
            "2. Comment distinguer expertise legitime et rhetorique de credibilisation dans ce discours?"
        )
        q3 = (
            "3. Pourquoi presenter cette approche comme voie privilegiee vers bonheur/paix alors que des approches "
            "evaluees (ex. TCC) peuvent aussi reduire les symptomes sans postulat transgenerationnel?"
            if has_promise_claim else
            "3. Quelles alternatives fondees sur des preuves sont proposees pour eviter une dependance a une methode unique?"
        )
        return "\n".join([q1, q2, q3])

    if lang == "es":
        if has_business_consulting and not has_systemic_claim:
            return (
                "1. Que metodologia concreta utiliza para diagnosticar conflictos internos y como se mide si la intervencion mejora realmente la coordinacion del equipo?\n"
                "2. Que resultados verificables, comparables o indicadores de seguimiento respaldan la eficacia de las estrategias personalizadas que propone?\n"
                "3. Como distingue entre problemas de roles, comunicacion o estructura organizativa y explicaciones demasiado generales que podrian sonar convincentes pero no ser operativas?"
            )
        return (
            "1. Que evidencia clinica comparativa respalda esta afirmacion central?\n"
            "2. Como se separa la autoridad profesional del valor cientifico real del metodo?\n"
            "3. Que alternativas basadas en evidencia existen sin depender de una narrativa unica?"
        )

    return (
        "1. What comparative clinical evidence supports the core claim?\n"
        "2. How is professional authority separated from actual scientific validity?\n"
        "3. Which evidence-based alternatives exist beyond a single explanatory framework?"
    )

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

def get_ethic_band(score):
    if score >= 88:
        return "A", colors.HexColor("#00FF88")
    elif score >= 75:
        return "B", colors.HexColor("#FFE600")
    elif score >= 56:
        return "C", colors.HexColor("#FF8C00")
    elif score >= 35:
        return "D", colors.HexColor("#FF2A2A")
    return "E", colors.HexColor("#B00020")


def get_ethic_letter(score):
    letter, _ = get_ethic_band(score)
    return letter


def get_dominant_severity(flags):
    severity_order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
    detected_levels = [FLAG_SEVERITY[flag] for flag in flags if flag in FLAG_SEVERITY]
    return max(detected_levels, key=lambda level: severity_order[level], default=None)


def get_default_flag_label(lang="fr", score=None):
    labels = {
        "fr": {
            "A": "AUCUN SIGNAL DE RISQUE COGNITIF DETECTE",
            "B": "COMMUNICATION COMMERCIALE - PERSUASION STANDARD",
            "C": "ATTENTION - PRESENCE DE CONCEPTS NON EPROUVES",
            "D": "RISQUE ELEVE - RISQUE DE DERIVE THERAPEUTIQUE",
            "E": "ALERTE ROUGE - CRITICITE MAXIMALE DETECTEE",
        },
        "es": {
            "A": "NINGUNA ALERTA COGNITIVA DETECTADA",
            "B": "COMUNICACION COMERCIAL - PERSUASION ESTANDAR",
            "C": "ATENCION - PRESENCIA DE CONCEPTOS NO PROBADOS",
            "D": "RIESGO ELEVADO - POSIBLE DERIVA TERAPEUTICA",
            "E": "ALERTA ROJA - CRITICIDAD MAXIMA DETECTADA",
        },
        "en": {
            "A": "NO COGNITIVE RISK SIGNAL DETECTED",
            "B": "COMMERCIAL COMMUNICATION - STANDARD PERSUASION",
            "C": "CAUTION - UNPROVEN CONCEPTS PRESENT",
            "D": "HIGH RISK - POTENTIAL THERAPEUTIC DRIFT",
            "E": "RED ALERT - MAXIMUM CRITICALITY DETECTED",
        },
    }
    letter = get_ethic_letter(score) if score is not None else "A"
    return labels.get(lang, labels["fr"])[letter]


def format_flags_line(flags, lang="fr"):
    labels = {
        "fr": "- Flags detectes: ",
        "es": "- Flags detectados: ",
        "en": "- Flags detected: ",
    }
    prefix = labels.get(lang, labels["fr"])
    return f"{prefix}{' | '.join(flags)}"


def get_risk_intensity_comment(risk_score, lang="fr"):
    if lang == "es":
        if risk_score >= 80:
            return "Riesgo extremo de venta de humo"
        if risk_score >= 60:
            return "Riesgo alto de manipulación o humo"
        if risk_score >= 40:
            return "Riesgo moderado, requiere verificación"
        if risk_score >= 20:
            return "Riesgo bajo"
        return "Riesgo mínimo"

    if lang == "en":
        if risk_score >= 80:
            return "Extreme risk of deceptive hype"
        if risk_score >= 60:
            return "High risk of manipulation or hype"
        if risk_score >= 40:
            return "Moderate risk, verification needed"
        if risk_score >= 20:
            return "Low risk"
        return "Minimal risk"

    if risk_score >= 80:
        return "Risque extrem de vente de fumee"
    if risk_score >= 60:
        return "Risque eleve de manipulation ou d'enfumage"
    if risk_score >= 40:
        return "Risque modere, verification necessaire"
    if risk_score >= 20:
        return "Risque faible"
    return "Risque minimal"


def build_risk_indicators(flags, lang="fr"):
    indicator_map = {
        "SENSATIONNALISME": {
            "fr": "Ton sensationnaliste",
            "es": "Tono sensacionalista",
            "en": "Sensationalist tone",
        },
        "CADRAGE CONSPIRATIONNISTE": {
            "fr": "Cadrage conspirationniste",
            "es": "Marco conspirativo",
            "en": "Conspiratorial framing",
        },
        "PROMESSE MIRACLE": {
            "fr": "Promesse miracle",
            "es": "Promesa milagrosa",
            "en": "Miracle promise",
        },
        "MANIPULATION EMOTIONNELLE": {
            "fr": "Manipulation emotionnelle",
            "es": "Manipulacion emocional",
            "en": "Emotional manipulation",
        },
        "RHETORIQUE COERCITIVE": {
            "fr": "Rhetorique coercitive",
            "es": "Retorica coercitiva",
            "en": "Coercive rhetoric",
        },
        "PROMESSE THERAPEUTIQUE": {
            "fr": "Promesse therapeutique non prouvee",
            "es": "Promesa terapeutica no probada",
            "en": "Unproven therapeutic promise",
        },
        "PSEUDO-MEDECINE": {
            "fr": "Pseudo-medecine",
            "es": "Pseudomedicina",
            "en": "Pseudomedicine",
        },
        "BIAIS D'AUTORITE": {
            "fr": "Appel a l'autorite",
            "es": "Apelacion a la autoridad",
            "en": "Appeal to authority",
        },
        "PSEUDO-SCIENCE": {
            "fr": "Pseudo-science",
            "es": "Pseudociencia",
            "en": "Pseudoscience",
        },
        "CROYANCE TRANSGENERATIONNELLE": {
            "fr": "Croyance transgenerationnelle",
            "es": "Creencia transgeneracional",
            "en": "Transgenerational belief claim",
        },
    }

    lang_key = lang if lang in {"fr", "es", "en"} else "fr"
    output = []
    for flag in flags or []:
        if flag in indicator_map:
            output.append(indicator_map[flag][lang_key])
        else:
            output.append(flag)

    # Keep indicators concise and deterministic in the UI.
    return list(dict.fromkeys(output))[:6]


def update_report_summary_lines(analysis_text, score, flags, lang="fr"):
    return normalize_phase0_structure(analysis_text, analysis_text, lang)


def enforce_analysis_consistency(analysis_text, score, flags, lang="fr"):
    normalized_text = normalize_for_match(analysis_text)
    normalized_flags = []
    had_real_flags = False
    default_flag_labels = {
        get_default_flag_label(lang, score),
        "AUCUN SIGNAL MAJEUR",
        "NINGUNA ALERTA MAYOR",
        "NO MAJOR ALERT",
    }
    for flag in flags or []:
        clean_flag = str(flag).strip()
        if clean_flag and clean_flag not in normalized_flags and clean_flag not in default_flag_labels:
            normalized_flags.append(clean_flag)
            had_real_flags = True

    trigger_flags = []

    if "postulats systemiques difficiles a verifier" in normalized_text or "postulats difficiles a verifier" in normalized_text:
        trigger_flags.append("CROYANCE TRANSGENERATIONNELLE")

    if "promesse d'un acces a la 'racine' du probleme" in normalized_text or "promesse d'un acces a la racine du probleme" in normalized_text:
        trigger_flags.extend(["PROMESSE IMPLICITE", "CROYANCE TRANSGENERATIONNELLE"])

    for flag in trigger_flags:
        if flag not in normalized_flags:
            normalized_flags.append(flag)

    if trigger_flags and score >= 70:
        score = 60

    dominant_severity = get_dominant_severity(normalized_flags)
    if dominant_severity and dominant_severity in {"D", "E"}:
        score = SEVERITY_SCORE[dominant_severity]
    elif dominant_severity == "C" and score >= 78:
        score = SEVERITY_SCORE[dominant_severity]

    if not had_real_flags and not trigger_flags:
        score = max(score, 82)

    if not normalized_flags:
        normalized_flags = [get_default_flag_label(lang, score)]

    updated_analysis = update_report_summary_lines(analysis_text, score, normalized_flags, lang)
    return updated_analysis, score, normalized_flags

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
        languages = ['es', 'fr', 'en']
        if hasattr(YouTubeTranscriptApi, 'get_transcript'):
            transcript_items = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        else:
            transcript = YouTubeTranscriptApi().fetch(video_id, languages=languages)
            transcript_items = getattr(transcript, 'snippets', transcript)

        transcript_text = ' '.join(
            item.get('text', '') if isinstance(item, dict) else getattr(item, 'text', '')
            for item in transcript_items
        )
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


def extract_pdf_text(file_storage):
    if PdfReader is None:
        print("[PDF Warning] pypdf is not installed.")
        return None

    try:
        file_storage.stream.seek(0)
        reader = PdfReader(file_storage.stream)
        pages_text = [page.extract_text() or "" for page in reader.pages]
        extracted = "\n".join(pages_text).strip()
        return extracted or None
    except Exception as err:
        print(f"[PDF Extraction Error] {err}")
        return None


# =====================================================================
# FUNCIONES AUXILIARES Y UTILIDADES DE AUDITORIA
# =====================================================================
def generate_audit_metadata(input_text, pdf_bytes=None):
    """Generate verifiable UTC and SHA-256 audit metadata for an analysis."""
    text_hash = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest() if pdf_bytes else None

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "text_hash_sha256": text_hash,
        "pdf_hash_sha256": pdf_hash,
        "audit_id": text_hash[:12].upper(),
    }


@app.route("/", methods=["GET"])
def home():
    """Serve the main Beacon UI when opening the backend root URL."""
    candidate = os.path.abspath(os.path.join(app.root_path, "..", "beacon-app.html"))
    if os.path.exists(candidate):
        return send_file(candidate)

    return jsonify({
        "service": "Polethic Beacon API",
        "status": "online",
        "endpoints": ["/analyze", "/refute", "/export_pdf"]
    }), 200

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

        uploaded_file = request.files.get("file") or request.files.get("image")
        if uploaded_file and uploaded_file.filename:
            source_type = "file"
            filename_lower = uploaded_file.filename.lower()
            if filename_lower.endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp')):
                source_type = "image"
                ocr_text = ocr_image_file(uploaded_file)
                if ocr_text:
                    if content_to_analyze:
                        content_to_analyze = f"{content_to_analyze}\n\n[OCR text extracted from image:]\n{ocr_text}"
                    else:
                        content_to_analyze = ocr_text
                else:
                    if not content_to_analyze:
                        content_to_analyze = f"[IMAGE FILE: {uploaded_file.filename}]"
            elif filename_lower.endswith('.pdf'):
                pdf_text = extract_pdf_text(uploaded_file)
                if pdf_text:
                    if content_to_analyze:
                        content_to_analyze = f"{content_to_analyze}\n\n[PDF text extracted from {uploaded_file.filename}:]\n{pdf_text}"
                    else:
                        content_to_analyze = pdf_text
                elif not content_to_analyze:
                    return jsonify({"error": "No extractable text found in the PDF. Use a text-based PDF or an OCR-enabled image."}), 422
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

        audit_meta = generate_audit_metadata(content_to_analyze)
        template = TEMPLATES.get(lang, TEMPLATES["fr"])
        preliminary_hits = local_match_rules(
            content_to_analyze,
            academic_context=detect_academic_context(normalize_for_match(content_to_analyze)),
        )
        preliminary_flags = [hit["flag"] for hit in preliminary_hits]
        analysis_text = ""
        final_score = 50
        final_flags = []

        if MOCK_LLM:
            local_result = build_local_analysis_report(content_to_analyze, lang=lang)
            analysis_text = local_result["analysis"]
            score_tag = local_result["score"]
            flags_tag = ",".join(local_result["flags"])
            analysis_text += f"\n\n<flags>{flags_tag}</flags>\n<score>{score_tag}</score>"
        elif client:
            try:
                lang_names = {"fr": "FRENCH", "es": "SPANISH", "en": "ENGLISH"}
                target_lang_name = lang_names.get(lang, "FRENCH")

                user_prompt = (
                    f"CRITICAL REQUIREMENT: WRITE EVERYTHING 100% IN {target_lang_name}.\n"
                    f"DO NOT MIX LANGUAGES. USE ONLY {target_lang_name} FOR HEADERS AND CONTENT.\n\n"
                    f"Lexical pre-analysis detected these flags: {', '.join(preliminary_flags) or 'none'}.\n"
                    "Assess their context. When confirmed, preserve the same labels in the Phase 1 local evidence "
                    "and apply the severity implied by the detected flags.\n\n"
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

        final_flags = list(dict.fromkeys(final_flags + preliminary_flags))

        # Limpiar tags XML del texto resultante
        clean_analysis = re.sub(r"<score>.*?</score>", "", analysis_text, flags=re.DOTALL)
        clean_analysis = re.sub(r"<flags>.*?</flags>", "", clean_analysis, flags=re.DOTALL).strip()

        # FORZAR ENCABEZADOS EN EL IDIOMA OBJETIVO
        clean_analysis = force_language_headings(clean_analysis, target_lang=lang)
        clean_analysis, final_score, final_flags = enforce_analysis_consistency(clean_analysis, final_score, final_flags, lang)

        ethic_letter = get_ethic_letter(final_score)
        risk_score = max(0, min(100, 100 - final_score))
        risk_indicators = build_risk_indicators(final_flags, lang)
        save_audit("CORE", source_type, content_to_analyze, final_score, clean_analysis)

        return jsonify({
            "status": "success",
            "analysis": clean_analysis,
            "report": clean_analysis,
            "score": final_score,
            "flags": final_flags,
            "ethic_letter": ethic_letter,
            "scoreLetter": ethic_letter,
            "risk_grade": ethic_letter,
            "risk_label": get_risk_intensity_comment(risk_score, lang),
            "risk_indicators": risk_indicators,
            "audit_metadata": audit_meta,
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
            refutation_text = build_local_refutation(text_to_challenge, lang=lang)
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
        score_letter_raw = str(data.get("scoreLetter") or data.get("ethic_letter") or "").strip().upper()
        if score_letter_raw in SEVERITY_SCORE:
            score = SEVERITY_SCORE[score_letter_raw]
        else:
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
        analysis_text, score, flags = enforce_analysis_consistency(analysis_text, score, flags, lang)
        ethic_score_letter = get_ethic_letter(score)

        pdf_filename = f"RAPPORT_BEACON_{ethic_score_letter}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
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

        def score_palette(numeric_score):
            _, color = get_ethic_band(numeric_score)
            return color

        score_letter_colors = {
            "A": colors.HexColor("#00FF88"),
            "B": colors.HexColor("#FFE600"),
            "C": colors.HexColor("#FF8C00"),
            "D": colors.HexColor("#FF2A2A"),
            "E": colors.HexColor("#B00020"),
        }

        resolved_score_letter = score_letter_raw if score_letter_raw in score_letter_colors else get_ethic_letter(score)
        score_color = score_letter_colors.get(resolved_score_letter, score_palette(score))

        style_title = ParagraphStyle('DocTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=17, leading=21, textColor=colors.HexColor('#0F172A'), spaceAfter=2)
        style_subtitle_sm = ParagraphStyle('DocSubtitle', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=11, textColor=colors.HexColor('#475569'), spaceAfter=10)
        style_score_label = ParagraphStyle('ScoreLabel', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=6.8, leading=8.0, textColor=colors.white, alignment=1)
        style_score_value = ParagraphStyle('ScoreValue', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=13.8, leading=15.0, textColor=colors.white, alignment=1)

        style_meta_key = ParagraphStyle('MetaKey', parent=styles['Normal'], fontName='Courier-Bold', fontSize=8, leading=10, textColor=colors.HexColor('#0F172A'))
        style_meta_value = ParagraphStyle('MetaValue', parent=styles['Normal'], fontName='Courier', fontSize=8, leading=10, textColor=colors.HexColor('#0F172A'))

        style_indicator_title = ParagraphStyle('IndicatorTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8, leading=10, textColor=colors.HexColor('#334155'))
        style_indicator_chip = ParagraphStyle('IndicatorChip', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=6.8, leading=8.4, textColor=colors.HexColor('#334155'), alignment=1)

        style_section_title = ParagraphStyle('SectionTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor('#0F172A'), spaceBefore=10, spaceAfter=5)
        style_section_body = ParagraphStyle('SectionBody', parent=styles['Normal'], fontName='Helvetica', fontSize=8.8, leading=12.2, textColor=colors.HexColor('#111827'), spaceAfter=3)
        style_small_bullet = ParagraphStyle('SmallBullet', parent=styles['Normal'], fontName='Helvetica', fontSize=8.8, leading=12.2, textColor=colors.HexColor('#111827'), leftIndent=10, bulletIndent=0, spaceAfter=2)

        style_warn_title = ParagraphStyle('WarnTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=10.5, textColor=colors.HexColor('#6B3F0A'))
        style_warn_body = ParagraphStyle('WarnBody', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor('#2F2F2F'))

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

        pdf_labels = {
            "fr": {
                "title": "POLETHIC BEACON",
                "subtitle": "LABORATOIRE D'AUTODEFENSE COGNITIVE",
                "score_label": "ETHIC-SCORE",
                "ref_label": "REF DOSSIER :",
                "timestamp_label": "HORODATAGE :",
                "indicators_label": "INDICATEURS :",
                "footer": "POLETHIC BEACON | Rapport forensique d'intégrité cognitive"
            },
            "es": {
                "title": "POLETHIC BEACON",
                "subtitle": "LABORATORIO DE AUTODEFENSA COGNITIVA",
                "score_label": "PUNTAJE ÉTICO",
                "ref_label": "EXPEDIENTE REF :",
                "timestamp_label": "FECHA/HORA :",
                "indicators_label": "INDICADORES :",
                "footer": "POLETHIC BEACON | Informe forense de integridad cognitiva"
            },
            "en": {
                "title": "POLETHIC BEACON",
                "subtitle": "COGNITIVE SELF-DEFENSE LABORATORY",
                "score_label": "ETHIC SCORE",
                "ref_label": "REF CASE :",
                "timestamp_label": "TIMESTAMP :",
                "indicators_label": "INDICATORS :",
                "footer": "POLETHIC BEACON | Forensic report on cognitive integrity"
            }
        }
        pdf_text = pdf_labels.get(lang, pdf_labels["fr"])

        story = []
        title_banner = Table([
            [Paragraph(pdf_text["title"], style_title)],
            [Paragraph(pdf_text["subtitle"], style_subtitle_sm)]
        ], colWidths=[520])
        title_banner.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
            ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#CBD5E1')),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ]))
        story.append(title_banner)
        story.append(Spacer(1, 4))

        beacon_ref = f"BEACON-{datetime.now().year}-{int(datetime.now().timestamp()) % 1000000:06d}"
        score_box = Table([
            [Paragraph(pdf_text["score_label"], style_score_label)],
            [Paragraph(ethic_score_letter, style_score_value)]
        ], colWidths=[78])
        score_box.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), score_color),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOX', (0,0), (-1,-1), 0, colors.white),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ]))

        meta_lines = [
            f"<font face='Courier-Bold'>{pdf_text['ref_label']}</font> {beacon_ref}",
            f"<font face='Courier-Bold'>{pdf_text['timestamp_label']}</font> {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        ]
        meta_paragraph = Paragraph('<br />'.join(meta_lines), style_meta_value)

        top_row = Table([
            [score_box, meta_paragraph]
        ], colWidths=[94, 426])
        top_row.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FFFFFF')),
            ('BOX', (0,0), (-1,-1), 0.8, colors.HexColor('#CBD5E1')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 12),
            ('BOTTOMPADDING', (0,0), (-1,-1), 12),
        ]))

        indicator_tags = [str(flag).upper() for flag in (flags if flags else ['NONE'])]
        chips_per_row = 3
        chip_rows = []
        for idx in range(0, len(indicator_tags), chips_per_row):
            row_values = indicator_tags[idx:idx + chips_per_row]
            while len(row_values) < chips_per_row:
                row_values.append("")
            chip_rows.append([Paragraph(value, style_indicator_chip) if value else "" for value in row_values])

        indicator_line = Table(chip_rows, colWidths=[138, 138, 138])
        indicator_line.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('LEFTPADDING', (0,0), (-1,-1), 3),
            ('RIGHTPADDING', (0,0), (-1,-1), 3),
            ('TOPPADDING', (0,0), (-1,-1), 2),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ]))

        for r, row in enumerate(chip_rows):
            for c, cell in enumerate(row):
                if cell:
                    indicator_line.setStyle(TableStyle([
                        ('BACKGROUND', (c, r), (c, r), colors.HexColor('#EEF2F7')),
                        ('BOX', (c, r), (c, r), 0.5, colors.HexColor('#C7D1DE')),
                        ('ROUNDEDCORNERS', [2, 2, 2, 2]),
                    ]))

        indicator_row = Table([
            [Paragraph(pdf_text["indicators_label"], style_indicator_title), indicator_line]
        ], colWidths=[90, 430])
        indicator_row.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F7F8FA')),
            ('BOX', (0,0), (-1,-1), 0, colors.white),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))

        card_wrapper = Table([
            [top_row],
            [indicator_row]
        ], colWidths=[520])
        card_wrapper.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FFFFFF')),
            ('BOX', (0,0), (-1,-1), 0.8, colors.HexColor('#CBD5E1')),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))

        story.append(card_wrapper)
        story.append(Spacer(1, 18))

        def should_skip_pdf_line(line):
            no_md = re.sub(r'\*\*', '', line or '')
            normalized = normalize_for_match(no_md)
            core = re.sub(r'^[\s\-•]+', '', normalized)
            if core.startswith("phase ") or core.startswith("fase "):
                return True
            if core.startswith("ethic-score"):
                return True
            if core.startswith("flags detectes") or core.startswith("flags detectados") or core.startswith("flags detected"):
                return True
            return False

        for line in analysis_text.split('\n'):
            line_s = line.strip()
            if not line_s:
                continue
            if should_skip_pdf_line(line_s):
                continue

            clean_line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line_s)

            if is_heading_line(line_s):
                story.append(Paragraph(clean_line.upper(), style_section_title))
            elif line_s.startswith('- ') or line_s.startswith('• '):
                story.append(Paragraph(clean_line[2:], style_small_bullet, bulletText='•'))
            else:
                story.append(Paragraph(clean_line, style_section_body))

        if refutation_text:
            story.append(Spacer(1, 12))
            story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#64748B'), spaceBefore=10, spaceAfter=10))
            story.append(Paragraph(disc["refute_title"], style_section_title))

            warn_content = [
                Paragraph(disc["warn_title"], style_warn_title),
                Spacer(1, 2),
                Paragraph(disc["warn_body"], style_warn_body)
            ]
            t_warn = Table([[warn_content]], colWidths=[520])
            t_warn.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#FDF7ED")),
                ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#D6B47E")),
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
            canvas.setStrokeColor(colors.HexColor('#CBD5E1'))
            canvas.setLineWidth(0.6)
            canvas.line(36, 32, letter[0] - 36, 32)
            canvas.setFillColor(colors.HexColor('#334155'))
            canvas.setFont('Helvetica', 7.5)
            canvas.drawString(36, 20, pdf_text['footer'])
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
