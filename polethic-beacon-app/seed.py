import sqlite3
import os

DATABASE_NAME = "beacon.db"


def initialize_database():
    # 1. Remove any previous database to avoid duplicates during testing
    if os.path.exists(DATABASE_NAME):
        os.remove(DATABASE_NAME)
        print(f"[*] Old '{DATABASE_NAME}' removed for a clean setup.")

    # 2. Connect to the SQLite engine
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    print(f"[*] Connecting to database: {DATABASE_NAME}")

    # 3. Enable foreign keys to guarantee referential integrity
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 4. Create Table: Filter Modules (Beacon Ecosystem)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS modules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL
    );
    """)

    # 5. Create Table: Local Flag Taxonomy (Detectable Risk Keywords)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS local_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module_key TEXT NOT NULL,
        keyword TEXT NOT NULL,
        risk_category TEXT NOT NULL,
        penalty_points INTEGER NOT NULL,
        FOREIGN KEY (module_key) REFERENCES modules(key)
    );
    """)

    # 6. Create Table: Centralized Audit Log (Historical Ledger)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        module_key TEXT NOT NULL,
        source_type TEXT NOT NULL,
        raw_content TEXT NOT NULL,
        ethic_score INTEGER NOT NULL,
        diagnostic_report TEXT NOT NULL,
        FOREIGN KEY (module_key) REFERENCES modules(key)
    );
    """)
    print("[+] Core structural tables created successfully.")

    # 7. Seed Data: Application Modules (CORRECTED: 'cv' updated to 'identity_spoofing')
    modules_data = [
        ("news", "News Scanner"),
        ("myth", "Myth-Buster"),
        ("identity_spoofing", "Identity Spoofing"),
        ("coercion", "Coercive Filter")
    ]
    cursor.executemany("INSERT INTO modules (key, name) VALUES (?, ?);", modules_data)

    # 8. Seed Data: Local Deterministic Rules (Fully Bilingual)
    # NOTE: 'keyword' values are intentionally multilingual (ES/EN) — this is
    # detection data, not source code, and must not be translated to English.
    # Translating them would break detection of Spanish-language input.
    # Note: penalty_points now directly ADD to the total Ethic-Score threat calculation (0 to 100)
    rules_data = [
        # =====================================================================
        # MODULE: MYTH-BUSTER (Pseudoscience / Myths)
        # =====================================================================
        # Spanish Core
        ("myth", "constelaciones familiares", "Pseudoscience Framework", 25),
        ("myth", "bioneuroemocion", "Pseudoscience Framework", 25),
        ("myth", "biodescodificacion", "Pseudoscience Framework", 25),
        ("myth", "biomagnetismo", "Unverified Therapy", 20),
        ("myth", "cuántica", "Misused Medical Jargon", 15),
        ("myth", "regresion a vidas pasadas", "False Memory Risk / Pseudoscience", 25),
        ("myth", "hipnosis cuantica", "Sci-Fi Medical Fraud", 30),
        # Protected Clinical Term (Context-Gated in app.py — same gating as "trauma bond")
        ("myth", "trabajo de sombra", "Unregulated Psychological Practice", 10),

        # English Core
        ("myth", "med beds", "Sci-Fi Medical Fraud", 30),
        ("myth", "vibrational frequency", "Pseudoscience Framework", 15),
        ("myth", "alkaline diet", "Unverified Therapy", 20),
        ("myth", "heavy metal cleanse", "Detox Marketing Scam", 20),
        ("myth", "quantum manifestation", "Misused Scientific Jargon", 25),
        ("myth", "past life regression", "False Memory Risk / Pseudoscience", 25),
        ("myth", "quantum hypnosis", "Sci-Fi Medical Fraud", 30),
        ("myth", "subliminal reprogramming", "Unverified Psychological Claim", 15),
        # Protected Clinical Term (Context-Gated in app.py — same gating as "trauma bond")
        ("myth", "shadow work", "Unregulated Psychological Practice", 10),
        ("myth", "ancestral healing", "Pseudoscience Framework", 20),

        # =====================================================================
        # MODULE: IDENTITY SPOOFING (Intrusism / Credentials) -> UPDATED KEY
        # =====================================================================
        # Spanish Core
        ("identity_spoofing", "coach ontológico", "Ontological Frame Blending", 15),
        ("identity_spoofing", "experto en bioneuroprogramación", "Inflated Title", 20),
        ("identity_spoofing", "terapeuta holístico", "Unregulated Practice", 15),
        ("identity_spoofing", "hipnoterapeuta certificado", "Unregulated Practice Alert", 15),
        ("identity_spoofing", "sanador cuantico", "Inflated Title / Intrusion", 25),

        # New: Clinical Nomenclature Appropriation (PPI Framework Criterion 2) —
        # diagnostic-manual / neurodevelopmental terms used by unlicensed profiles
        ("identity_spoofing", "neurodivergencias", "Clinical Nomenclature Appropriation", 15),
        ("identity_spoofing", "neuroatípico", "Clinical Nomenclature Appropriation", 15),
        ("identity_spoofing", "analista cognitivo-conductual", "Regulatory Arbitrage (Unregulated Title)", 20),

        # English Core
        ("identity_spoofing", "certified hypnotherapist", "Unregulated Practice Alert", 15),
        ("identity_spoofing", "quantum healer", "Inflated Title / Intrusion", 25),
        ("identity_spoofing", "spiritual guide", "Unregulated Practice", 15),
        ("identity_spoofing", "biohacking consultant", "Uncertified Health Claims", 20),
        ("identity_spoofing", "holistic practitioner", "Unregulated Practice", 15),

        # New: Clinical Nomenclature Appropriation (PPI Framework Criterion 2) —
        # diagnostic-manual / neurodevelopmental terms used by unlicensed profiles
        ("identity_spoofing", "neurodivergences", "Clinical Nomenclature Appropriation", 15),
        ("identity_spoofing", "neuroatypical", "Clinical Nomenclature Appropriation", 15),
        ("identity_spoofing", "cognitive-behavioral analyst", "Regulatory Arbitrage (Unregulated Title)", 20),

        # =====================================================================
        # MODULE: COERCIVE FILTER (MLM / Predatory Rhetoric)
        # =====================================================================
        # Spanish Core
        ("coercion", "sé tu propio jefe", "MLM Recruitment Trap", 30),
        ("coercion", "libertad financiera", "Predatory Rhetoric", 20),
        ("coercion", "oportunidad única de inversión", "High-Pressure Sales", 25),
        ("coercion", "mentores cuánticos", "Coercive Framing", 20),
        ("coercion", "salir de la matriz", "Coercive Framing", 25),
        ("coercion", "ingresos pasivos", "Predatory Rhetoric", 20),

        # English Core
        ("coercion", "escape the matrix", "Coercive Framing", 25),
        ("coercion", "passive income stream", "Predatory Rhetoric", 20),
        ("coercion", "high-ticket affiliate", "MLM Recruitment Trap", 30),
        ("coercion", "financial freedom blueprint", "High-Pressure Sales", 20),
        ("coercion", "alpha male bootcamp", "Coercive Behavioral Control", 30),

        # Protected Clinical Terms (Context-Gated in app.py)
        ("coercion", "trauma bond", "Overused Therapy Jargon", 10),
        ("coercion", "reparent your inner child", "Predatory Rhetoric", 10)
    ]
    cursor.executemany(
        "INSERT INTO local_rules (module_key, keyword, risk_category, penalty_points) VALUES (?, ?, ?, ?);",
        rules_data
    )

    # 9. Commit changes and close the connection safely
    conn.commit()
    conn.close()
    print("[+] Database seeding completed successfully. Polethic Beacon is ready.")


if __name__ == "__main__":
    initialize_database()
