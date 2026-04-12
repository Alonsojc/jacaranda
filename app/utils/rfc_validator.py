"""
Validador de RFC mexicano.
Valida formato y dígito verificador para personas físicas y morales.
"""

import re

# Tabla de valores para cálculo del dígito verificador
_RFC_CHAR_VALUES = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
    "7": 7, "8": 8, "9": 9, "A": 10, "B": 11, "C": 12, "D": 13,
    "E": 14, "F": 15, "G": 16, "H": 17, "I": 18, "J": 19, "K": 20,
    "L": 21, "M": 22, "N": 23, "&": 24, "O": 25, "P": 26, "Q": 27,
    "R": 28, "S": 29, "T": 30, "U": 31, "V": 32, "W": 33, "X": 34,
    "Y": 35, "Z": 36, " ": 37, "Ñ": 38,
}

_DIGITO_VERIFICADOR = "0123456789A"

# RFCs genéricos del SAT
RFCS_GENERICOS = {"XAXX010101000", "XEXX010101000"}


def validar_formato_rfc(rfc: str) -> tuple[bool, str]:
    """
    Valida el formato de un RFC mexicano.
    Retorna (es_valido, mensaje).
    """
    rfc = rfc.upper().strip()

    if rfc in RFCS_GENERICOS:
        return True, "RFC genérico válido"

    # Persona moral: 3 letras + 6 dígitos fecha + 3 homoclave = 12
    patron_moral = r"^[A-ZÑ&]{3}\d{6}[A-Z0-9]{3}$"
    # Persona física: 4 letras + 6 dígitos fecha + 3 homoclave = 13
    patron_fisica = r"^[A-ZÑ&]{4}\d{6}[A-Z0-9]{3}$"

    if len(rfc) == 12:
        if not re.match(patron_moral, rfc):
            return False, "Formato inválido para persona moral"
        tipo = "moral"
    elif len(rfc) == 13:
        if not re.match(patron_fisica, rfc):
            return False, "Formato inválido para persona física"
        tipo = "fisica"
    else:
        return False, "RFC debe tener 12 (moral) o 13 (física) caracteres"

    # Validar fecha dentro del RFC
    if tipo == "moral":
        fecha_str = rfc[3:9]
    else:
        fecha_str = rfc[4:10]

    anio = int(fecha_str[0:2])
    mes = int(fecha_str[2:4])
    dia = int(fecha_str[4:6])

    if not (1 <= mes <= 12):
        return False, f"Mes inválido en RFC: {mes}"
    if not (1 <= dia <= 31):
        return False, f"Día inválido en RFC: {dia}"

    return True, f"RFC válido ({tipo})"


def calcular_digito_verificador(rfc_sin_digito: str) -> str:
    """Calcula el dígito verificador del RFC."""
    rfc_sin_digito = rfc_sin_digito.upper()

    # Para persona moral (11 chars), agregar espacio al inicio
    if len(rfc_sin_digito) == 11:
        rfc_sin_digito = " " + rfc_sin_digito

    if len(rfc_sin_digito) != 12:
        raise ValueError("RFC sin dígito debe tener 11 o 12 caracteres")

    suma = 0
    for i, char in enumerate(rfc_sin_digito):
        valor = _RFC_CHAR_VALUES.get(char, 0)
        suma += valor * (13 - i)

    residuo = suma % 11
    if residuo == 0:
        return "0"
    else:
        return _DIGITO_VERIFICADOR[11 - residuo]


def validar_rfc_completo(rfc: str) -> tuple[bool, str]:
    """Validación completa: formato + dígito verificador."""
    rfc = rfc.upper().strip()

    if rfc in RFCS_GENERICOS:
        return True, "RFC genérico válido"

    valido, mensaje = validar_formato_rfc(rfc)
    if not valido:
        return False, mensaje

    rfc_sin_digito = rfc[:-1]
    digito_esperado = calcular_digito_verificador(rfc_sin_digito)

    if rfc[-1] != digito_esperado:
        return False, f"Dígito verificador incorrecto (esperado: {digito_esperado})"

    return True, "RFC válido con dígito verificador correcto"
