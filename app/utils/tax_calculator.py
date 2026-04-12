"""
Calculadora de impuestos mexicanos.
Funciones puras para cálculos de IVA, ISR, IMSS y subsidio al empleo.
Todas las cantidades usan Decimal para precisión fiscal.
"""

from decimal import Decimal, ROUND_HALF_UP


# ============================================================
# TABLAS ISR Art. 96 LISR - Retención mensual (vigente 2025)
# ============================================================

TABLA_ISR_MENSUAL = [
    # (limite_inferior, limite_superior, cuota_fija, tasa_sobre_excedente)
    (Decimal("0.01"), Decimal("746.04"), Decimal("0.00"), Decimal("0.0192")),
    (Decimal("746.05"), Decimal("6332.05"), Decimal("14.32"), Decimal("0.0640")),
    (Decimal("6332.06"), Decimal("11128.01"), Decimal("371.83"), Decimal("0.1088")),
    (Decimal("11128.02"), Decimal("12935.82"), Decimal("893.63"), Decimal("0.16")),
    (Decimal("12935.83"), Decimal("15487.71"), Decimal("1182.88"), Decimal("0.1792")),
    (Decimal("15487.72"), Decimal("31236.49"), Decimal("1640.18"), Decimal("0.2136")),
    (Decimal("31236.50"), Decimal("49233.00"), Decimal("5004.12"), Decimal("0.2352")),
    (Decimal("49233.01"), Decimal("93993.90"), Decimal("9236.89"), Decimal("0.30")),
    (Decimal("93993.91"), Decimal("125325.20"), Decimal("22665.17"), Decimal("0.32")),
    (Decimal("125325.21"), Decimal("375975.61"), Decimal("32691.18"), Decimal("0.34")),
    (Decimal("375975.62"), Decimal("999999999"), Decimal("117912.32"), Decimal("0.35")),
]

# ============================================================
# TABLA SUBSIDIO AL EMPLEO (mensual)
# ============================================================

TABLA_SUBSIDIO_MENSUAL = [
    # (limite_inferior, limite_superior, subsidio)
    (Decimal("0.01"), Decimal("1768.96"), Decimal("407.02")),
    (Decimal("1768.97"), Decimal("2653.38"), Decimal("406.83")),
    (Decimal("2653.39"), Decimal("3472.84"), Decimal("406.62")),
    (Decimal("3472.85"), Decimal("3537.87"), Decimal("392.77")),
    (Decimal("3537.88"), Decimal("4446.15"), Decimal("382.46")),
    (Decimal("4446.16"), Decimal("4717.18"), Decimal("354.23")),
    (Decimal("4717.19"), Decimal("5335.42"), Decimal("324.87")),
    (Decimal("5335.43"), Decimal("6224.67"), Decimal("294.63")),
    (Decimal("6224.68"), Decimal("7113.90"), Decimal("253.54")),
    (Decimal("7113.91"), Decimal("7382.33"), Decimal("217.61")),
    (Decimal("7382.34"), Decimal("999999999"), Decimal("0.00")),
]

# ============================================================
# TASAS IMSS (cuotas obrero-patronales)
# ============================================================

IMSS_CUOTAS = {
    "enfermedades_maternidad_especie_patron_fija": Decimal("0.204"),  # 20.40% sobre 1 SMGDF
    "enfermedades_maternidad_especie_patron_excedente": Decimal("0.011"),  # 1.10%
    "enfermedades_maternidad_especie_trabajador": Decimal("0.004"),  # 0.40%
    "enfermedades_maternidad_dinero_patron": Decimal("0.007"),  # 0.70%
    "enfermedades_maternidad_dinero_trabajador": Decimal("0.0025"),  # 0.25%
    "enfermedades_maternidad_pensionados_patron": Decimal("0.0105"),  # 1.05%
    "enfermedades_maternidad_pensionados_trabajador": Decimal("0.00375"),  # 0.375%
    "invalidez_vida_patron": Decimal("0.0175"),  # 1.75%
    "invalidez_vida_trabajador": Decimal("0.00625"),  # 0.625%
    "retiro_patron": Decimal("0.02"),  # 2.00%
    "cesantia_vejez_patron": Decimal("0.0315"),  # 3.150%
    "cesantia_vejez_trabajador": Decimal("0.01125"),  # 1.125%
    "guarderias_patron": Decimal("0.01"),  # 1.00%
    "infonavit_patron": Decimal("0.05"),  # 5.00%
}

# ============================================================
# DÍAS DE VACACIONES LFT (reforma 2023)
# ============================================================

DIAS_VACACIONES_LFT = {
    1: 12, 2: 14, 3: 16, 4: 18, 5: 20,
    6: 22, 7: 22, 8: 22, 9: 22, 10: 22,
    11: 24, 12: 24, 13: 24, 14: 24, 15: 24,
    16: 26, 17: 26, 18: 26, 19: 26, 20: 26,
    21: 28, 22: 28, 23: 28, 24: 28, 25: 28,
    26: 30, 27: 30, 28: 30, 29: 30, 30: 30,
}


def _round_currency(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ============================================================
# IVA
# ============================================================

def calcular_iva(base: Decimal, tasa: Decimal) -> Decimal:
    """Calcula IVA sobre una base gravable."""
    return _round_currency(base * tasa)


def desglosar_iva(total_con_iva: Decimal, tasa: Decimal) -> tuple[Decimal, Decimal]:
    """Desglosa un total con IVA incluido en base + IVA."""
    if tasa == Decimal("0"):
        return total_con_iva, Decimal("0")
    base = _round_currency(total_con_iva / (1 + tasa))
    iva = _round_currency(total_con_iva - base)
    return base, iva


# ============================================================
# ISR
# ============================================================

def calcular_isr_mensual(ingreso_gravable_mensual: Decimal) -> Decimal:
    """
    Calcula ISR a retener usando la tabla del Art. 96 LISR.
    Retorna el ISR antes de subsidio.
    """
    if ingreso_gravable_mensual <= Decimal("0"):
        return Decimal("0")

    for li, ls, cuota, tasa in TABLA_ISR_MENSUAL:
        if li <= ingreso_gravable_mensual <= ls:
            excedente = ingreso_gravable_mensual - li
            isr = cuota + _round_currency(excedente * tasa)
            return _round_currency(isr)

    # Si excede la tabla, usar el último rango
    li, _, cuota, tasa = TABLA_ISR_MENSUAL[-1]
    excedente = ingreso_gravable_mensual - li
    return _round_currency(cuota + excedente * tasa)


def calcular_subsidio_empleo(ingreso_gravable_mensual: Decimal) -> Decimal:
    """Calcula subsidio al empleo mensual."""
    if ingreso_gravable_mensual <= Decimal("0"):
        return Decimal("0")

    for li, ls, subsidio in TABLA_SUBSIDIO_MENSUAL:
        if li <= ingreso_gravable_mensual <= ls:
            return subsidio

    return Decimal("0")


def calcular_isr_retencion_neta(ingreso_gravable_mensual: Decimal) -> Decimal:
    """ISR neto a retener = ISR causado - subsidio al empleo."""
    isr = calcular_isr_mensual(ingreso_gravable_mensual)
    subsidio = calcular_subsidio_empleo(ingreso_gravable_mensual)
    neto = isr - subsidio
    return _round_currency(max(neto, Decimal("0")))


# ============================================================
# IMSS
# ============================================================

def calcular_cuota_imss_trabajador(
    sdi: Decimal,
    dias: int,
    uma_diario: Decimal,
) -> Decimal:
    """
    Cuotas IMSS que se retienen al trabajador.
    SDI = Salario Diario Integrado.
    """
    salario_periodo = sdi * dias
    tres_uma = uma_diario * 3

    # Enfermedad y maternidad en especie (excedente de 3 UMA)
    excedente = max(sdi - tres_uma, Decimal("0"))
    em_especie = excedente * dias * IMSS_CUOTAS["enfermedades_maternidad_especie_trabajador"]

    # Enfermedad y maternidad en dinero
    em_dinero = salario_periodo * IMSS_CUOTAS["enfermedades_maternidad_dinero_trabajador"]

    # Pensionados y beneficiarios
    em_pensionados = salario_periodo * IMSS_CUOTAS["enfermedades_maternidad_pensionados_trabajador"]

    # Invalidez y vida
    iv = salario_periodo * IMSS_CUOTAS["invalidez_vida_trabajador"]

    # Cesantía y vejez
    cv = salario_periodo * IMSS_CUOTAS["cesantia_vejez_trabajador"]

    total = em_especie + em_dinero + em_pensionados + iv + cv
    return _round_currency(total)


def calcular_cuota_imss_patron(
    sdi: Decimal,
    dias: int,
    uma_diario: Decimal,
    prima_riesgo: Decimal = Decimal("0.005"),
) -> Decimal:
    """
    Cuotas IMSS patronales.
    prima_riesgo: Prima de Riesgo de Trabajo (clase I mínima = 0.50000%).
    """
    salario_periodo = sdi * dias
    tres_uma = uma_diario * 3

    # Riesgo de trabajo
    rt = salario_periodo * prima_riesgo

    # Enfermedad y maternidad - cuota fija (sobre UMA, no SDI)
    em_fija = uma_diario * dias * IMSS_CUOTAS["enfermedades_maternidad_especie_patron_fija"]

    # Enfermedad y maternidad - excedente
    excedente = max(sdi - tres_uma, Decimal("0"))
    em_excedente = excedente * dias * IMSS_CUOTAS["enfermedades_maternidad_especie_patron_excedente"]

    # Enfermedad y maternidad en dinero
    em_dinero = salario_periodo * IMSS_CUOTAS["enfermedades_maternidad_dinero_patron"]

    # Pensionados
    em_pensionados = salario_periodo * IMSS_CUOTAS["enfermedades_maternidad_pensionados_patron"]

    # Invalidez y vida
    iv = salario_periodo * IMSS_CUOTAS["invalidez_vida_patron"]

    # Retiro
    retiro = salario_periodo * IMSS_CUOTAS["retiro_patron"]

    # Cesantía y vejez
    cv = salario_periodo * IMSS_CUOTAS["cesantia_vejez_patron"]

    # Guarderías
    guarderias = salario_periodo * IMSS_CUOTAS["guarderias_patron"]

    # INFONAVIT
    infonavit = salario_periodo * IMSS_CUOTAS["infonavit_patron"]

    total = (rt + em_fija + em_excedente + em_dinero + em_pensionados +
             iv + retiro + cv + guarderias + infonavit)
    return _round_currency(total)


# ============================================================
# SALARIO DIARIO INTEGRADO (SDI) para IMSS
# ============================================================

def calcular_sdi(
    salario_diario: Decimal,
    antiguedad_anios: int,
    aguinaldo_dias: int = 15,
    prima_vacacional: Decimal = Decimal("0.25"),
) -> Decimal:
    """
    SDI = Salario diario + proporcional de aguinaldo + proporcional de prima vacacional.
    Factor = 1 + (aguinaldo_dias/365) + (dias_vacaciones * prima_vacacional / 365)
    """
    dias_vacaciones = DIAS_VACACIONES_LFT.get(
        min(antiguedad_anios, 30), 12
    )
    if antiguedad_anios < 1:
        dias_vacaciones = 12  # Primer año

    factor_aguinaldo = Decimal(str(aguinaldo_dias)) / Decimal("365")
    factor_prima = Decimal(str(dias_vacaciones)) * prima_vacacional / Decimal("365")
    factor_integracion = Decimal("1") + factor_aguinaldo + factor_prima

    return _round_currency(salario_diario * factor_integracion)


# ============================================================
# VACACIONES Y PRESTACIONES
# ============================================================

def calcular_dias_vacaciones(antiguedad_anios: int) -> int:
    """Días de vacaciones según LFT Art. 76 (reforma 2023)."""
    if antiguedad_anios < 1:
        return 12
    return DIAS_VACACIONES_LFT.get(min(antiguedad_anios, 30), 30)


def calcular_aguinaldo(
    salario_diario: Decimal,
    dias_trabajados_anio: int,
    dias_aguinaldo: int = 15,
) -> Decimal:
    """Aguinaldo proporcional. LFT Art. 87: mínimo 15 días de salario."""
    proporcional = Decimal(str(dias_trabajados_anio)) / Decimal("365")
    return _round_currency(salario_diario * Decimal(str(dias_aguinaldo)) * proporcional)


def calcular_prima_vacacional(
    salario_diario: Decimal,
    dias_vacaciones: int,
    porcentaje: Decimal = Decimal("0.25"),
) -> Decimal:
    """Prima vacacional: 25% del salario de vacaciones. LFT Art. 80."""
    return _round_currency(salario_diario * Decimal(str(dias_vacaciones)) * porcentaje)


def calcular_ptu(
    utilidad_fiscal: Decimal,
    porcentaje: Decimal = Decimal("0.10"),
) -> Decimal:
    """PTU: 10% de la utilidad fiscal. LFT Art. 117."""
    return _round_currency(utilidad_fiscal * porcentaje)


# ============================================================
# HORAS EXTRA (LFT Art. 66-68)
# ============================================================

def calcular_horas_extra(
    salario_diario: Decimal,
    tipo_jornada_horas: int,
    horas_extra: Decimal,
) -> Decimal:
    """
    Primeras 9 hrs extra/semana: se pagan al doble (200%).
    Excedente de 9 hrs/semana: se pagan al triple (300%).
    LFT Art. 67-68.
    """
    salario_hora = salario_diario / Decimal(str(tipo_jornada_horas))

    horas_dobles = min(horas_extra, Decimal("9"))
    horas_triples = max(horas_extra - Decimal("9"), Decimal("0"))

    pago_dobles = horas_dobles * salario_hora * Decimal("2")
    pago_triples = horas_triples * salario_hora * Decimal("3")

    return _round_currency(pago_dobles + pago_triples)
