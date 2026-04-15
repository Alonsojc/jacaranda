"""
Servicio de reportes fiscales SAT: DIOT, declaraciones IVA/ISR,
contabilidad electronica (catalogo y balanza de comprobacion).
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, and_

from app.models.venta import Venta, EstadoVenta
from app.models.inventario import Proveedor
from app.models.compras import OrdenCompra, CuentaPagar, EstadoOrdenCompra
from app.models.contabilidad import (
    CuentaContable, AsientoContable, LineaAsiento, TipoAsiento,
)
from app.models.facturacion import CFDIComprobante

ZERO = Decimal("0")
IVA_TASA = Decimal("0.16")
COEFICIENTE_UTILIDAD_DEFAULT = Decimal("0.20")
TASA_ISR_PROVISIONAL = Decimal("0.30")


# ─── Helpers ─────────────────────────────────────────────────────

def _rango_mes(mes: int, anio: int) -> tuple[datetime, datetime]:
    """Retorna inicio y fin de un mes como datetimes UTC."""
    if mes < 1 or mes > 12:
        raise ValueError(f"Mes invalido: {mes}. Debe estar entre 1 y 12.")
    if anio < 2000:
        raise ValueError(f"Anio invalido: {anio}. Debe ser >= 2000.")
    inicio = datetime(anio, mes, 1, tzinfo=timezone.utc)
    if mes == 12:
        fin = datetime(anio + 1, 1, 1, tzinfo=timezone.utc)
    else:
        fin = datetime(anio, mes + 1, 1, tzinfo=timezone.utc)
    return inicio, fin


def _rango_mes_date(mes: int, anio: int) -> tuple[date, date]:
    """Retorna inicio y fin de un mes como dates."""
    if mes < 1 or mes > 12:
        raise ValueError(f"Mes invalido: {mes}. Debe estar entre 1 y 12.")
    if anio < 2000:
        raise ValueError(f"Anio invalido: {anio}. Debe ser >= 2000.")
    inicio = date(anio, mes, 1)
    if mes == 12:
        fin = date(anio + 1, 1, 1)
    else:
        fin = date(anio, mes + 1, 1)
    return inicio, fin


def _float(val: Decimal | None) -> float:
    """Convierte Decimal/None a float redondeado a 2 decimales."""
    if val is None:
        return 0.0
    return round(float(val), 2)


# ─── DIOT ────────────────────────────────────────────────────────

def generar_diot(db: Session, mes: int, anio: int) -> list[dict]:
    """
    Genera datos para la Declaracion Informativa de Operaciones con Terceros (DIOT).
    Agrupa operaciones de compra por proveedor con desglose de IVA 0% y 16%.
    """
    inicio, fin = _rango_mes(mes, anio)

    # Ordenes de compra recibidas en el periodo, agrupadas por proveedor
    ordenes = (
        db.query(OrdenCompra)
        .filter(
            and_(
                OrdenCompra.estado.in_([
                    EstadoOrdenCompra.RECIBIDA,
                    EstadoOrdenCompra.PARCIAL,
                ]),
                OrdenCompra.creado_en >= inicio,
                OrdenCompra.creado_en < fin,
            )
        )
        .all()
    )

    # Agrupar por proveedor
    proveedores_ops: dict[int, dict] = {}
    for oc in ordenes:
        pid = oc.proveedor_id
        if pid not in proveedores_ops:
            proveedores_ops[pid] = {
                "total_16": ZERO,
                "total_0": ZERO,
                "iva_retenido": ZERO,
            }
        if oc.iva and oc.iva > ZERO:
            # Operacion con IVA 16%
            proveedores_ops[pid]["total_16"] += oc.subtotal or ZERO
        else:
            # Operacion a tasa 0%
            proveedores_ops[pid]["total_0"] += oc.subtotal or ZERO

    # Obtener datos de proveedores
    resultado = []
    for pid, ops in proveedores_ops.items():
        proveedor = db.query(Proveedor).filter(Proveedor.id == pid).first()
        if not proveedor:
            continue
        resultado.append({
            "rfc": proveedor.rfc or "XAXX010101000",
            "razon_social": proveedor.nombre,
            "tipo_operacion": "03",  # 03 = Provision de bienes y servicios
            "total_16": _float(ops["total_16"]),
            "total_0": _float(ops["total_0"]),
            "iva_retenido": _float(ops["iva_retenido"]),
        })

    return resultado


# ─── Declaracion IVA mensual ─────────────────────────────────────

def declaracion_iva_mensual(db: Session, mes: int, anio: int) -> dict:
    """
    Calcula la declaracion mensual de IVA.
    IVA causado = IVA cobrado en ventas (tasa 16%).
    IVA acreditable = IVA pagado en compras (tasa 16%).
    """
    inicio, fin = _rango_mes(mes, anio)

    # IVA causado: suma del IVA 16% de ventas completadas en el periodo
    iva_causado = (
        db.query(func.coalesce(func.sum(Venta.iva_16), 0))
        .filter(
            and_(
                Venta.estado == EstadoVenta.COMPLETADA,
                Venta.fecha >= inicio,
                Venta.fecha < fin,
            )
        )
        .scalar()
    )
    iva_causado = Decimal(str(iva_causado))

    # Ventas gravadas al 16% (base)
    ventas_gravadas_16 = (
        db.query(func.coalesce(func.sum(Venta.subtotal), 0))
        .filter(
            and_(
                Venta.estado == EstadoVenta.COMPLETADA,
                Venta.fecha >= inicio,
                Venta.fecha < fin,
                Venta.iva_16 > 0,
            )
        )
        .scalar()
    )
    ventas_gravadas_16 = Decimal(str(ventas_gravadas_16))

    # Ventas a tasa 0%
    ventas_tasa_0 = (
        db.query(func.coalesce(func.sum(Venta.subtotal), 0))
        .filter(
            and_(
                Venta.estado == EstadoVenta.COMPLETADA,
                Venta.fecha >= inicio,
                Venta.fecha < fin,
                Venta.iva_16 == 0,
            )
        )
        .scalar()
    )
    ventas_tasa_0 = Decimal(str(ventas_tasa_0))

    # IVA acreditable: IVA de ordenes de compra recibidas en el periodo
    iva_acreditable = (
        db.query(func.coalesce(func.sum(OrdenCompra.iva), 0))
        .filter(
            and_(
                OrdenCompra.estado.in_([
                    EstadoOrdenCompra.RECIBIDA,
                    EstadoOrdenCompra.PARCIAL,
                ]),
                OrdenCompra.creado_en >= inicio,
                OrdenCompra.creado_en < fin,
            )
        )
        .scalar()
    )
    iva_acreditable = Decimal(str(iva_acreditable))

    # Determinacion
    diferencia = iva_causado - iva_acreditable
    iva_a_pagar = max(diferencia, ZERO)
    saldo_a_favor = max(-diferencia, ZERO)

    return {
        "mes": mes,
        "anio": anio,
        "ventas_gravadas_16": _float(ventas_gravadas_16),
        "ventas_tasa_0": _float(ventas_tasa_0),
        "iva_causado": _float(iva_causado),
        "iva_acreditable": _float(iva_acreditable),
        "iva_a_pagar": _float(iva_a_pagar),
        "saldo_a_favor": _float(saldo_a_favor),
    }


# ─── Declaracion ISR provisional ────────────────────────────────

def declaracion_isr_provisional(
    db: Session,
    mes: int,
    anio: int,
    coeficiente_utilidad: Decimal | None = None,
) -> dict:
    """
    Calcula el pago provisional de ISR del mes.
    Ingresos acumulados = ventas del 1 de enero al fin del mes.
    Coeficiente de utilidad configurable (default 0.20).
    """
    if mes < 1 or mes > 12:
        raise ValueError(f"Mes invalido: {mes}. Debe estar entre 1 y 12.")
    if anio < 2000:
        raise ValueError(f"Anio invalido: {anio}. Debe ser >= 2000.")

    coef = coeficiente_utilidad or COEFICIENTE_UTILIDAD_DEFAULT

    # Ingresos acumulados: del 1 de enero al fin del mes actual
    inicio_anio = datetime(anio, 1, 1, tzinfo=timezone.utc)
    if mes == 12:
        fin_mes = datetime(anio + 1, 1, 1, tzinfo=timezone.utc)
    else:
        fin_mes = datetime(anio, mes + 1, 1, tzinfo=timezone.utc)

    ingresos_acumulados = (
        db.query(func.coalesce(func.sum(Venta.total - Venta.iva_16), 0))
        .filter(
            and_(
                Venta.estado == EstadoVenta.COMPLETADA,
                Venta.fecha >= inicio_anio,
                Venta.fecha < fin_mes,
            )
        )
        .scalar()
    )
    ingresos_acumulados = Decimal(str(ingresos_acumulados))

    # Utilidad fiscal estimada
    utilidad_fiscal = ingresos_acumulados * coef

    # ISR causado acumulado (tasa provisional 30%)
    isr_causado = utilidad_fiscal * TASA_ISR_PROVISIONAL

    # Pagos provisionales anteriores: ISR de meses 1..mes-1
    pagos_provisionales_anteriores = ZERO
    for m in range(1, mes):
        inicio_m = datetime(anio, m, 1, tzinfo=timezone.utc)
        if m == 12:
            fin_m = datetime(anio + 1, 1, 1, tzinfo=timezone.utc)
        else:
            fin_m = datetime(anio, m + 1, 1, tzinfo=timezone.utc)

        ingresos_m = (
            db.query(func.coalesce(func.sum(Venta.total - Venta.iva_16), 0))
            .filter(
                and_(
                    Venta.estado == EstadoVenta.COMPLETADA,
                    Venta.fecha >= inicio_m,
                    Venta.fecha < fin_m,
                )
            )
            .scalar()
        )
        ingresos_m = Decimal(str(ingresos_m))
        pagos_provisionales_anteriores += ingresos_m * coef * TASA_ISR_PROVISIONAL

    # ISR a pagar en este mes
    isr_a_pagar = max(isr_causado - pagos_provisionales_anteriores, ZERO)

    return {
        "mes": mes,
        "anio": anio,
        "ingresos_acumulados": _float(ingresos_acumulados),
        "coeficiente_utilidad": _float(coef),
        "utilidad_fiscal": _float(utilidad_fiscal),
        "tasa_isr": _float(TASA_ISR_PROVISIONAL),
        "isr_causado": _float(isr_causado),
        "pagos_provisionales_anteriores": _float(pagos_provisionales_anteriores),
        "isr_a_pagar": _float(isr_a_pagar),
    }


# ─── Contabilidad electronica: catalogo ─────────────────────────

def contabilidad_electronica_catalogo(db: Session) -> list[dict]:
    """
    Genera el catalogo de cuentas en formato SAT para contabilidad electronica.
    Incluye todas las cuentas activas ordenadas por codigo.
    """
    cuentas = (
        db.query(CuentaContable)
        .filter(CuentaContable.activa.is_(True))
        .order_by(CuentaContable.codigo)
        .all()
    )

    resultado = []
    for c in cuentas:
        resultado.append({
            "codigo": c.codigo,
            "nombre": c.nombre,
            "nivel": c.nivel,
            "naturaleza": c.naturaleza.value,
            "tipo": c.tipo.value,
        })

    return resultado


# ─── Contabilidad electronica: balanza de comprobacion ───────────

def contabilidad_electronica_balanza(db: Session, mes: int, anio: int) -> list[dict]:
    """
    Genera la balanza de comprobacion mensual en formato SAT.
    Para cada cuenta calcula: saldo_inicial, debe, haber, saldo_final.
    Saldo inicial = movimientos acumulados antes del periodo.
    Debe/Haber = movimientos del periodo.
    Saldo final = saldo_inicial + debe - haber (deudora) o saldo_inicial - debe + haber (acreedora).
    """
    inicio_date, fin_date = _rango_mes_date(mes, anio)

    cuentas = (
        db.query(CuentaContable)
        .filter(CuentaContable.activa.is_(True))
        .order_by(CuentaContable.codigo)
        .all()
    )

    resultado = []
    for cuenta in cuentas:
        # Saldo inicial: acumulado de todos los asientos anteriores al periodo
        saldo_inicial_row = (
            db.query(
                func.coalesce(func.sum(LineaAsiento.debe), 0).label("total_debe"),
                func.coalesce(func.sum(LineaAsiento.haber), 0).label("total_haber"),
            )
            .join(AsientoContable, AsientoContable.id == LineaAsiento.asiento_id)
            .filter(
                and_(
                    LineaAsiento.cuenta_id == cuenta.id,
                    AsientoContable.fecha < inicio_date,
                )
            )
            .first()
        )

        debe_anterior = Decimal(str(saldo_inicial_row[0])) if saldo_inicial_row else ZERO
        haber_anterior = Decimal(str(saldo_inicial_row[1])) if saldo_inicial_row else ZERO

        if cuenta.naturaleza.value == "deudora":
            saldo_inicial = debe_anterior - haber_anterior
        else:
            saldo_inicial = haber_anterior - debe_anterior

        # Movimientos del periodo
        movs_periodo = (
            db.query(
                func.coalesce(func.sum(LineaAsiento.debe), 0).label("total_debe"),
                func.coalesce(func.sum(LineaAsiento.haber), 0).label("total_haber"),
            )
            .join(AsientoContable, AsientoContable.id == LineaAsiento.asiento_id)
            .filter(
                and_(
                    LineaAsiento.cuenta_id == cuenta.id,
                    AsientoContable.fecha >= inicio_date,
                    AsientoContable.fecha < fin_date,
                )
            )
            .first()
        )

        debe_periodo = Decimal(str(movs_periodo[0])) if movs_periodo else ZERO
        haber_periodo = Decimal(str(movs_periodo[1])) if movs_periodo else ZERO

        # Saldo final
        if cuenta.naturaleza.value == "deudora":
            saldo_final = saldo_inicial + debe_periodo - haber_periodo
        else:
            saldo_final = saldo_inicial - debe_periodo + haber_periodo

        # Solo incluir cuentas con algun movimiento o saldo
        if (
            saldo_inicial != ZERO
            or debe_periodo != ZERO
            or haber_periodo != ZERO
            or saldo_final != ZERO
        ):
            resultado.append({
                "cuenta_codigo": cuenta.codigo,
                "cuenta_nombre": cuenta.nombre,
                "saldo_inicial": _float(saldo_inicial),
                "debe": _float(debe_periodo),
                "haber": _float(haber_periodo),
                "saldo_final": _float(saldo_final),
            })

    return resultado


# ─── Reporte fiscal completo ─────────────────────────────────────

def generar_reporte_fiscal_completo(db: Session, mes: int, anio: int) -> dict:
    """
    Genera un reporte fiscal integral que combina todos los reportes SAT
    del periodo: DIOT, declaracion IVA, ISR provisional, catalogo y balanza.
    """
    return {
        "mes": mes,
        "anio": anio,
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "diot": generar_diot(db, mes, anio),
        "iva_mensual": declaracion_iva_mensual(db, mes, anio),
        "isr_provisional": declaracion_isr_provisional(db, mes, anio),
        "contabilidad_electronica": {
            "catalogo": contabilidad_electronica_catalogo(db),
            "balanza": contabilidad_electronica_balanza(db, mes, anio),
        },
    }
