"""Tests para validador de RFC mexicano."""

from app.utils.rfc_validator import validar_formato_rfc, validar_rfc_completo


class TestFormatoRFC:
    def test_rfc_generico_nacional(self):
        valido, _ = validar_formato_rfc("XAXX010101000")
        assert valido

    def test_rfc_generico_extranjero(self):
        valido, _ = validar_formato_rfc("XEXX010101000")
        assert valido

    def test_rfc_persona_fisica_formato(self):
        valido, msg = validar_formato_rfc("GARC850101ABC")
        assert valido
        assert "fisica" in msg.lower() or "válido" in msg.lower()

    def test_rfc_persona_moral_formato(self):
        valido, msg = validar_formato_rfc("GAR850101ABC")
        assert valido

    def test_rfc_muy_corto(self):
        valido, _ = validar_formato_rfc("ABC")
        assert not valido

    def test_rfc_muy_largo(self):
        valido, _ = validar_formato_rfc("ABCD8501011234X")
        assert not valido

    def test_rfc_mes_invalido(self):
        valido, _ = validar_formato_rfc("GARC851301ABC")
        assert not valido

    def test_rfc_dia_invalido(self):
        valido, _ = validar_formato_rfc("GARC850132ABC")
        assert not valido


class TestRFCCompleto:
    def test_generico_valido(self):
        valido, _ = validar_rfc_completo("XAXX010101000")
        assert valido
