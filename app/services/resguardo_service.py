"""Cash control derived from closed cuts and active expenses, never a second sale."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.time_utils import operation_datetime, operation_today
from app.models.egreso import Egreso
from app.models.resguardo import ResguardoControl
from app.models.venta import CorteCaja

ZERO = Decimal("0.00")


def bloquear_resguardo(db: Session) -> ResguardoControl | None:
    # Lock before any cut/day/expense row, including the first initialization.
    connection = db.connection()
    if connection.dialect.name == "postgresql":
        db.execute(func.pg_advisory_xact_lock(674322, 1).select())
    elif connection.dialect.name == "sqlite":
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
    return db.query(ResguardoControl).filter_by(id=1).populate_existing().with_for_update().first()


def _totales(db: Session, control: ResguardoControl) -> tuple[Decimal, Decimal]:
    entradas = db.query(func.coalesce(func.sum(CorteCaja.retiros), 0)).filter(
        CorteCaja.id > control.ultimo_corte_id, CorteCaja.estado == "cerrado",
    ).scalar()
    salidas = db.query(func.coalesce(func.sum(Egreso.monto), 0)).filter(
        Egreso.id > control.ultimo_egreso_id,
        Egreso.activo.is_(True), Egreso.metodo_pago == "resguardo",
    ).scalar()
    return Decimal(str(entradas)), Decimal(str(salidas))


def saldo_resguardo(db: Session, control: ResguardoControl) -> Decimal:
    entradas, salidas = _totales(db, control)
    return control.saldo_inicial + entradas - salidas


def validar_salida_resguardo(
    db: Session, control: ResguardoControl | None, monto: Decimal,
    fecha: date, egreso: Egreso | None = None,
) -> None:
    if control is None:
        raise ValueError("Primero registra el saldo inicial de resguardo")
    if egreso and egreso.id <= control.ultimo_egreso_id:
        raise ValueError("Los egresos anteriores al inicio no pueden cargarse a resguardo")
    if fecha < operation_datetime(control.iniciado_en).date() or fecha > operation_today():
        raise ValueError("La fecha debe estar entre el inicio del resguardo y hoy")
    anterior = (
        egreso.monto if egreso and egreso.activo and egreso.metodo_pago == "resguardo" else ZERO
    )
    if saldo_resguardo(db, control) + anterior - monto < ZERO:
        raise ValueError("Saldo de resguardo insuficiente para este egreso")


def validar_cambio_retiro(
    db: Session, control: ResguardoControl | None, corte: CorteCaja, nuevo: Decimal,
) -> None:
    if control and corte.id > control.ultimo_corte_id:
        if saldo_resguardo(db, control) + nuevo - (corte.retiros or ZERO) < ZERO:
            raise ValueError("El retiro ya se utilizo: esta correccion dejaria resguardo negativo")


def resumen_resguardo(db: Session) -> dict:
    control = bloquear_resguardo(db)
    if control is None:
        return {"configurado": False, "saldo": None, "movimientos": []}
    entradas, salidas = _totales(db, control)
    cortes = db.query(CorteCaja).filter(
        CorteCaja.id > control.ultimo_corte_id, CorteCaja.estado == "cerrado", CorteCaja.retiros > 0,
    ).order_by(CorteCaja.id.desc()).limit(20).all()
    egresos = db.query(Egreso).filter(
        Egreso.id > control.ultimo_egreso_id, Egreso.activo.is_(True),
        Egreso.metodo_pago == "resguardo",
    ).order_by(Egreso.id.desc()).limit(20).all()
    movimientos = [{
        "tipo": "entrada", "id": c.id, "fecha": operation_datetime(c.fecha).isoformat(),
        "concepto": f"Corte #{c.id} - Turno {c.turno}",
        "monto": float(c.retiros), "recibido_por": c.recibido_por,
    } for c in cortes] + [{
        "tipo": "salida", "id": e.id, "fecha": operation_datetime(e.creado_en).isoformat(),
        "fecha_egreso": e.fecha.isoformat(), "concepto": e.concepto,
        "monto": float(e.monto), "proveedor": e.proveedor,
    } for e in egresos]
    movimientos.sort(key=lambda m: m["fecha"], reverse=True)
    return {
        "configurado": True, "iniciado_en": operation_datetime(control.iniciado_en).isoformat(),
        "saldo_inicial": float(control.saldo_inicial), "entradas": float(entradas),
        "salidas": float(salidas), "saldo": float(control.saldo_inicial + entradas - salidas),
        "movimientos": movimientos[:20],
    }
