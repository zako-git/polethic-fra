import importlib.util
import io
from pathlib import Path

from pypdf import PdfReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("app", ROOT / "app.py")
app_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app_module)


def test_neutral_text_stays_in_a_band():
    result = app_module.build_local_analysis_report(
        "Este texto es neutral y claro, sin promesas ni miedo ni urgencia.",
        lang="es",
    )
    assert result["score"] <= 15
    assert result["analysis"].startswith('<div class="executive-metadata">')


def test_business_consulting_stays_in_b_band():
    result = app_module.build_local_analysis_report(
        "Soy especialista en mediación y consultoría organizacional para empresas familiares.",
        lang="es",
    )
    assert 15 <= result["score"] <= 35


def test_mild_persuasion_goes_to_b_or_c_band():
    result = app_module.build_local_analysis_report(
        "Este texto promete resultados si sigues el método, pero sin amenazas ni afirmaciones médicas.",
        lang="es",
    )
    assert 15 <= result["score"] <= 45


def test_scientific_text_has_low_noise():
    result = app_module.build_local_analysis_report(
        "Este estudio revisa métodos científicos, presenta resultados con análisis riguroso y evidencia clara.",
        lang="es",
    )
    assert result["score"] <= 15


def test_literary_text_has_low_noise():
    result = app_module.build_local_analysis_report(
        "En la noche de la ciudad, la luna abría un camino de humo sobre los muros del recuerdo.",
        lang="es",
    )
    assert result["score"] <= 18


def test_persuasive_unverified_claims_go_to_high_toxicity():
    result = app_module.build_local_analysis_report(
        "Esta tecnica cuantica reequilibra el cuerpo, te lleva a la paz interior y solo funciona si sigues el metodo sin dudar.",
        lang="es",
    )
    assert result["score"] > 45


def test_phase0_contains_only_summary_domain_and_document_type():
    result = app_module.build_local_analysis_report(
        "Este texto presenta una metodología de coaching existencial para gestionar emociones y alcanzar el éxito personal.",
        lang="fr",
    )
    analysis = result["analysis"]
    assert "Sujet / Résumé" in analysis
    assert "Domaine" in analysis
    assert "Type de document" in analysis
    assert '<div class="executive-metadata">' in analysis
    assert analysis.count('<div class="executive-metadata">') == 1
    assert "Ethic-Score" not in analysis
    assert "Flags" not in analysis


def test_phase1_quotes_literal_evidence_and_keeps_complete_phrases():
    text = (
        "Je suis ancien sportif, maintenant facilitatrice en constellations familiales. "
        "L'entraînement de l'esprit permet de trouver la paix et de reprendre le contrôle de nos vies. "
        "Le système familial sacré est la clé pour libérer le blocage corporel et la souffrance."
    )
    result = app_module.build_local_analysis_report(text, lang="fr")
    analysis = result["analysis"]
    assert '«L\'entraînement de l\'esprit permet de trouver la paix et de reprendre le contrôle de nos vies.»' in analysis
    assert '«Le système familial sacré est la clé pour libérer le blocage corporel et la souffrance.»' in analysis
    assert 'contrô»' not in analysis


def test_analysis_uses_six_phases_and_ethic_score_spinner_context():
    result = app_module.build_local_analysis_report(
        "Este texto promete resultados si sigues el método, pero sin amenazas ni afirmaciones médicas.",
        lang="fr",
    )
    analysis = result["analysis"]
    assert "### Phase 0" in analysis
    assert "### Phase 1" in analysis
    assert "### Phase 2" in analysis
    assert "### Phase 3" in analysis
    assert "### Phase 4" in analysis
    assert "### Phase 5" in analysis
    assert "phase 0: contexte et type de discours" in analysis.lower()
    assert "phase 1: promesses, autorité et solution miracle" in analysis.lower()
    assert "phase 2: démontage forensique" in analysis.lower()
    assert "phase 3: sources et intérêts" in analysis.lower()
    assert "phase 4: logique et biais" in analysis.lower()
    assert "phase 5: synthèse et risque" in analysis.lower()
    assert "Ethic-Score" not in analysis


def test_medical_abandonment_is_severe():
    result = app_module.build_local_analysis_report(
        "Deja tus medicamentos, los medicos te mienten, esta tecnica milagrosa te cura y solo nosotros podemos salvarte.",
        lang="es",
    )
    assert result["score"] >= 60


def test_french_miracle_claim_is_flagged():
    result = app_module.build_local_analysis_report(
        "Ce texte promet une guérison rapide, une urgence et une autorité sans preuve.",
        lang="fr",
    )
    assert result["score"] >= 35
    assert "PROMESA_MILAGROSA" in result["flags"] or "INJONCION" in result["flags"]


def test_french_coaching_self_transformation_is_not_neutral():
    text = (
        "Je suis Arantza Gandiaga, psychopédagogue, professeure, technique sportive et facilitatrice en constellations familiales. "
        "Nous devons prendre le contrôle de nos vies et ce n’est qu’ainsi que nous trouverons le bonheur, l’épanouissement et la paix. "
        "Il est très important d’entraîner l’esprit et de comprendre la racine de nos schémas de pensée."
    )
    result = app_module.build_local_analysis_report(text, lang="fr")
    assert result["score"] >= 20
    assert any(flag in result["flags"] for flag in ["COACHING_TRANSFORMATION", "PERSUASION", "INJONCION"])


def test_clinical_language_does_not_hide_coaching_and_promise_risk_in_french():
    text = (
        "Analyste cognitivo-comportementale. Conseil | Masterclass | Conférences. "
        "Je propose des évaluations de terrain et des hypothèses cliniques structurées sur les dynamiques comportementales émotionnelles. "
        "J'interviens en complément de vos diagnostics pour apporter un éclairage clinique structuré. "
        "Sans hypnose. Sans thérapie. Masterclass pour le développement personnel, bien-être et coaching. "
        "Décoder les dimensions invisibles de la psyché, ressortir des résultats pérennes et transmuter les émotions limitantes en émotions créatrices."
    )
    result = app_module.build_local_analysis_report(text, lang="fr")
    assert result["score"] > 15
    assert any(flag in result["flags"] for flag in ["COACHING_TRANSFORMATION", "PERSUASION", "PROMESA_MILAGROSA"])


def test_clinical_scope_claims_are_not_misclassified_as_miracle_promises():
    text = (
        "Je propose des hypothèses cliniques pour compléter vos diagnostics auprès de patients. "
        "J'étudie les corrélations entre les états émotionnels et les dysfonctionnements métaboliques. "
        "Ma méthode repose sur la psychanalyse jungienne et l'analyse fonctionnelle du comportement."
    )
    result = app_module.build_local_analysis_report(text, lang="fr")
    assert "PERIMETRE_CLINIQUE_NON_ETAYE" in result["flags"]
    assert "PROMESA_MILAGROSA" not in result["flags"]
    assert "intervention clinique auprès de patients" in result["analysis"]


def test_clinical_scope_risk_is_capped_and_has_specific_summary_and_questions():
    text = (
        "Masterclass pour le coaching. J'interviens auprès de patients en complément de diagnostics, "
        "avec des hypothèses cliniques sur les corrélations entre émotions et dysfonctionnements métaboliques. "
        "Mes programmes permettent d'obtenir des résultats pérennes."
    )
    result = app_module.build_local_analysis_report(text, lang="fr")
    summary = app_module.build_summary_text(result["score"], result["flags"], lang="fr")
    questions = app_module.build_refutation_questions(result["flags"], lang="fr")
    assert result["score"] <= 60
    assert "urgence coercitive" not in result["analysis"]
    assert "confusion entre offre de formation, coaching et périmètre clinique" in summary
    assert any("qualification" in question for question in questions)
    assert not any("confiance immédiate" in question for question in questions)


def test_chronic_pain_wellness_offer_is_not_neutral_or_a_miracle_claim():
    text = (
        "Un suivi pour les personnes sans solution à leur fatigue et leurs douleurs chroniques. "
        "J'ai eu des crises de migraine, puis l'inflammation et Hashimoto. "
        "Mon accompagnement permet d'avoir moins mal, de récupérer de l'énergie et de rééquilibrer le corps "
        "avec les neurosciences, la micronutrition et des remèdes naturels."
    )
    result = app_module.build_local_analysis_report(text, lang="fr")
    summary = app_module.build_summary_text(result["score"], result["flags"], lang="fr")
    assert 45 <= result["score"] <= 60
    assert "ACCOMPAGNEMENT_SANTE_NON_ETAYE" in result["flags"]
    assert "PROMESA_MILAGROSA" not in result["flags"]
    assert "douleurs chroniques" in result["analysis"]
    assert "Accompagnement bien-être et symptômes chroniques" in result["analysis"]
    assert "offre d'accompagnement individuel visant la fatigue" in result["analysis"]
    assert "bénéfices de santé non documentés" in summary


def test_sectarian_drift_flag_is_detected_for_family_constellations_and_pseudotherapy():
    text = (
        "Nous faisons de la psychogénéalogie, des constellations familiales et des ateliers de libération. "
        "Le but est de faire apparaître la racine de nos schémas dans un système familial sacré, "
        "sans aucun doute, pour contrôler nos vies et retrouver le bonheur par une transformation profonde."
    )
    result = app_module.build_local_analysis_report(text, lang="fr")
    assert result["score"] >= 35
    assert "DERIVA_SECTARIA_PSEUDOTERAPIA" in result["flags"]


def test_local_report_contextualizes_real_text_and_avoids_redundant_phase_titles():
    text = (
        "Je suis ancien sportif, maintenant facilitatrice en constellations familiales. "
        "L'entraînement de l'esprit permet de trouver la paix et de reprendre le contrôle de nos vies. "
        "Le système familial sacré est la clé pour libérer le blocage corporel et la souffrance."
    )
    result = app_module.build_local_analysis_report(text, lang="fr")
    analysis = result["analysis"]
    assert "constellations familiales" in analysis.lower()
    assert "contrôle de nos vies" in analysis.lower()
    assert "entraîner l'esprit" in analysis.lower()
    assert "Phase 1" in analysis and "Phase 1:" in analysis
    assert "Promesses, autorité" not in analysis
    assert "Dérive sectaire" in analysis or "dérive sectaire" in analysis.lower()


def test_semantic_drift_and_causal_opacity_are_flagged_in_local_report():
    text = (
        "Le système familial est la cause de tout, la douleur est simplement la preuve du schéma, "
        "et la transformation profonde est la seule explication valable sans démonstration indépendante."
    )
    result = app_module.build_local_analysis_report(text, lang="fr")
    assert "GLISSEMENT_SEMANTIQUE" in result["flags"]
    assert "OPACITE_CAUSALE" in result["flags"]


def test_force_structured_analysis_builds_multi_block_html():
    html = app_module.force_structured_analysis("Une seule phrase de résumé sans structure.", 82, ["GLISSEMENT_SEMANTIQUE"])
    assert "<h3>1)" in html
    assert "<h3>2)" in html
    assert "<h3>3)" in html
    assert "<ul>" in html


def test_forensic_report_includes_phase_sequence_without_displaying_bite_labels():
    result = app_module.build_local_analysis_report(
        "Nous avons la seule méthode pour libérer votre esprit, sans doute, avec une promesse de transformation totale et une autorité sans preuve.",
        lang="fr",
    )
    analysis = result["analysis"]
    assert "Phase 0" in analysis
    assert "Phase 1" in analysis
    assert "Phase 2" in analysis
    assert "Phase 3" in analysis
    assert "Phase 4" in analysis
    assert "Phase 5" in analysis
    assert "B.I.T.E." not in analysis
    assert "B = Behavior" not in analysis
    assert "I = Information" not in analysis
    assert "T = Thought" not in analysis
    assert "E = Emotion" not in analysis


def test_lexical_autopsy_keeps_complete_sentences_without_midword_truncation():
    text = (
        "Je suis ancien sportif, maintenant facilitatrice en constellations familiales. "
        "L'entraînement de l'esprit permet de trouver la paix et de reprendre le contrôle de nos vies. "
        "Le système familial sacré est la clé pour libérer le blocage corporel et la souffrance."
    )
    result = app_module.build_local_analysis_report(text, lang="fr")
    analysis = result["analysis"]
    assert "contrôle de nos vies" in analysis
    assert "libérer le blocage corporel et la souffrance" in analysis
    assert "«ancien sportif, maintenant facilitatrice en constellations familiales.»" in analysis or "«L'entraînement de l'esprit permet de trouver la paix et de reprendre le contrôle de nos vies.»" in analysis
    assert "contrô»" not in analysis
    assert "«eure" not in analysis


def test_business_text_does_not_inject_sectarian_template_phrases():
    text = (
        "About Me\n\nYou could say a thousand things about me, but here’s what truly matters: I’m a creative from Spain with over 40 years of experience in design, photography, and visual storytelling. "
        "I help my clients feel seen. Whether they’re building a brand or offering a service, I shape their identity through visuals that speak the same language as their audience. "
        "Together, we build a strategy that speaks to their current audience and attracts the future one."
    )
    result = app_module.build_local_analysis_report(text, lang="fr")
    analysis = result["analysis"].lower()
    assert "constellations familiales" not in analysis
    assert "bloquage corporel" not in analysis
    assert "libération" not in analysis
    assert "aucune citation exploitable" not in analysis
    assert "i help my clients feel seen" in analysis
    assert "relation client" in analysis or "stratégie" in analysis or "marque" in analysis


def test_phase0_uses_real_citations_once_and_not_generic_template():
    text = (
        "Mes ateliers et Masterclass vous permettent d’acquérir un système d'analyse, des programmes et des outils que vos clients ne trouveront nulle part ailleurs. "
        "Mes ateliers et Masterclass vous permettent d’acquérir un système d'analyse, des programmes et des outils que vos clients ne trouveront nulle part ailleurs."
    )
    result = app_module.build_local_analysis_report(text, lang="fr")
    analysis = result["analysis"].lower()
    assert "l'analyse insiste sur le terrain" not in analysis
    assert analysis.count("mes ateliers et masterclass") == 1
    assert analysis.count("vous permettent d’acquérir") == 1


def test_toxicity_scale_inverts_band_ranges():
    assert app_module.get_ethic_band(10) == ("A", "#273BE9")
    assert app_module.get_ethic_band(20) == ("B", "#09AA29")
    assert app_module.get_ethic_band(35) == ("C", "#FFB700")
    assert app_module.get_ethic_band(50) == ("D", "#FF6600")
    assert app_module.get_ethic_band(85) == ("E", "#FF0055")


def test_supported_model_candidates_include_current_fallbacks():
    assert "gemini-2.5-flash" in app_module.MODEL_CANDIDATES
    assert "gemini-2.5-flash-lite" in app_module.MODEL_CANDIDATES


def test_analysis_endpoint_rejects_a_prior_beacon_report():
    report = (
        "Ethic-Score: E\nSujet / Résumé\nPhase 0\nPhase 1\n"
        "Autopsie lexicale\nConclusion"
    )
    response = app_module.app.test_client().post("/analyze", json={"text": report, "lang": "fr"})
    assert response.status_code == 422
    assert response.get_json()["code"] == "BEACON_REPORT_REANALYSIS"


def test_analysis_endpoint_extracts_text_from_uploaded_pdf(monkeypatch):
    pdf_buffer = io.BytesIO()
    pdf = canvas.Canvas(pdf_buffer)
    pdf.drawString(72, 720, "Document PDF : analyse de texte source.")
    pdf.save()
    pdf_buffer.seek(0)
    monkeypatch.setattr(app_module, "client", None)

    extracted_text, extraction_error = app_module.extract_uploaded_pdf_text(
        type("Upload", (), {"filename": "source.pdf", "stream": io.BytesIO(pdf_buffer.getvalue())})()
    )
    assert extraction_error is None
    assert "Document PDF" in extracted_text

    response = app_module.app.test_client().post(
        "/analyze",
        data={"file": (pdf_buffer, "source.pdf"), "lang": "fr"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "success"


def test_analysis_endpoint_uses_local_result_unless_gemini_is_explicitly_enabled(monkeypatch):
    monkeypatch.setattr(app_module, "client", object())
    monkeypatch.delenv("BEACON_ENABLE_GEMINI_ANALYSIS", raising=False)
    text = "Texte descriptif sur un jardin urbain et ses plantations saisonnières."
    expected = app_module.build_local_analysis_report(text, lang="fr")

    response = app_module.app.test_client().post(
        "/analyze",
        json={"text": text, "lang": "fr"},
    )

    assert response.status_code == 200
    assert response.get_json()["score"] == expected["score"]
    assert response.get_json()["analysis"] == expected["analysis"]


def test_analysis_endpoint_extracts_a_webpage_url(monkeypatch):
    class FakeResponse:
        headers = {"Content-Type": "text/plain"}
        text = "<html><body><h1>Programme bien-être</h1><p>Réduire les douleurs chroniques avec des remèdes naturels.</p></body></html>"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(app_module, "client", None)
    monkeypatch.setattr(app_module.requests, "get", lambda *args, **kwargs: FakeResponse())
    response = app_module.app.test_client().post(
        "/analyze",
        json={"text": "https://example.com/programme", "lang": "fr"},
    )

    assert response.status_code == 200
    assert response.get_json()["source_type"] == "url"
    assert "ACCOMPAGNEMENT_SANTE_NON_ETAYE" in response.get_json()["flags"]


def test_spanish_neuroscience_wellness_claims_are_not_neutral():
    text = (
        "Entrenamiento con Tecnología de Neurociencia para reducir irritabilidad y mejorar el sueño de calidad. "
        "Conseguimos armonizar las frecuencias cerebrales y optimizar nuestro cerebro con ondas de frecuencias cerebrales."
    )
    result = app_module.build_local_analysis_report(text, lang="fr")
    summary = app_module.build_summary_text(result["score"], result["flags"], lang="fr")
    assert 45 <= result["score"] <= 60
    assert "REVENDICATION_NEUROSCIENTIFIQUE_NON_ETAYEE" in result["flags"]
    assert "armonizar las frecuencias cerebrales" in result["analysis"]
    assert "revendications neuro-scientifiques" in summary


def test_export_pdf_returns_a_pdf_without_html_markup():
    response = app_module.app.test_client().post(
        "/export_pdf",
        json={
            "scoreLetter": "D",
            "flags": ["REVENDICATION_NEUROSCIENTIFIQUE_NON_ETAYEE"],
            "analysis": "<div><p>1. Sujet / Résumé : Une affirmation de test.</p><p>2. Domaine : Bien-être</p><p>3. Type de document : Texte</p><h3>Phase 1: vérification</h3><p>- Une <strong>affirmation</strong> à vérifier.</p><p>Conclusion : Une conclusion de test.</p></div>",
        },
    )
    assert response.status_code == 200
    assert response.content_type == "application/pdf"
    assert response.data.startswith(b"%PDF")
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(response.data)).pages)
    normalized_pdf_text = " ".join(pdf_text.split())
    assert "POLETHIC BEACON" in pdf_text
    assert "RÉF" in normalized_pdf_text
    assert "INDICATEURS D'ALERTE" in normalized_pdf_text
    assert "Conclusion : Une conclusion de test." in pdf_text
    assert "Forensic Cognitive Engine" in pdf_text


def test_unregulated_clinical_title_with_masterclass_flags_scope():
    result = app_module.build_local_analysis_report(
        "Analyste cognitivo-comportementale | Auteur. Analyses cliniques des dynamiques comportementales, "
        "émotionnelles et leurs enjeux. Programmes de régulation émotionnelle et comportementale. "
        "Masterclass | Workshops.",
        lang="fr",
    )
    assert "PERIMETRE_CLINIQUE_NON_ETAYE" in result["flags"]
