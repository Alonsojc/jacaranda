"""
Servicio del sistema de lealtad avanzado.
Niveles, cupones, tarjeta digital QR, promociones de cumpleanos.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from app.models.cliente import Cliente
from app.models.lealtad import (
    Cupon, CuponCliente, HistorialPuntos,
    NivelLealtad, TipoCupon, EstadoCupon,
)
from app.services.venta_service import PUNTOS_POR_PESO


# ── Niveles ──────────────────────────────────────────────────────────

NIVELES_CONFIG = {
    NivelLealtad.BRONCE: {"min": 0, "max": 499, "multiplicador": 1.0},
    NivelLealtad.PLATA:  {"min": 500, "max": 1499, "multiplicador": 1.5},
    NivelLealtad.ORO:    {"min": 1500, "max": None, "multiplicador": 2.0},
}


def calcular_nivel(puntos_historicos: int) -> NivelLealtad:
    """Determina el nivel de lealtad segun puntos historicos acumulados."""
    if puntos_historicos >= 1500:
        return NivelLealtad.ORO
    if puntos_historicos >= 500:
        return NivelLealtad.PLATA
    return NivelLealtad.BRONCE


def multiplicador_puntos(nivel: NivelLealtad) -> float:
    """Retorna el multiplicador de puntos segun nivel."""
    return NIVELES_CONFIG[nivel]["multiplicador"]


# ── Puntos ───────────────────────────────────────────────────────────

def acumular_puntos(
    db: Session,
    cliente_id: int,
    venta_id: int,
    monto_venta: Decimal,
) -> dict:
    """
    Calcula y acumula puntos por una venta.
    1 punto por cada $10 * multiplicador del nivel.
    Actualiza puntos_acumulados, puntos_totales_historicos y nivel.
    Registra movimiento en HistorialPuntos.
    """
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise ValueError("Cliente no encontrado")

    nivel = calcular_nivel(cliente.puntos_totales_historicos)
    mult = multiplicador_puntos(nivel)

    puntos_base = int(monto_venta * PUNTOS_POR_PESO)
    puntos_ganados = int(puntos_base * mult)

    saldo_anterior = cliente.puntos_acumulados
    cliente.puntos_acumulados += puntos_ganados
    cliente.puntos_totales_historicos += puntos_ganados

    # Recalcular nivel despues de acumular
    nuevo_nivel = calcular_nivel(cliente.puntos_totales_historicos)
    cliente.nivel_lealtad = nuevo_nivel.value

    historial = HistorialPuntos(
        cliente_id=cliente_id,
        puntos=puntos_ganados,
        concepto=f"Compra (venta #{venta_id}) - x{mult} nivel {nivel.value}",
        venta_id=venta_id,
        saldo_anterior=saldo_anterior,
        saldo_nuevo=cliente.puntos_acumulados,
    )
    db.add(historial)
    db.flush()

    return {
        "puntos_ganados": puntos_ganados,
        "multiplicador": mult,
        "nivel": nuevo_nivel.value,
        "saldo": cliente.puntos_acumulados,
    }


# ── Tarjeta digital QR ──────────────────────────────────────────────

def generar_tarjeta_qr(db: Session, cliente_id: int) -> dict:
    """Genera un UUID unico para la tarjeta QR del cliente."""
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise ValueError("Cliente no encontrado")

    qr_code = str(uuid.uuid4())
    cliente.tarjeta_qr = qr_code
    db.flush()

    return {
        "cliente_id": cliente.id,
        "nombre": cliente.nombre,
        "tarjeta_qr": qr_code,
    }


def obtener_tarjeta(db: Session, cliente_id: int) -> dict:
    """Obtiene los datos de la tarjeta de lealtad digital."""
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise ValueError("Cliente no encontrado")

    return {
        "cliente_id": cliente.id,
        "nombre": cliente.nombre,
        "nivel": cliente.nivel_lealtad,
        "puntos_acumulados": cliente.puntos_acumulados,
        "puntos_totales_historicos": cliente.puntos_totales_historicos,
        "tarjeta_qr": cliente.tarjeta_qr,
    }


def buscar_por_qr(db: Session, qr_code: str) -> Cliente | None:
    """Busca un cliente por su codigo QR de tarjeta digital."""
    return db.query(Cliente).filter(
        Cliente.tarjeta_qr == qr_code,
        Cliente.activo.is_(True),
    ).first()


# ── Cupones ──────────────────────────────────────────────────────────

def crear_cupon(db: Session, data: dict) -> Cupon:
    """Crea un nuevo cupon/promocion."""
    cupon = Cupon(**data)
    db.add(cupon)
    db.flush()
    db.refresh(cupon)
    return cupon


def listar_cupones(db: Session, activos_only: bool = True) -> list[Cupon]:
    """Lista cupones, opcionalmente solo los activos."""
    query = db.query(Cupon)
    if activos_only:
        hoy = date.today()
        query = query.filter(
            Cupon.activo.is_(True),
            Cupon.estado == EstadoCupon.ACTIVO,
            Cupon.fecha_inicio <= hoy,
            Cupon.fecha_fin >= hoy,
        )
    return query.order_by(Cupon.fecha_fin.desc()).all()


def validar_cupon(
    db: Session,
    codigo: str,
    cliente_id: int | None = None,
    monto_compra: Decimal = Decimal("0"),
) -> dict:
    """
    Valida un cupon. Verifica fechas, usos, nivel requerido y compra minima.
    Retorna dict con valid=True/False y reason.
    """
    cupon = db.query(Cupon).filter(Cupon.codigo == codigo).first()
    if not cupon:
        return {"valid": False, "reason": "Cupon no encontrado"}

    if not cupon.activo or cupon.estado != EstadoCupon.ACTIVO:
        return {"valid": False, "reason": "Cupon inactivo o cancelado"}

    hoy = date.today()
    if hoy < cupon.fecha_inicio:
        return {"valid": False, "reason": "Cupon aun no vigente"}
    if hoy > cupon.fecha_fin:
        return {"valid": False, "reason": "Cupon expirado"}

    if cupon.usos_actuales >= cupon.max_usos:
        return {"valid": False, "reason": "Cupon agotado (maximo de usos alcanzado)"}

    if cupon.compra_minima and monto_compra < cupon.compra_minima:
        return {
            "valid": False,
            "reason": f"Compra minima requerida: ${cupon.compra_minima}",
        }

    if cupon.nivel_requerido and cliente_id:
        cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
        if cliente:
            nivel_cliente = calcular_nivel(cliente.puntos_totales_historicos)
            niveles_orden = [NivelLealtad.BRONCE, NivelLealtad.PLATA, NivelLealtad.ORO]
            if niveles_orden.index(nivel_cliente) < niveles_orden.index(cupon.nivel_requerido):
                return {
                    "valid": False,
                    "reason": f"Requiere nivel {cupon.nivel_requerido.value} o superior",
                }

    return {
        "valid": True,
        "reason": "Cupon valido",
        "cupon": {
            "id": cupon.id,
            "codigo": cupon.codigo,
            "nombre": cupon.nombre,
            "tipo": cupon.tipo.value,
            "valor": float(cupon.valor),
        },
    }


def canjear_cupon(
    db: Session,
    codigo: str,
    cliente_id: int,
    venta_id: int,
) -> CuponCliente:
    """Marca un cupon como usado por un cliente en una venta."""
    cupon = db.query(Cupon).filter(Cupon.codigo == codigo).first()
    if not cupon:
        raise ValueError("Cupon no encontrado")

    cupon.usos_actuales += 1
    if cupon.usos_actuales >= cupon.max_usos:
        cupon.estado = EstadoCupon.USADO

    registro = CuponCliente(
        cupon_id=cupon.id,
        cliente_id=cliente_id,
        usado=True,
        fecha_uso=datetime.now(timezone.utc),
        venta_id=venta_id,
    )
    db.add(registro)
    db.flush()
    return registro


def asignar_cupon_cliente(db: Session, cupon_id: int, cliente_id: int) -> CuponCliente:
    """Asigna un cupon personal a un cliente."""
    asignacion = CuponCliente(
        cupon_id=cupon_id,
        cliente_id=cliente_id,
    )
    db.add(asignacion)
    db.flush()
    db.refresh(asignacion)
    return asignacion


# ── Cumpleanos ───────────────────────────────────────────────────────

def cumpleanos_del_mes(db: Session) -> list[Cliente]:
    """Lista clientes que cumplen anos este mes."""
    mes_actual = date.today().month
    return (
        db.query(Cliente)
        .filter(
            Cliente.activo.is_(True),
            Cliente.fecha_cumpleanos.isnot(None),
            extract("month", Cliente.fecha_cumpleanos) == mes_actual,
        )
        .order_by(extract("day", Cliente.fecha_cumpleanos))
        .all()
    )


def enviar_ofertas_cumpleanos(db: Session) -> list[dict]:
    """
    Genera cupones de cumpleanos (10% descuento) para clientes que
    cumplen anos este mes y aun no tienen cupon de cumpleanos vigente.
    """
    hoy = date.today()
    clientes = cumpleanos_del_mes(db)
    resultados = []

    for cliente in clientes:
        # Verificar si ya tiene cupon de cumpleanos este mes
        codigo_cumple = f"CUMPLE-{cliente.id}-{hoy.year}-{hoy.month:02d}"
        existente = db.query(Cupon).filter(Cupon.codigo == codigo_cumple).first()
        if existente:
            continue

        # Crear cupon de cumpleanos: 10% descuento, valido todo el mes
        primer_dia = hoy.replace(day=1)
        if hoy.month == 12:
            ultimo_dia = hoy.replace(month=12, day=31)
        else:
            ultimo_dia = hoy.replace(month=hoy.month + 1, day=1).replace(
                day=1
            ) - __import__("datetime").timedelta(days=1)

        cupon = Cupon(
            codigo=codigo_cumple,
            nombre=f"Feliz cumpleanos {cliente.nombre}",
            descripcion="Cupon de cumpleanos - 10% de descuento",
            tipo=TipoCupon.PORCENTAJE,
            valor=Decimal("10"),
            compra_minima=Decimal("0"),
            nivel_requerido=None,
            max_usos=1,
            fecha_inicio=primer_dia,
            fecha_fin=ultimo_dia,
            estado=EstadoCupon.ACTIVO,
            activo=True,
        )
        db.add(cupon)
        db.flush()

        # Asignar al cliente
        asignacion = CuponCliente(
            cupon_id=cupon.id,
            cliente_id=cliente.id,
        )
        db.add(asignacion)

        resultados.append({
            "cliente_id": cliente.id,
            "nombre": cliente.nombre,
            "cupon_codigo": codigo_cumple,
        })

    db.flush()
    return resultados


# ── Dashboard ────────────────────────────────────────────────────────

def dashboard_lealtad(db: Session) -> dict:
    """Estadisticas del programa de lealtad."""
    # Clientes por nivel
    niveles = (
        db.query(Cliente.nivel_lealtad, func.count(Cliente.id))
        .filter(Cliente.activo.is_(True))
        .group_by(Cliente.nivel_lealtad)
        .all()
    )
    clientes_por_nivel = {nivel: count for nivel, count in niveles}

    # Total puntos en circulacion
    total_puntos = (
        db.query(func.sum(Cliente.puntos_acumulados))
        .filter(Cliente.activo.is_(True))
        .scalar()
    ) or 0

    # Top clientes por puntos historicos
    top_clientes = (
        db.query(Cliente)
        .filter(Cliente.activo.is_(True))
        .order_by(Cliente.puntos_totales_historicos.desc())
        .limit(10)
        .all()
    )

    # Cupones activos
    hoy = date.today()
    cupones_activos = (
        db.query(func.count(Cupon.id))
        .filter(
            Cupon.activo.is_(True),
            Cupon.estado == EstadoCupon.ACTIVO,
            Cupon.fecha_fin >= hoy,
        )
        .scalar()
    ) or 0

    return {
        "clientes_por_nivel": clientes_por_nivel,
        "total_puntos_circulacion": total_puntos,
        "top_clientes": [
            {
                "id": c.id,
                "nombre": c.nombre,
                "nivel": c.nivel_lealtad,
                "puntos_acumulados": c.puntos_acumulados,
                "puntos_totales_historicos": c.puntos_totales_historicos,
            }
            for c in top_clientes
        ],
        "cupones_activos": cupones_activos,
    }
