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