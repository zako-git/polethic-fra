# POLETHIC BEACON

POLETHIC BEACON est un outil d'autodefense cognitive qui analyse la forme d'un discours: promesses, cadrage persuasif, autorite invoquee, opacite methodologique et risques de confusion avec un perimetre clinique. Il produit un rapport forensique structure, des indicateurs d'alerte et un `ETHIC-SCORE` de A a E.

Le moteur ne pose ni diagnostic medical, ni diagnostic psychologique, ni qualification juridique d'une personne ou d'une organisation. Les resultats decrivent uniquement les signaux presents dans le contenu soumis.

## Fonctionnalites

- Analyse de texte libre en francais, espagnol ou anglais.
- Analyse d'une URL publique: le contenu HTML est extrait puis analyse.
- Analyse de PDF textuels: le texte du document est extrait localement avec `pypdf`.
- Rapport local deterministe en six phases: contexte, promesses, demontage forensique, sources, logique et synthese du risque.
- Questions de refutation cognitive via `POST /refute`.
- Bloc optionnel `MEMES`: synthese courte, directe et fondee sur les indicateurs detectes.
- Export d'un rapport PDF forensique avec score colore, metadonnees, indicateurs, citations et conclusion.

Les PDF scannes sans couche de texte ne peuvent pas etre lus automatiquement. Il faut utiliser un PDF ayant subi un OCR ou coller le texte manuellement.

## ETHIC-SCORE

Le score mesure le niveau de signaux rhetoriques detectes: plus il est eleve, plus les elements a verifier sont nombreux ou importants.

| Lettre | Score | Couleur | Lecture operationnelle |
| --- | ---: | --- | --- |
| A | 0-15 | Bleu | Peu ou pas de signaux detectes |
| B | 16-30 | Vert | Vigilance faible |
| C | 31-45 | Jaune | Elements a verifier |
| D | 46-60 | Orange | Risque modere a eleve |
| E | 61-100 | Rose/rouge | Risque eleve |

La lettre et sa couleur sont coherentes dans l'interface et dans le PDF exporte.

## Structure du projet

```text
.
|-- backend/
|   |-- app.py                 # API Flask, analyse, extraction et export PDF
|   |-- requirements.txt       # Dependances Python
|   |-- tests/test_scoring.py  # Tests de regression
|   |-- static/                # Ressources de l'interface Flask historique
|   `-- templates/             # Gabarits Flask historiques
|-- frontend/
|   |-- beacon-app.html        # Interface principale BEACON
|   |-- css/styles.css         # Styles des pages publiques
|   `-- post/                  # Contenus editoriaux
`-- README.md
```

Les fichiers `.env`, `venv/`, caches Python et fichiers temporaires ne doivent pas etre versionnes. La base `backend/beacon.db` doit etre versionnee seulement si elle constitue une base de demonstration reproductible; sinon, elle doit rester locale et etre ajoutee au fichier `.gitignore`.

## Demarrage local

Prerequis: Python 3.10 ou plus recent.

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

L'API demarre sur `http://127.0.0.1:5000`.

Ouvrir ensuite [frontend/beacon-app.html](frontend/beacon-app.html) dans le navigateur. L'interface appelle le backend local sur le port `5000`.

## Analyse et export

### Analyser un texte

```bash
curl -X POST http://127.0.0.1:5000/analyze \
  -H "Content-Type: application/json" \
  -d '{"text":"Texte a analyser", "lang":"fr"}'
```

### Analyser un PDF

L'interface transmet le fichier PDF au meme endpoint `POST /analyze` avec un formulaire `multipart/form-data`. Le backend accepte actuellement les fichiers `.pdf` contenant du texte extractible.

### Exporter le rapport

`POST /export_pdf` recoit le rapport, la lettre de score et les indicateurs, puis renvoie le fichier `RAPPORT_BEACON.pdf`.

Le PDF contient une entete operationnelle avec `ETHIC-SCORE`, la reference de dossier et la date, les indicateurs d'alerte, les elements d'identification, les six phases et la conclusion. Les titres de phase et le badge score utilisent la couleur de l'ETHIC-SCORE.

## Endpoints

| Methode | Endpoint | Role |
| --- | --- | --- |
| `POST` | `/analyze` | Analyse de texte, URL ou PDF textuel |
| `POST` | `/refute` | Questions de refutation cognitive |
| `POST` | `/export_pdf` | Generation du rapport PDF |

## Mode d'analyse

L'analyse locale deterministe est la source de verite: elle calcule le score, les indicateurs et le rapport a partir de regles explicites. Une couche Gemini optionnelle peut etre activee pour enrichir le texte, sans remplacer les decisions locales:

```bash
export BEACON_ENABLE_GEMINI_ANALYSIS=true
python app.py
```

Cette option requiert la configuration des identifiants Gemini dans `backend/.env`. Sans cette variable, le fonctionnement local reste complet et ne depend d'aucune API externe.

## Tests

Depuis le dossier `backend`:

```bash
pytest tests/test_scoring.py -q
```

La suite couvre les scores et indicateurs, les regles de prudence clinique, l'analyse locale, l'extraction de contenu et la generation d'un PDF valide.

## Limites et responsabilite

POLETHIC BEACON est un outil d'analyse de discours, d'education et de prevention. Il ne remplace pas un professionnel de sante, un psychologue, un juriste ou une autorite competente. Toute decision concernant un soin, une situation de danger ou une procedure doit etre prise avec les professionnels concernes.