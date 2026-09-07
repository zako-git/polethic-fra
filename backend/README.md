# Polethic Beacon App

## Demarrage local

Depuis la racine du depot:

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

L'API demarre sur `http://127.0.0.1:5000`. Pour executer les tests:

```bash
pytest tests/test_scoring.py -q
```

Pour un frontend GitHub Pages en HTTPS, rendre le port `5000` public dans Codespaces et utiliser son URL `https://...app.github.dev` comme valeur de `CODESPACES_BACKEND_URL` dans le template `beacon-app.html`. Ne pas utiliser `http://127.0.0.1:5000` depuis une page HTTPS.