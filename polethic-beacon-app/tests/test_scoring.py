import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("app", ROOT / "app.py")
app_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app_module)


def test_neutral_text_stays_in_a_band():
    result = app_module.build_local_analysis_report(
        "Este texto es neutral y claro, sin promesas ni miedo ni urgencia.",
        lang="es",
    )
    assert result["score"] >= 85
    assert result["analysis"].startswith("**1")


def test_business_consulting_stays_in_b_band():
    result = app_module.build_local_analysis_report(
        "Soy especialista en mediación y consultoría organizacional para empresas familiares.",
        lang="es",
    )
    assert result["score"] >= 70 and result["score"] < 85


def test_mild_persuasion_goes_to_b_band():
    result = app_module.build_local_analysis_report(
        "Este texto promete resultados si sigues el método, pero sin amenazas ni afirmaciones médicas.",
        lang="es",
    )
    assert 75 <= result["score"] <= 87


def test_persuasive_unverified_claims_go_to_c_or_lower():
    result = app_module.build_local_analysis_report(
        "Esta tecnica cuantica reequilibra el cuerpo, te lleva a la paz interior y solo funciona si sigues el metodo sin dudar.",
        lang="es",
    )
    assert result["score"] < 70


def test_phase0_contains_only_summary_domain_and_document_type():
    result = app_module.build_local_analysis_report(
        "Este texto presenta una metodología de coaching existencial para gestionar emociones y alcanzar el éxito personal.",
        lang="es",
    )
    analysis = result["analysis"]
    assert "Tema / Resumen" in analysis
    assert "Dominio" in analysis
    assert "Tipo de documento" in analysis
    assert "Ethic-Score" not in analysis
    assert "Flags" not in analysis


def test_medical_abandonment_is_severe():
    result = app_module.build_local_analysis_report(
        "Deja tus medicamentos, los medicos te mienten, esta tecnica milagrosa te cura y solo nosotros podemos salvarte.",
        lang="es",
    )
    assert result["score"] <= 40
