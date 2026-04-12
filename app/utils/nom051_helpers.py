"""
Cálculos para etiquetado NOM-051-SCFI/SSA1-2010 (Fase 3).
Determina sellos de advertencia y leyendas precautorias para productos empacados.
"""

from decimal import Decimal


# Umbrales NOM-051 Fase 3 (vigente desde oct 2025) - productos sólidos
UMBRALES_SOLIDOS = {
    "exceso_calorias_kcal_100g": 275,
    "exceso_azucares_g_100g": Decimal("10.0"),
    "exceso_grasas_saturadas_g_100g": Decimal("4.0"),
    "exceso_grasas_trans_g_100g": Decimal("0.5"),  # >1% del total de energía o >0.5g
    "exceso_sodio_mg_100g": 350,
}

# Para líquidos
UMBRALES_LIQUIDOS = {
    "exceso_calorias_kcal_100ml": 70,
    "exceso_azucares_g_100ml": Decimal("5.0"),
    "exceso_grasas_saturadas_g_100ml": Decimal("2.0"),
    "exceso_grasas_trans_g_100ml": Decimal("0.5"),
    "exceso_sodio_mg_100ml": 350,
}


def calcular_sellos_advertencia(
    calorias_por_100g: int | None,
    azucar_g_por_100g: Decimal | None,
    grasa_saturada_g_por_100g: Decimal | None,
    grasa_trans_g_por_100g: Decimal | None,
    sodio_mg_por_100g: int | None,
    es_liquido: bool = False,
) -> list[str]:
    """
    Determina qué sellos de advertencia debe llevar el producto.
    Retorna lista de sellos requeridos.
    """
    sellos = []
    umbrales = UMBRALES_LIQUIDOS if es_liquido else UMBRALES_SOLIDOS
    key_suffix = "100ml" if es_liquido else "100g"

    if calorias_por_100g is not None:
        if calorias_por_100g > umbrales[f"exceso_calorias_kcal_{key_suffix}"]:
            sellos.append("EXCESO CALORÍAS")

    if azucar_g_por_100g is not None:
        if azucar_g_por_100g > umbrales[f"exceso_azucares_g_{key_suffix}"]:
            sellos.append("EXCESO AZÚCARES")

    if grasa_saturada_g_por_100g is not None:
        if grasa_saturada_g_por_100g > umbrales[f"exceso_grasas_saturadas_g_{key_suffix}"]:
            sellos.append("EXCESO GRASAS SATURADAS")

    if grasa_trans_g_por_100g is not None:
        if grasa_trans_g_por_100g > umbrales[f"exceso_grasas_trans_g_{key_suffix}"]:
            sellos.append("EXCESO GRASAS TRANS")

    if sodio_mg_por_100g is not None:
        if sodio_mg_por_100g > umbrales[f"exceso_sodio_mg_{key_suffix}"]:
            sellos.append("EXCESO SODIO")

    return sellos


def calcular_leyendas_precautorias(
    contiene_edulcorantes: bool = False,
    contiene_cafeina: bool = False,
    sellos: list[str] | None = None,
) -> list[str]:
    """
    Leyendas precautorias obligatorias según NOM-051.
    Se aplican cuando hay sellos + edulcorantes/cafeína.
    """
    leyendas = []

    if contiene_edulcorantes:
        leyendas.append("CONTIENE EDULCORANTES – NO RECOMENDABLE EN NIÑOS")

    if contiene_cafeina:
        leyendas.append("CONTIENE CAFEÍNA – EVITAR EN NIÑOS")

    if sellos and len(sellos) >= 1:
        if contiene_edulcorantes or contiene_cafeina:
            pass  # Ya incluidas arriba
        # Los sellos mismos son las leyendas principales

    return leyendas


def generar_informacion_nutrimental(
    peso_neto_g: Decimal,
    calorias_por_100g: int,
    azucar_g_por_100g: Decimal,
    grasa_saturada_g_por_100g: Decimal,
    grasa_trans_g_por_100g: Decimal | None,
    sodio_mg_por_100g: int,
) -> dict:
    """
    Genera la tabla de información nutrimental por porción y por 100g.
    Porción estándar para pan: 30-40g según tipo.
    """
    porcion_g = Decimal("40")  # Porción estándar panadería
    factor = porcion_g / Decimal("100")

    return {
        "porcion_g": float(porcion_g),
        "por_100g": {
            "calorias_kcal": calorias_por_100g,
            "azucares_g": float(azucar_g_por_100g),
            "grasas_saturadas_g": float(grasa_saturada_g_por_100g),
            "grasas_trans_g": float(grasa_trans_g_por_100g) if grasa_trans_g_por_100g else 0,
            "sodio_mg": sodio_mg_por_100g,
        },
        "por_porcion": {
            "calorias_kcal": round(calorias_por_100g * float(factor)),
            "azucares_g": round(float(azucar_g_por_100g * factor), 1),
            "grasas_saturadas_g": round(float(grasa_saturada_g_por_100g * factor), 1),
            "grasas_trans_g": round(float((grasa_trans_g_por_100g or Decimal("0")) * factor), 1),
            "sodio_mg": round(sodio_mg_por_100g * float(factor)),
        },
        "porciones_por_envase": round(float(peso_neto_g / porcion_g), 1),
    }
