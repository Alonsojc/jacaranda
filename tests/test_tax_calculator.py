"""Tests para calculadora de impuestos mexicanos."""

from decimal import Decimal
from app.utils.tax_calculator import (
    calcular_iva,
    calcular_isr_mensual,
    calcular_subsidio_empleo,
    calcular_isr_retencion_neta,
    calcular_sdi,
    calcular_dias_vacaciones,
    calcular_aguinaldo,
    calcular_prima_vacacional,
    calcular_horas_extra,
    calcular_cuota_imss_trabajador,
)


class TestIVA:
    def test_iva_16_porciento(self):
        assert calcular_iva(Decimal("100"), Decimal("0.16")) == Decimal("16.00")

    def test_iva_0_porciento(self):
        assert calcular_iva(Decimal("100"), Decimal("0.00")) == Decimal("0.00")

    def test_iva_8_porciento_frontera(self):
        assert calcular_iva(Decimal("100"), Decimal("0.08")) == Decimal("8.00")

    def test_iva_monto_grande(self):
        assert calcular_iva(Decimal("15000"), Decimal("0.16")) == Decimal("2400.00")


class TestISR:
    def test_isr_salario_minimo(self):
        # Salario mínimo mensual (~8,364): debería tener ISR bajo
        isr = calcular_isr_mensual(Decimal("8364"))
        assert isr > Decimal("0")

    def test_isr_ingreso_cero(self):
        assert calcular_isr_mensual(Decimal("0")) == Decimal("0")

    def test_isr_ingreso_alto(self):
        # Ingreso alto debería generar ISR significativo
        isr = calcular_isr_mensual(Decimal("50000"))
        assert isr > Decimal("5000")

    def test_subsidio_empleo_bajo(self):
        subsidio = calcular_subsidio_empleo(Decimal("3000"))
        assert subsidio > Decimal("0")

    def test_subsidio_empleo_alto(self):
        subsidio = calcular_subsidio_empleo(Decimal("30000"))
        assert subsidio == Decimal("0")

    def test_isr_neto_con_subsidio(self):
        neto = calcular_isr_retencion_neta(Decimal("5000"))
        assert neto >= Decimal("0")


class TestSDI:
    def test_sdi_primer_anio(self):
        salario = Decimal("300")
        sdi = calcular_sdi(salario, 1)
        # SDI debe ser mayor que salario diario (incluye factor de integración)
        assert sdi > salario

    def test_sdi_cinco_anios(self):
        salario = Decimal("400")
        sdi_1 = calcular_sdi(salario, 1)
        sdi_5 = calcular_sdi(salario, 5)
        # Más antigüedad = más días vacaciones = SDI más alto
        assert sdi_5 > sdi_1


class TestVacaciones:
    def test_primer_anio(self):
        assert calcular_dias_vacaciones(1) == 12

    def test_segundo_anio(self):
        assert calcular_dias_vacaciones(2) == 14

    def test_quinto_anio(self):
        assert calcular_dias_vacaciones(5) == 20

    def test_diez_anios(self):
        assert calcular_dias_vacaciones(10) == 22

    def test_quince_anios(self):
        assert calcular_dias_vacaciones(15) == 24


class TestAguinaldo:
    def test_anio_completo(self):
        aguinaldo = calcular_aguinaldo(Decimal("300"), 365)
        # 15 días * 300 = 4500
        assert aguinaldo == Decimal("4500.00")

    def test_medio_anio(self):
        aguinaldo = calcular_aguinaldo(Decimal("300"), 182)
        # Proporcional: ~2,241
        assert Decimal("2200") < aguinaldo < Decimal("2300")


class TestPrimaVacacional:
    def test_prima_25_porciento(self):
        prima = calcular_prima_vacacional(Decimal("300"), 12)
        # 300 * 12 * 0.25 = 900
        assert prima == Decimal("900.00")


class TestHorasExtra:
    def test_horas_dobles(self):
        pago = calcular_horas_extra(Decimal("400"), 8, Decimal("4"))
        salario_hora = Decimal("400") / Decimal("8")
        assert pago == (Decimal("4") * salario_hora * Decimal("2")).quantize(Decimal("0.01"))

    def test_horas_triples(self):
        # 12 horas extra: 9 al doble + 3 al triple
        pago = calcular_horas_extra(Decimal("400"), 8, Decimal("12"))
        salario_hora = Decimal("400") / Decimal("8")
        esperado = (
            Decimal("9") * salario_hora * Decimal("2") +
            Decimal("3") * salario_hora * Decimal("3")
        ).quantize(Decimal("0.01"))
        assert pago == esperado


class TestIMSS:
    def test_cuota_trabajador_positiva(self):
        cuota = calcular_cuota_imss_trabajador(
            sdi=Decimal("350"),
            dias=15,
            uma_diario=Decimal("113.14"),
        )
        assert cuota > Decimal("0")
