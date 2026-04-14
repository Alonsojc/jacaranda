"""
Servicio de contabilidad: catálogo de cuentas, pólizas de diario,
balance general, estado de resultados y conciliación bancaria.
"""

from decimal import Decimal
from datetime import date, datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.models.contabilidad import (
    CuentaContable, AsientoContable, LineaAsiento, MovimientoBancario,
    TipoCuenta, NaturalezaCuenta, TipoAsiento,
)
from app.models.venta import Venta, DetalleVenta, EstadoVenta
from app.models.inventario import (
    Ingrediente, Producto, MovimientoInventario, TipoMovimiento,
)
from app.models.gasto_fijo import GastoFijo
from app.models.empleado import RegistroNomina

ZERO = Decimal("0")


# ─── Catálogo de cuentas ──────────────────────────────────────────

_CATALOGO_DEFAULT = [
    # (codigo, nombre, tipo, naturaleza, nivel)
    ("1000", "Activo", TipoCuenta.ACTIVO, NaturalezaCuenta.DEUDORA, 1),
    ("1100", "Activo circulante", TipoCuenta.ACTIVO, NaturalezaCuenta.DEUDORA, 2),
    ("1101", "Caja", TipoCuenta.ACTIVO, NaturalezaCuenta.DEUDORA, 3),
    ("1102", "Bancos", TipoCuenta.ACTIVO, NaturalezaCuenta.DEUDORA, 3),
    ("1103", "Clientes", TipoCuenta.ACTIVO, NaturalezaCuenta.DEUDORA, 3),
    ("1104", "Inventario materia prima", TipoCuenta.ACTIVO, NaturalezaCuenta.DEUDORA, 3),
    ("1105", "Inventario producto terminado", TipoCuenta.ACTIVO, NaturalezaCuenta.DEUDORA, 3),
    ("1106", "IVA acreditable", TipoCuenta.ACTIVO, NaturalezaCuenta.DEUDORA, 3),
    ("1200", "Activo fijo", TipoCuenta.ACTIVO, NaturalezaCuenta.DEUDORA, 2),
    ("1201", "Equipo de panadería", TipoCuenta.ACTIVO, NaturalezaCuenta.DEUDORA, 3),
    ("1202", "Mobiliario y equipo", TipoCuenta.ACTIVO, NaturalezaCuenta.DEUDORA, 3),
    ("1203", "Vehículos", TipoCuenta.ACTIVO, NaturalezaCuenta.DEUDORA, 3),
    ("2000", "Pasivo", TipoCuenta.PASIVO, NaturalezaCuenta.ACREEDORA, 1),
    ("2100", "Pasivo circulante", TipoCuenta.PASIVO, NaturalezaCuenta.ACREEDORA, 2),
    ("2101", "Proveedores", TipoCuenta.PASIVO, NaturalezaCuenta.ACREEDORA, 3),
    ("2102", "Impuestos por pagar", TipoCuenta.PASIVO, NaturalezaCuenta.ACREEDORA, 3),
    ("2103", "IVA por pagar", TipoCuenta.PASIVO, NaturalezaCuenta.ACREEDORA, 3),
    ("2104", "ISR por pagar", TipoCuenta.PASIVO, NaturalezaCuenta.ACREEDORA, 3),
    ("2105", "IMSS por pagar", TipoCuenta.PASIVO, NaturalezaCuenta.ACREEDORA, 3),
    ("2106", "Nómina por pagar", TipoCuenta.PASIVO, NaturalezaCuenta.ACREEDORA, 3),
    ("3000", "Capital", TipoCuenta.CAPITAL, NaturalezaCuenta.ACREEDORA, 1),
    ("3100", "Capital contable", TipoCuenta.CAPITAL, NaturalezaCuenta.ACREEDORA, 2),
    ("3101", "Capital social", TipoCuenta.CAPITAL, NaturalezaCuenta.ACREEDORA, 3),
    ("3102", "Utilidades acumuladas", TipoCuenta.CAPITAL, NaturalezaCuenta.ACREEDORA, 3),
    ("3103", "Utilidad del ejercicio", TipoCuenta.CAPITAL, NaturalezaCuenta.ACREEDORA, 3),
    ("4000", "Ingresos", TipoCuenta.INGRESO, NaturalezaCuenta.ACREEDORA, 1),
    ("4100", "Ingresos operativos", TipoCuenta.INGRESO, NaturalezaCuenta.ACREEDORA, 2),
    ("4101", "Ventas de mostrador", TipoCuenta.INGRESO, NaturalezaCuenta.ACREEDORA, 3),
    ("4102", "Ventas por pedido", TipoCuenta.INGRESO, NaturalezaCuenta.ACREEDORA, 3),
    ("4103", "Ventas WhatsApp", TipoCuenta.INGRESO, NaturalezaCuenta.ACREEDORA, 3),
    ("5000", "Costos", TipoCuenta.COSTO, NaturalezaCuenta.DEUDORA, 1),
    ("5100", "Costo de ventas", TipoCuenta.COSTO, NaturalezaCuenta.DEUDORA, 2),
    ("5101", "Materia prima consumida", TipoCuenta.COSTO, NaturalezaCuenta.DEUDORA, 3),
    ("5102", "Mano de obra directa", TipoCuenta.COSTO, NaturalezaCuenta.DEUDORA, 3),
    ("5103", "Mermas y desperdicios", TipoCuenta.COSTO, NaturalezaCuenta.DEUDORA, 3),
    ("6000", "Gastos", TipoCuenta.GASTO, NaturalezaCuenta.DEUDORA, 1),
    ("6100", "Gastos de operación", TipoCuenta.GASTO, NaturalezaCuenta.DEUDORA, 2),
    ("6101", "Renta", TipoCuenta.GASTO, NaturalezaCuenta.DEUDORA, 3),
    ("6102", "Servicios (luz, agua, gas)", TipoCuenta.GASTO, NaturalezaCuenta.DEUDORA, 3),
    ("6103", "Nómina administrativa", TipoCuenta.GASTO, NaturalezaCuenta.DEUDORA, 3),
    ("6104", "Impuestos y derechos", TipoCuenta.GASTO, NaturalezaCuenta.DEUDORA, 3),
    ("6105", "Mantenimiento", TipoCuenta.GASTO, NaturalezaCuenta.DEUDORA, 3),
    ("6106", "Publicidad", TipoCuenta.GASTO, NaturalezaCuenta.DEUDORA, 3),
    ("6107", "Depreciación", TipoCuenta.GASTO, NaturalezaCuenta.DEUDORA, 3),
]


def catalogo_cuentas(db: Session) -> list[dict]:
    """Retorna catálogo de cuentas agrupado por tipo."""
    cuentas = db.query(CuentaContable).filter(
        CuentaContable.activa.is_(True)
    ).order_by(CuentaContable.codigo).all()

    resultado = {}
    for c in cuentas:
        tipo = c.tipo.value
        if tipo not in resultado:
            resultado[tipo] = []
        resultado[tipo].append({
            "id": c.id,
            "codigo": c.codigo,
            "nombre": c.nombre,
            "tipo": tipo,
            "naturaleza": c.naturaleza.value,
            "nivel": c.nivel,
            "padre_id": c.padre_id,
        })
    return resultado


def crear_cuenta(db: Session, data: dict) -> CuentaContable:
    """Crea una cuenta contable."""
    cuenta = CuentaContable(
        codigo=data["codigo"],
        nombre=data["nombre"],
        tipo=TipoCuenta(data["tipo"]),
        naturaleza=NaturalezaCuenta(data["naturaleza"]),
        nivel=data.get("nivel", 3),
        padre_id=data.get("padre_id"),
    )
    db.add(cuenta)
    db.commit()
    db.refresh(cuenta)
    return cuenta


def seedear_catalogo(db: Session) -> int:
    """Siembra catálogo de cuentas por defecto si está vacío. Retorna cuentas creadas."""
    existentes = db.query(CuentaContable).count()
    if existentes > 0:
        return 0

    # Build parent mapping
    cuentas_map = {}
    for codigo, nombre, tipo, naturaleza, nivel in _CATALOGO_DEFAULT:
        padre_id = None
        if nivel == 2:
            padre_code = codigo[:1] + "000"
            padre_id = cuentas_map.get(padre_code)
        elif nivel == 3:
            padre_code = codigo[:2] + "00"
            padre_id = cuentas_map.get(padre_code)

        cuenta = CuentaContable(
            codigo=codigo, nombre=nombre, tipo=tipo,
            naturaleza=naturaleza, nivel=nivel, padre_id=padre_id,
        )
        db.add(cuenta)
        db.flush()
        cuentas_map[codigo] = cuenta.id

    db.commit()
    return len(_CATALOGO_DEFAULT)


# ─── Asientos contables (pólizas) ────────────────────────────────

def crear_asiento(
    db: Session,
    fecha: date,
    concepto: str,
    tipo: str,
    lineas: list[dict],
    usuario_id: int,
    referencia_id: int | None = None,
    referencia_tipo: str | None = None,
) -> AsientoContable:
    """
    Crea asiento contable con validación de partida doble.
    lineas: [{cuenta_codigo, debe, haber, concepto}]
    """
    total_debe = sum(Decimal(str(l.get("debe", 0))) for l in lineas)
    total_haber = sum(Decimal(str(l.get("haber", 0))) for l in lineas)
    if total_debe != total_haber:
        raise ValueError(
            f"Asiento descuadrado: debe={total_debe}, haber={total_haber}"
        )

    # Generate sequential number
    prefijo = {"ingreso": "I", "egreso": "E", "nomina": "N", "ajuste": "A"}.get(tipo, "P")
    ultimo = db.query(AsientoContable).filter(
        AsientoContable.numero.like(f"{prefijo}-%")
    ).order_by(AsientoContable.id.desc()).first()
    if ultimo:
        num = int(ultimo.numero.split("-")[1]) + 1
    else:
        num = 1
    numero = f"{prefijo}-{num:04d}"

    asiento = AsientoContable(
        numero=numero, fecha=fecha, concepto=concepto,
        tipo=TipoAsiento(tipo), usuario_id=usuario_id,
        referencia_id=referencia_id, referencia_tipo=referencia_tipo,
    )
    db.add(asiento)
    db.flush()

    for l in lineas:
        cuenta = db.query(CuentaContable).filter(
            CuentaContable.codigo == l["cuenta_codigo"]
        ).first()
        if not cuenta:
            raise ValueError(f"Cuenta {l['cuenta_codigo']} no encontrada")
        db.add(LineaAsiento(
            asiento_id=asiento.id,
            cuenta_id=cuenta.id,
            debe=Decimal(str(l.get("debe", 0))),
            haber=Decimal(str(l.get("haber", 0))),
            concepto=l.get("concepto"),
        ))

    db.commit()
    db.refresh(asiento)
    return asiento


def libro_diario(db: Session, fecha_inicio: date, fecha_fin: date) -> list[dict]:
    """Libro diario: asientos con líneas en un periodo."""
    asientos = db.query(AsientoContable).filter(
        and_(
            AsientoContable.fecha >= fecha_inicio,
            AsientoContable.fecha <= fecha_fin,
        )
    ).order_by(AsientoContable.fecha, AsientoContable.numero).all()

    resultado = []
    for a in asientos:
        lineas = []
        for l in a.lineas:
            lineas.append({
                "cuenta_codigo": l.cuenta.codigo,
                "cuenta_nombre": l.cuenta.nombre,
                "debe": float(l.debe),
                "haber": float(l.haber),
                "concepto": l.concepto,
            })
        resultado.append({
            "id": a.id,
            "numero": a.numero,
            "fecha": a.fecha.isoformat(),
            "concepto": a.concepto,
            "tipo": a.tipo.value,
            "aprobado": a.aprobado,
            "lineas": lineas,
            "total_debe": sum(l["debe"] for l in lineas),
            "total_haber": sum(l["haber"] for l in lineas),
        })
    return resultado


# ─── Balance general ──────────────────────────────────────────────

def balance_general(db: Session, fecha_corte: date | None = None) -> dict:
    """
    Balance general a una fecha de corte.
    Combina saldos de pólizas contables + estimaciones de datos operativos.
    """
    corte = fecha_corte or date.today()
    corte_dt = datetime.combine(corte, datetime.max.time(), tzinfo=timezone.utc)

    # 1. Saldos desde pólizas contables
    saldos_polizas = _saldos_cuentas(db, corte)

    # 2. Estimaciones directas de datos operativos
    # Caja: ventas en efectivo no conciliadas
    efectivo = db.query(func.coalesce(func.sum(Venta.total), 0)).filter(
        and_(Venta.estado == EstadoVenta.COMPLETADA,
             Venta.metodo_pago == "01", Venta.fecha <= corte_dt)
    ).scalar()

    # Inventario materia prima
    inv_mp = ZERO
    ingredientes = db.query(Ingrediente).filter(Ingrediente.activo.is_(True)).all()
    for ing in ingredientes:
        inv_mp += (ing.stock_actual or ZERO) * (ing.costo_unitario or ZERO)

    # Inventario producto terminado
    inv_pt = ZERO
    productos = db.query(Producto).filter(Producto.activo.is_(True)).all()
    for p in productos:
        inv_pt += (p.stock_actual or ZERO) * (p.costo_produccion or ZERO)

    # IVA por pagar (cobrado en ventas)
    iva_cobrado = db.query(func.coalesce(func.sum(Venta.iva_16), 0)).filter(
        and_(Venta.estado == EstadoVenta.COMPLETADA, Venta.fecha <= corte_dt)
    ).scalar()

    # Build balance
    activos = [
        {"cuenta": "1101 - Caja", "saldo": float(efectivo)},
        {"cuenta": "1102 - Bancos", "saldo": float(saldos_polizas.get("1102", ZERO))},
        {"cuenta": "1104 - Inventario materia prima", "saldo": float(inv_mp)},
        {"cuenta": "1105 - Inventario producto terminado", "saldo": float(inv_pt)},
    ]
    # Add any poliza-based activo accounts not already listed
    for codigo, saldo in saldos_polizas.items():
        if codigo.startswith("1") and codigo not in ("1101", "1102", "1104", "1105") and saldo != ZERO:
            cuenta = db.query(CuentaContable).filter(CuentaContable.codigo == codigo).first()
            nombre = cuenta.nombre if cuenta else codigo
            activos.append({"cuenta": f"{codigo} - {nombre}", "saldo": float(saldo)})

    pasivos = [
        {"cuenta": "2103 - IVA por pagar", "saldo": float(iva_cobrado)},
    ]
    for codigo, saldo in saldos_polizas.items():
        if codigo.startswith("2") and codigo != "2103" and saldo != ZERO:
            cuenta = db.query(CuentaContable).filter(CuentaContable.codigo == codigo).first()
            nombre = cuenta.nombre if cuenta else codigo
            pasivos.append({"cuenta": f"{codigo} - {nombre}", "saldo": float(saldo)})

    capital_items = []
    for codigo, saldo in saldos_polizas.items():
        if codigo.startswith("3") and saldo != ZERO:
            cuenta = db.query(CuentaContable).filter(CuentaContable.codigo == codigo).first()
            nombre = cuenta.nombre if cuenta else codigo
            capital_items.append({"cuenta": f"{codigo} - {nombre}", "saldo": float(saldo)})

    total_activos = sum(a["saldo"] for a in activos)
    total_pasivos = sum(p["saldo"] for p in pasivos)
    total_capital = sum(c["saldo"] for c in capital_items)

    # Utilidad implícita = Activos - Pasivos - Capital registrado
    utilidad_implicita = total_activos - total_pasivos - total_capital
    if abs(utilidad_implicita) > 0.01:
        capital_items.append({
            "cuenta": "3103 - Utilidad del ejercicio",
            "saldo": round(utilidad_implicita, 2),
        })
        total_capital += utilidad_implicita

    return {
        "fecha_corte": corte.isoformat(),
        "activos": activos,
        "pasivos": pasivos,
        "capital": capital_items,
        "total_activos": round(total_activos, 2),
        "total_pasivos": round(total_pasivos, 2),
        "total_capital": round(total_capital, 2),
        "cuadra": abs(total_activos - total_pasivos - total_capital) < 0.01,
    }


def _saldos_cuentas(db: Session, fecha_corte: date) -> dict[str, Decimal]:
    """Calcula saldos acumulados por cuenta desde pólizas."""
    lineas = db.query(
        CuentaContable.codigo,
        CuentaContable.naturaleza,
        func.coalesce(func.sum(LineaAsiento.debe), 0).label("total_debe"),
        func.coalesce(func.sum(LineaAsiento.haber), 0).label("total_haber"),
    ).join(
        LineaAsiento, LineaAsiento.cuenta_id == CuentaContable.id
    ).join(
        AsientoContable, AsientoContable.id == LineaAsiento.asiento_id
    ).filter(
        AsientoContable.fecha <= fecha_corte
    ).group_by(
        CuentaContable.codigo, CuentaContable.naturaleza
    ).all()

    saldos = {}
    for codigo, naturaleza, total_debe, total_haber in lineas:
        if naturaleza == NaturalezaCuenta.DEUDORA:
            saldos[codigo] = Decimal(str(total_debe)) - Decimal(str(total_haber))
        else:
            saldos[codigo] = Decimal(str(total_haber)) - Decimal(str(total_debe))
    return saldos


# ─── Estado de resultados ─────────────────────────────────────────

def estado_resultados(db: Session, fecha_inicio: date, fecha_fin: date) -> dict:
    """Estado de resultados (P&L) para un periodo."""
    inicio_dt = datetime.combine(fecha_inicio, datetime.min.time(), tzinfo=timezone.utc)
    fin_dt = datetime.combine(fecha_fin, datetime.max.time(), tzinfo=timezone.utc)

    # Ingresos: ventas completadas en el periodo
    ventas = db.query(Venta).filter(
        and_(Venta.estado == EstadoVenta.COMPLETADA,
             Venta.fecha >= inicio_dt, Venta.fecha <= fin_dt)
    ).all()
    ingresos_brutos = sum((v.total or ZERO) for v in ventas)
    iva_cobrado = sum((v.iva_16 or ZERO) for v in ventas)
    ingresos_netos = ingresos_brutos - iva_cobrado

    # Costo de ventas: sum(cantidad * costo_produccion) de los detalles
    costo_ventas = ZERO
    for v in ventas:
        for d in v.detalles:
            producto = db.query(Producto).filter(Producto.id == d.producto_id).first()
            if producto and producto.costo_produccion:
                costo_ventas += d.cantidad * producto.costo_produccion

    utilidad_bruta = ingresos_netos - costo_ventas

    # Gastos de operación
    gastos_fijos = db.query(GastoFijo).filter(GastoFijo.activo.is_(True)).all()
    dias_periodo = max((fecha_fin - fecha_inicio).days, 1)
    gastos_desglose = {}
    total_gastos_op = ZERO
    for g in gastos_fijos:
        monto_periodo = _prorratear_gasto(g.monto, g.periodicidad, dias_periodo)
        gastos_desglose[g.concepto] = float(monto_periodo)
        total_gastos_op += monto_periodo

    # Nómina en el periodo
    nominas = db.query(RegistroNomina).filter(
        and_(RegistroNomina.periodo_inicio >= fecha_inicio,
             RegistroNomina.periodo_fin <= fecha_fin)
    ).all()
    total_nomina = sum((n.neto_a_pagar or ZERO) for n in nominas)
    if total_nomina > 0:
        gastos_desglose["Nómina"] = float(total_nomina)
        total_gastos_op += total_nomina

    utilidad_operacion = utilidad_bruta - total_gastos_op

    # Impuestos estimados (ISR provisional ~30% sobre utilidad positiva)
    isr_estimado = max(utilidad_operacion * Decimal("0.30"), ZERO)
    utilidad_neta = utilidad_operacion - isr_estimado

    # Mermas en el periodo
    mermas = db.query(func.coalesce(
        func.sum(MovimientoInventario.cantidad * MovimientoInventario.costo_unitario), 0
    )).filter(
        and_(MovimientoInventario.tipo == TipoMovimiento.SALIDA_MERMA,
             MovimientoInventario.fecha >= inicio_dt,
             MovimientoInventario.fecha <= fin_dt)
    ).scalar()

    return {
        "periodo": {"inicio": fecha_inicio.isoformat(), "fin": fecha_fin.isoformat()},
        "ingresos_brutos": float(ingresos_brutos),
        "iva_cobrado": float(iva_cobrado),
        "ingresos_netos": float(ingresos_netos),
        "costo_ventas": float(costo_ventas),
        "utilidad_bruta": float(utilidad_bruta),
        "margen_bruto_pct": round(float(utilidad_bruta / ingresos_netos * 100), 1) if ingresos_netos else 0,
        "gastos_operacion": gastos_desglose,
        "total_gastos_operacion": float(total_gastos_op),
        "mermas": float(mermas),
        "utilidad_operacion": float(utilidad_operacion),
        "isr_estimado": float(isr_estimado),
        "utilidad_neta": float(utilidad_neta),
        "margen_neto_pct": round(float(utilidad_neta / ingresos_netos * 100), 1) if ingresos_netos else 0,
        "numero_ventas": len(ventas),
    }


def _prorratear_gasto(monto: Decimal, periodicidad: str, dias: int) -> Decimal:
    """Prorratea un gasto fijo al número de días del periodo."""
    if periodicidad == "mensual":
        diario = monto / Decimal("30")
    elif periodicidad == "quincenal":
        diario = monto / Decimal("15")
    elif periodicidad == "semanal":
        diario = monto / Decimal("7")
    else:
        diario = monto / Decimal("30")
    return (diario * Decimal(str(dias))).quantize(Decimal("0.01"))


# ─── Conciliación bancaria ────────────────────────────────────────

def registrar_movimiento_banco(db: Session, data: dict) -> MovimientoBancario:
    """Registra un movimiento bancario."""
    mov = MovimientoBancario(
        fecha=date.fromisoformat(data["fecha"]) if isinstance(data["fecha"], str) else data["fecha"],
        concepto=data["concepto"],
        referencia=data.get("referencia"),
        deposito=Decimal(str(data.get("deposito", 0))),
        retiro=Decimal(str(data.get("retiro", 0))),
        saldo=Decimal(str(data.get("saldo", 0))),
        notas=data.get("notas"),
    )
    db.add(mov)
    db.commit()
    db.refresh(mov)
    return mov


def conciliar_movimiento(
    db: Session, movimiento_id: int, venta_id: int | None = None
) -> MovimientoBancario:
    """Marca un movimiento bancario como conciliado."""
    mov = db.query(MovimientoBancario).filter(
        MovimientoBancario.id == movimiento_id
    ).first()
    if not mov:
        raise ValueError("Movimiento bancario no encontrado")
    mov.conciliado = True
    if venta_id:
        mov.venta_id = venta_id
    db.commit()
    db.refresh(mov)
    return mov


def conciliacion_bancaria(db: Session, mes: int, anio: int) -> dict:
    """Conciliación bancaria del mes: banco vs sistema."""
    primer_dia = date(anio, mes, 1)
    if mes == 12:
        ultimo_dia = date(anio + 1, 1, 1)
    else:
        ultimo_dia = date(anio, mes + 1, 1)

    inicio_dt = datetime.combine(primer_dia, datetime.min.time(), tzinfo=timezone.utc)
    fin_dt = datetime.combine(ultimo_dia, datetime.min.time(), tzinfo=timezone.utc)

    # Movimientos bancarios del mes
    movs_banco = db.query(MovimientoBancario).filter(
        and_(MovimientoBancario.fecha >= primer_dia,
             MovimientoBancario.fecha < ultimo_dia)
    ).order_by(MovimientoBancario.fecha).all()

    # Ventas con tarjeta/transferencia del mes (depósitos esperados)
    ventas_electronicas = db.query(Venta).filter(
        and_(Venta.estado == EstadoVenta.COMPLETADA,
             Venta.metodo_pago.in_(["03", "04", "28"]),
             Venta.fecha >= inicio_dt, Venta.fecha < fin_dt)
    ).all()

    # Identify conciliadas vs pendientes
    ventas_conciliadas_ids = {m.venta_id for m in movs_banco if m.venta_id and m.conciliado}
    ventas_no_conciliadas = [v for v in ventas_electronicas if v.id not in ventas_conciliadas_ids]

    total_depositos = sum(float(m.deposito or 0) for m in movs_banco)
    total_retiros = sum(float(m.retiro or 0) for m in movs_banco)
    saldo_banco = total_depositos - total_retiros
    saldo_sistema = sum(float(v.total) for v in ventas_electronicas)
    conciliados = sum(1 for m in movs_banco if m.conciliado)

    movs_list = []
    for m in movs_banco:
        movs_list.append({
            "id": m.id,
            "fecha": m.fecha.isoformat(),
            "concepto": m.concepto,
            "referencia": m.referencia,
            "deposito": float(m.deposito),
            "retiro": float(m.retiro),
            "saldo": float(m.saldo),
            "conciliado": m.conciliado,
            "venta_id": m.venta_id,
        })

    ventas_pend = []
    for v in ventas_no_conciliadas:
        metodos = {"03": "Transferencia", "04": "Tarjeta crédito", "28": "Tarjeta débito"}
        ventas_pend.append({
            "id": v.id,
            "folio": v.folio,
            "fecha": v.fecha.isoformat() if v.fecha else "",
            "total": float(v.total),
            "metodo": metodos.get(v.metodo_pago, v.metodo_pago),
        })

    return {
        "mes": mes,
        "anio": anio,
        "movimientos_banco": movs_list,
        "ventas_no_conciliadas": ventas_pend,
        "total_depositos": round(total_depositos, 2),
        "total_retiros": round(total_retiros, 2),
        "saldo_banco": round(saldo_banco, 2),
        "saldo_sistema": round(saldo_sistema, 2),
        "diferencia": round(saldo_banco - saldo_sistema, 2),
        "total_movimientos": len(movs_banco),
        "conciliados": conciliados,
        "porcentaje_conciliado": round(conciliados / max(len(movs_banco), 1) * 100, 1),
    }
