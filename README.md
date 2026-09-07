-------------------------------------------------------------
# 📡 POLETHIC BEACON
--------------------------------------------------------------
> Outil forensique d'autodéfense cognitive pour la détection de la rhétorique persuasive, de la pseudoscience, des biais New Age et du marketing abusif.

**POLETHIC BEACON** analyse la structure du discours : promesses non fondées, cadrage persuasif, appel à de fausses autorités, opacité méthodologique et risques d'empiétement sur le périmètre clinique. Il génère un rapport forensique structuré, des indicateurs d'alerte et un score d'évaluation `ETHIC-SCORE` (de A à E).

La langue principale du système est le **Français (FR)**, avec prise en charge native de l'**Espagnol (ES)** et de l'**Anglais (EN)**.

> ⚠️ **Avertissement de responsabilité :** Le moteur ne pose aucun diagnostic médical, psychologique ou juridique. Les résultats décrivent exclusivement les signaux et données présents dans le contenu soumis.

---

## 🚀 Fonctionnalités

- **Ingestion Multi-Format :** Analyse de texte brut, URL publiques (extraction HTML), documents PDF (vectoriels et scannés via OCR) et images (`.png`, `.jpg`).
- **Transcription YouTube :** Extraction automatique des sous-titres des vidéos pour analyse rétorique.
- **Support Multilingue (i18n) :** Traitement natif prioritaire en **Français (`fr`)**, avec fallback dynamique vers l'**Espagnol (`es`)** et l'**Anglais (`en`)**.
- **Pipeline Déterministe en 6 Phases :** Contexte, promesses, démontage forensique, sources, logique et synthèse du risque.
- **Réfutation Cognitive (`POST /refute`) :** Génération de questions ciblées pour déconstruire le discours analysé.
- **Module `MEMES` :** Résumé exécutif incisif basé sur les indicateurs détectés.
- **Rapport PDF Forensique :** Exportation structurée avec code couleur, métadonnées, citations contextuelles et matrice de risque.
- **Architecture Hybride :** Analyse locale déterministe autonome, enrichie optionnellement par l'API Gemini.

---

## 📊 Matrice ETHIC-SCORE

Le score mesure la densité de signaux rhétoriques et de sophismes détectés :

| Lettre | Score | Couleur | Niveau de Risque / Lecture Opérationnelle |
| :--- | :---: | :--- | :--- |
| **A** | 0 - 15 | Bleu | **Aucun signal significatif.** Discours neutre ou transparent. |
| **B** | 16 - 30 | Vert | **Vigilance faible.** Présence minime d'éléments persuasifs. |
| **C** | 31 - 45 | Jaune | **Éléments à vérifier.** Affirmations non étayées ou ambiguës. |
| **D** | 46 - 60 | Orange | **Risque modéré à élevé.** Manipulation rhétorique explicite. |
| **E** | 61 - 100 | Rose / Rouge | **Risque critique.** Haute densité de biais, pseudoscience ou charlatanisme. |

---

## 🛠️ Prérequis et Installation

### 1. Dépendances Système (OCR & Conversion PDF)

Nécessaire pour le traitement des images et des fichiers PDF scannés :

```bash
# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-fra tesseract-ocr-spa poppler-utils

```

### 2. Environnement Python

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

```

### 3. Configuration des Variables d'Environnement

Créez un fichier `backend/.env` :

```env
PORT=5000
FLASK_ENV=development
DEFAULT_LANG=fr
BEACON_ENABLE_GEMINI_ANALYSIS=false
GEMINI_API_KEY=votre_cle_api_optionnelle

```

---

## 🔌 Référence de l'API

### `POST /analyze`

Point d'entrée principal pour l'analyse de textes, URLs, images ou documents.

**En-tête HTTP :** `Content-Type: application/json` ou `multipart/form-data`

**Payload JSON (Texte ou URL) :**

```json
{
  "text": "[https://www.youtube.com/watch?v=example](https://www.youtube.com/watch?v=example)",
  "lang": "fr"
}

```

**Payload Multipart/Form-Data (Fichiers) :**

* `file` : Fichier binaire (`.pdf`, `.png`, `.jpg`).
* `lang` : Code langue (`fr` par défaut, `es`, `en`).

---

### `POST /refute`

Génère une série de questions critiques basées sur le rapport d'analyse.

---

### `POST /export_pdf`

Compile et retourne le rapport technique téléchargeable `RAPPORT_BEACON.pdf`.

---

## 💻 Structure du Projet

```text
.
├── backend/
│   ├── app.py                 # API Flask et endpoints principaux
│   ├── ingestion.py           # Pipeline d'extraction (OCR, PDF, URLs, YouTube)
│   ├── requirements.txt       # Dépendances Python
│   ├── .env                   # Variables d'environnement
│   └── tests/                 # Tests unitaires et d'intégration
│       └── test_scoring.py    # Validation du moteur d'analyse
├── frontend/
│   ├── beacon-app.html        # Interface utilisateur principale
│   ├── css/styles.css         # Styles UI et palettes ETHIC-SCORE
│   └── post/                  # Documentation éditoriale
└── README.md

```

---

## ⚡ Démarrage Local et Déploiement Cloud

### Exécution Locale

```bash
cd backend
python app.py

```

L'API démarre sur `http://127.0.0.1:5000`. Ouvrez `frontend/beacon-app.html` dans votre navigateur.

### Déploiement GitHub Codespaces + GitHub Pages

Pour autoriser les requêtes HTTPS depuis GitHub Pages :

1. Lancez l'API dans Codespaces (`python app.py`).
2. Dans l'onglet **Ports**, passez le port `5000` en **Public**.
3. Copiez l'URL HTTPS publique générée.
4. Injectez cette URL dans la variable `CODESPACES_BACKEND_URL` du fichier `docs/beacon-app.html`.

---

## 🧪 Tests et Qualité du Code

Exécutez la suite de tests automatisés :

```bash
cd backend
pytest tests/test_scoring.py -v

```

```

```