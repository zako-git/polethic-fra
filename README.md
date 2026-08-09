# POLETHIC BEACON

## FR - Version Principale

Développé comme extension technique de Polethic, une association engagée dans la prévention des dérives sectaires, des comportements cultuels et de la manipulation psychologique, ce système agit comme moteur d'autodéfense cognitive et analyseur de métacommunication.

Au lieu d'être un fact-checker classique centré sur la vérité objective, POLETHIC BEACON se concentre sur la manière dont l'information est présentée. Le moteur analyse des textes, des transcriptions YouTube et des captures d'écran pour détecter le cadrage trompeur, les sophismes, la dilution pseudoscientifique et la rhétorique coercitive.

Le résultat est consolidé dans un Ethic-Score (0-100), accompagné de drapeaux de risque et d'un rapport d'analyse.

### Langues

- Langue principale: français
- Langues secondaires: espagnol et anglais

Le backend force la structure de sortie selon la langue demandée (fr, es, en), avec des en-têtes normalisés.

### Cle d'allumage (Demarrage rapide)

1. Aller dans le dossier backend:

```bash
cd polethic-beacon-app
```

2. Installer les dependances Python:

```bash
pip install -r requirements.txt
```

3. (Optionnel) Initialiser la base SQLite locale:

```bash
python seed.py
```

4. Lancer le serveur Flask:

```bash
python app.py
```

5. Le service demarre sur:

```text
http://127.0.0.1:5000
```

### Mode IA: token ou mode mock

Le backend lit la variable d'environnement HF_TOKEN pour utiliser Hugging Face Inference.

- Si HF_TOKEN est defini: analyse LLM active.
- Si HF_TOKEN est absent: bascule automatique en mode MOCK (reponse de test, sans consommation d'API).

Exemple:

```bash
export HF_TOKEN="votre_token_hf"
python app.py
```

### Architecture technique

Le projet s'appuie sur un pipeline multi-couche:

1. Frontend
- Interface web responsive (HTML/CSS/JS) pour soumettre texte, liens et images, puis afficher score et rapport.

2. Backend Flask
- Orchestration des endpoints API:
	- /analyze
	- /refute
	- /export_pdf
- Extraction de transcript YouTube.
- OCR d'images uploadees.
- Synthese LLM via Hugging Face.

3. Couche SQLite
- Taxonomie locale de modules et regles dans beacon.db.
- Journalisation historique des audits.

### Fondement methodologique

Le systeme traduit des cadres d'analyse comportementale en heuristiques operationnelles:

- 1. FakeNews Scanner: polarisation, hype artificielle, sensationnalisme emotionnel, consensus non verifie.
- 2. Myth-Buster: assertions pseudoscientifiques, deficit empirique, sophismes de validation dogmatique.
- 3. Identity Spoofing (cadre PPI): credentiels douteux, intrusion professionnelle, arbitrage reglementaire, incoherences epistemologiques.
- 4. Coercive Filter (modele BITE): signaux d'emprise selon les axes comportemental, informationnel, cognitif et emotionnel.

#### Coercive Filter: application du modele BITE

Le backend applique les quatre axes du modele BITE de Steven Hassan aux textes francais, espagnols et anglais:

- Controle comportemental: injonctions de discipline, regulation des horaires, privation ou restriction de conduites.
- Controle informationnel: interdiction des sources externes, disqualification des critiques ou isolement informationnel.
- Controle de la pensee: interdiction du doute, verite unique ou disqualification de toute remise en question.
- Controle emotionnel: peur de partir, culpabilisation, menace d'echec ou dependance au groupe.

Un axe BITE detecte est un signal D. Trois axes ou plus ajoutent le flag `EMPRISE PSYCHOLOGIQUE` et imposent le niveau E. Cette regle reste une detection de signaux linguistiques de prevention, et non un diagnostic clinique ou juridique.

#### Taxonomie lexicale BEACON

Avant toute synthese LLM, le backend normalise les accents et les separateurs puis recherche des groupes semantiques en francais, espagnol et anglais. Les flags preliminaires sont integres au prompt LLM et consolides avec la sortie afin que les indicateurs, les evidences locales et le score final restent coherents.

- `BLANCHIMENT SCIENTIFIQUE` + `BIAIS D'AUTORITE` (minimum C): jargon scientifique de prestige associe a une pratique alternative, sans credential clinique ou de recherche explicite dans l'extrait.
- `PROMESSE THERAPEUTIQUE` (minimum D): pathologie, symptome ou intervention de sante physique/mentale mentionne dans une proposition d'accompagnement ou de soin non validee dans l'extrait.
- `CROYANCE TRANSGENERATIONNELLE` (minimum C): memoire cellulaire, lignees, constellations, loyautes invisibles, karma familial ou causalites energetiques analogues.
- `PROMESSE IMPLICITE` + `CAPTATION DE VULNERABILITE` (minimum C): langage d'epuisement ou d'echec combine a un acces prive, une disponibilite constante ou une methode exclusive.

Ces regles sont des alertes de structure rhetorique. Elles ne permettent pas, a elles seules, d'etablir les qualifications reelles d'une personne ou la valeur clinique d'une pratique.

### Matrice d'evaluation et de decision (score A-E)

L'Ethic-Score evalue l'integrite rhetorique et epistemique du contenu, et non la valeur ou la moralite d'une personne. La matrice est definie en francais, puis appliquee avec une sortie localisee en espagnol et en anglais.

| Niveau | Plage indicative | Decision | Signaux typiques |
| --- | --- | --- | --- |
| A | 85-100 | Conforme / rigueur scientifique | Faits verifiables, sources, affiliations et donnees empiriques; aucun flag critique. |
| B | 70-84 | Vigilance mineure / communication commerciale | Autopresentation B2B/B2C standard, ambiguite methodologique, glissement d'expertise ou cadrage persuasif leger. |
| C | 50-69 | Attention requise / elements non eprouves | Pseudo-science, biais d'autorite, blanchiment scientifique, croyance transgenerationnelle ou promesse implicite. |
| D | 30-49 | Vigilance elevee / derive therapeutique | Promesse therapeutique, pseudo-medecine, application d'une pratique non validee a une pathologie physique, biais d'anecdote, validation croisee ou rhetorique virale fortement manipulatrice. |
| E | 0-29 | Alerte critique / emprise ou fraude manifeste | Injonction au decrochage medical, emprise psychologique, theorie du complot medical ou rhetorique cultuelle. |

Les indicateurs sont detectes dans les trois langues. Par exemple, une combinaison du type `BREAKING`, `they don't want you to know`, `one simple trick` et `share before they delete this` est classee D: elle associe sensationnalisme, cadrage conspirationniste, promesse miracle et injonction de diffusion, sans constituer a elle seule une preuve de pseudoscience de niveau E.

Le flag `BLANCHIMENT SCIENTIFIQUE` est declenche lorsqu'un texte associe des termes de prestige scientifique (par exemple neurosciences, neurobiologie ou physique quantique) a une pratique alternative non validee (remedes naturels, lectures energetiques, etc.), sans credential clinique ou neuroscientifique explicite dans l'extrait. Il impose au minimum le niveau C et s'accompagne de `BIAIS D'AUTORITE`. Lorsqu'une telle pratique est presentee pour traiter une pathologie physique ou auto-immune, le flag `APPLICATION A UNE PATHOLOGIE PHYSIQUE` impose le niveau D. Ces flags signalent la structure rhetorique de l'extrait et ne constituent pas une conclusion sur les qualifications reelles d'une personne.

La sortie conserve les memes niveaux dans les langues secondaires:

- ES: `A-E`, con banderas localizadas y la misma logica de decision.
- EN: `A-E`, with localized flags and the same decision logic.

#### Regles rigides de controle logique

1. Le moteur ne peut jamais afficher `AUCUN SIGNAL MAJEUR` ou son equivalent localise pour un score C, D ou E.
2. La lettre finale correspond toujours au flag le plus grave detecte. Un contenu majoritairement commercial B qui formule une promesse therapeutique D est donc classe D.
3. La lettre est calculee une seule fois par reponse et reutilisee par le badge web, le resume d'analyse et le nom du PDF: `RAPPORT_BEACON_[LETTRE]_[DATE].pdf`.

### Mecanique d'execution

1. Pipeline multimodal
- Audit textuel direct.
- Audit de transcript YouTube via youtube-transcript-api.
- Analyse OCR d'images (pytesseract + Pillow) avant passage dans le pipeline d'audit.

2. Couche locale deterministe (SQLite)
- La base locale (seed.py -> beacon.db) contient des mots-cles de risque par module (table local_rules) avec des points de penalite.
- En mode hybride complet, si un mot-cle est detecte, son poids est ajoute au diagnostic global.
- Les correspondances sont restituees comme indicateurs locaux (local flags).
- Selon la version deployee, cette couche peut etre active en production ou preparee/semmee pour extension immediate.

3. Couche LLM de synthese
- Le backend envoie le contenu a un modele heberge via Hugging Face Inference API pour classer, extraire les premisses, identifier biais/leviers emotionnels et proposer un recadrage cognitif.

4. Sortie consolidee
- Rapport structure en 4 phases.
- Drapeaux de risque.
- Ethic-Score numerique + lettre de niveau.
- Export PDF.

### Endpoints API

- POST /analyze: analyse principale
- POST /refute: generation de questions de refutation cognitive
- POST /export_pdf: export du rapport en PDF

Exemple:

```bash
curl -X POST http://127.0.0.1:5000/analyze \
	-H "Content-Type: application/json" \
	-d '{"text":"Texte de test","lang":"fr"}'
```

### Arborescence utile

```text
.
├── README.md
└── polethic-beacon-app/
		├── app.py
		├── seed.py
		├── requirements.txt
		├── templates/
		└── static/
```

### Licence et responsabilite

Ce projet est oriente autodéfense cognitive et analyse de rhetorique. Il ne remplace ni une expertise clinique, ni un conseil juridique, ni une verification scientifique formelle par un professionnel qualifie.

---

## ES - Version Secundaria

Desarrollado como una extension tecnica de Polethic, una asociacion dedicada a la prevencion de derivas sectarias, conductas cultuales y manipulacion psicologica, este sistema actua como motor de autodefensa cognitiva y analizador de metacomunicacion.

En lugar de funcionar como un fact-checker tradicional centrado en la verdad objetiva, POLETHIC BEACON se enfoca en como se presenta la informacion. El motor analiza textos, transcripciones de YouTube y capturas de pantalla para detectar encuadre linguistico enganoso, falacias, dilucion pseudocientifica y retorica coercitiva.

El resultado se consolida en un Ethic-Score (0-100), acompanado de banderas de riesgo y un informe analitico.

### Idiomas

- Idioma principal: frances
- Idiomas secundarios: espanol e ingles

El backend fuerza la estructura de salida segun el idioma solicitado (fr, es, en), con encabezados normalizados.

### Llave de encendido (Inicio rapido)

1. Ir al directorio del backend:

```bash
cd polethic-beacon-app
```

2. Instalar dependencias Python:

```bash
pip install -r requirements.txt
```

3. (Opcional) Inicializar la base SQLite local:

```bash
python seed.py
```

4. Levantar el servidor Flask:

```bash
python app.py
```

5. El servicio inicia en:

```text
http://127.0.0.1:5000
```

### Modo IA: token o modo mock

El backend lee la variable de entorno HF_TOKEN para usar Hugging Face Inference.

- Si HF_TOKEN esta definido: analisis LLM activo.
- Si HF_TOKEN no esta definido: cambio automatico a modo MOCK (respuesta de prueba, sin consumo de API).

Ejemplo:

```bash
export HF_TOKEN="tu_token_hf"
python app.py
```

### Arquitectura tecnica

La aplicacion sigue un pipeline multicapa:

1. Frontend
- Interfaz web responsive (HTML/CSS/JS) para enviar texto, enlaces e imagenes y visualizar score e informe.

2. Backend Flask
- Orquestacion de endpoints API:
	- /analyze
	- /refute
	- /export_pdf
- Extraccion de transcript de YouTube.
- OCR de imagenes cargadas.
- Sintesis LLM via Hugging Face.

3. Capa SQLite
- Taxonomia local de modulos y reglas en beacon.db.
- Registro historico de auditorias.

### Fundamento metodologico

El sistema traduce marcos de analisis conductual en heuristicas operativas:

- 1. FakeNews Scanner: polarizacion, hype artificial, sensacionalismo emocional y consenso no verificado.
- 2. Myth-Buster: afirmaciones pseudocientificas, deficit empirico y falacias de validacion dogmatica.
- 3. Identity Spoofing (marco PPI): credenciales dudosas, intrusismo profesional, arbitraje regulatorio e incoherencias epistemologicas.
- 4. Coercive Filter (modelo BITE): senales de control conductual, informacional, cognitivo y emocional.

### Mecanica de ejecucion

1. Pipeline multimodal
- Auditoria textual directa.
- Auditoria de transcript de YouTube con youtube-transcript-api.
- Analisis OCR de imagenes (pytesseract + Pillow) antes de pasar por el pipeline.

2. Capa local determinista (SQLite)
- La base local (seed.py -> beacon.db) contiene palabras clave de riesgo por modulo (tabla local_rules) con puntos de penalizacion.
- En modo hibrido completo, cuando se detecta una palabra clave, su peso se suma al diagnostico global.
- Las coincidencias se muestran como indicadores locales (local flags).
- Segun la version desplegada, esta capa puede estar activa en produccion o preparada/sembrada para extension inmediata.

3. Capa LLM de sintesis
- El backend envia el contenido a un modelo alojado en Hugging Face Inference API para clasificar, extraer premisas, identificar sesgos/disparadores emocionales y proponer un reencuadre cognitivo.

4. Salida consolidada
- Informe estructurado en 4 fases.
- Banderas de riesgo.
- Ethic-Score numerico + letra de nivel.
- Exportacion PDF.

### Endpoints API

- POST /analyze: analisis principal
- POST /refute: generacion de preguntas de refutacion cognitiva
- POST /export_pdf: exportacion del informe en PDF

Ejemplo:

```bash
curl -X POST http://127.0.0.1:5000/analyze \
	-H "Content-Type: application/json" \
	-d '{"text":"Texto de prueba","lang":"es"}'
```

### Licencia y responsabilidad

Este proyecto esta orientado a la autodefensa cognitiva y al analisis retorico. No sustituye evaluacion clinica profesional, asesoramiento juridico ni verificacion cientifica formal.
