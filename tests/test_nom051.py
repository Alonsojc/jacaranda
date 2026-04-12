"""Tests para cálculos de etiquetado NOM-051."""

from decimal import Decimal
from app.utils.nom051_helpers import (
    calcular_sellos_advertencia,
    calcular_leyendas_precautorias,
)


class TestSellosAdvertencia:
    def test_producto_saludable_sin_sellos(self):
        sellos = calcular_sellos_advertencia(
            calorias_por_100g=200,
            azucar_g_por_100g=Decimal("5"),
            grasa_saturada_g_por_100g=Decimal("2"),
            grasa_trans_g_por_100g=Decimal("0.1"),
            sodio_mg_por_100g=200,
        )
        assert len(sellos) == 0

    def test_exceso_calorias(self):
        sellos = calcular_sellos_advertencia(
            calorias_por_100g=400,  # > 275
            azucar_g_por_100g=Decimal("5"),
            grasa_saturada_g_por_100g=Decimal("2"),
            grasa_trans_g_por_100g=Decimal("0.1"),
            sodio_mg_por_100g=200,
        )
        assert "EXCESO CALORÍAS" in sellos

    def test_exceso_azucares(self):
        sellos = calcular_sellos_advertencia(
            calorias_por_100g=200,
            azucar_g_por_100g=Decimal("15"),  # > 10
            grasa_saturada_g_por_100g=Decimal("2"),
            grasa_trans_g_por_100g=Decimal("0.1"),
            sodio_mg_por_100g=200,
        )
        assert "EXCESO AZÚCARES" in sellos

    def test_exceso_sodio(self):
        sellos = calcular_sellos_advertencia(
            calorias_por_100g=200,
            azucar_g_por_100g=Decimal("5"),
            grasa_saturada_g_por_100g=Decimal("2"),
            grasa_trans_g_por_100g=Decimal("0.1"),
            sodio_mg_por_100g=500,  # > 350
        )
        assert "EXCESO SODIO" in sellos

    def test_multiples_sellos(self):
        sellos = calcular_sellos_advertencia(
            calorias_por_100g=400,
            azucar_g_por_100g=Decimal("15"),
            grasa_saturada_g_por_100g=Decimal("6"),
            grasa_trans_g_por_100g=Decimal("1.0"),
            sodio_mg_por_100g=500,
        )
        assert len(sellos) == 5

    def test_valores_none_ignorados(self):
        sellos = calcular_sellos_advertencia(
            calorias_por_100g=None,
            azucar_g_por_100g=None,
            grasa_saturada_g_por_100g=None,
            grasa_trans_g_por_100g=None,
            sodio_mg_por_100g=None,
        )
        assert len(sellos) == 0


class TestLeyendasPrecautorias:
    def test_con_edulcorantes(self):
        leyendas = calcular_leyendas_precautorias(contiene_edulcorantes=True)
        assert any("EDULCORANTES" in l for l in leyendas)

    def test_con_cafeina(self):
        leyendas = calcular_leyendas_precautorias(contiene_cafeina=True)
        assert any("CAFEÍNA" in l for l in leyendas)

    def test_sin_leyendas(self):
        leyendas = calcular_leyendas_precautorias()
        assert len(leyendas) == 0
