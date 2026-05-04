"""
Servicio de gestión de proveedores y compras.
Órdenes de compra, recepción de mercancía, cuentas por pagar, evaluaciones.
"""

import json
from decimal import Decimal
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_
from sqlalchemy.exc import IntegrityError

from app.models.compras import (
    OrdenCompra, DetalleOrdenCompra, CuentaPagar, PagoCuentaPagar,
    EvaluacionProveedor, RecepcionOrdenCompra, EstadoOrdenCompra,
    EstadoCuentaPagar,
)
from app.models.inventario import (
    Proveedor, Ingrediente, MovimientoInventario, TipoMovimiento,
)
from app.services.auditoria_service import registrar_evento

ZERO = Decimal("0")


# ─── Proveedores ─────────────────────────────────────────────────

def listar_proveedores(db: Session, solo_activos: bool = True, skip: int = 0, limit: int = 100) -> list[dict]:
    """Lista proveedores, opcionalmente solo activos."""
    query = db.query(Proveedor)
    if solo_activos:
        query = query.filter(Proveedor.activo.is_(True))
    proveedores = query.order_by(Proveedor.nombre).offset(skip).limit(limit).all()

    return [
        {
            "id": p.id,
            "nombre": p.nombre,
            "rfc": p.rfc,
            "contacto": p.contacto,
            "telefono": p.telefono,
            "email": p.email,
            "direccion": p.direccion,
            "licencia_sanitaria": p.licencia_sanitaria,
            "certificaciones": p.certificaciones,
            "activo": p.activo,
        }
        for p in proveedores
    ]


def obtener_proveedor(db: Session, proveedor_id: int) -> dict:
    """Obtiene un proveedor con sus ingredientes asociados."""
    proveedor = db.query(Proveedor).filter(Proveedor.id == proveedor_id).first()
    if not proveedor:
        raise ValueError("Proveedor no encontrado")

    ingredientes = [
        {
            "id": ing.id,
            "nombre": ing.nombre,
            "unidad_medida": ing.unidad_medida.value,
            "stock_actual": float(ing.stock_actual),
            "costo_unitario": float(ing.costo_unitario),
        }
        for ing in proveedor.ingredientes
    ]

    return {
        "id": proveedor.id,
        "nombre": proveedor.nombre,
        "rfc": proveedor.rfc,
        "contacto": proveedor.contacto,
        "telefono": proveedor.telefono,
        "email": proveedor.email,
        "direccion": proveedor.direccion,
        "licencia_sanitaria": proveedor.licencia_sanitaria,
        "certificaciones": proveedor.certificaciones,
        "activo": proveedor.activo,
        "ingredientes": ingredientes,
    }


# ─── Órdenes de compra ──────────────────────────────────────────

def _generar_folio_oc(db: Session) -> str:
    """Genera folio auto-incremental: OC-YYYYMMDD-NNN."""
    hoy = date.today().strftime("%Y%m%d")
    prefijo = f"OC-{hoy}-"
    ultima = db.query(OrdenCompra).filter(
        OrdenCompra.folio.like(f"{prefijo}%")
    ).order_by(OrdenCompra.id.desc()).first()

    if ultima:
        num = int(ultima.folio.split("-")[-1]) + 1
    else:
        num = 1
    return f"{prefijo}{num:03d}"


def crear_orden_compra(db: Session, data: dict) -> dict:
    """
    Crea orden de compra con líneas de detalle.
    data: {proveedor_id, sucursal_id?, fecha_entrega_esperada?, notas?, usuario_id?,
           items: [{ingrediente_id, cantidad, precio_unitario}]}
    """
    proveedor = db.query(Proveedor).filter(
        Proveedor.id == data["proveedor_id"]
    ).first()
    if not proveedor:
        raise ValueError("Proveedor no encontrado")

    folio = _generar_folio_oc(db)
    subtotal = ZERO

    items = data.get("items", [])
    if not items:
        raise ValueError("La orden debe tener al menos un item")

    detalles = []
    for item in items:
        ingrediente = db.query(Ingrediente).filter(
            Ingrediente.id == item["ingrediente_id"]
        ).first()
        if not ingrediente:
            raise ValueError(f"Ingrediente ID {item['ingrediente_id']} no encontrado")

        cantidad = Decimal(str(item["cantidad"]))
        precio = Decimal(str(item["precio_unitario"]))
        if cantidad <= ZERO:
            raise ValueError("La cantidad solicitada debe ser mayor a cero")
        if precio < ZERO:
            raise ValueError("El precio unitario no puede ser negativo")
        sub = (cantidad * precio).quantize(Decimal("0.01"))
        subtotal += sub

        detalles.append(DetalleOrdenCompra(
            ingrediente_id=item["ingrediente_id"],
            cantidad_solicitada=cantidad,
            precio_unitario=precio,
            subtotal=sub,
            notas=item.get("notas"),
        ))

    iva = (subtotal * Decimal("0.16")).quantize(Decimal("0.01"))
    total = subtotal + iva

    fecha_entrega = data.get("fecha_entrega_esperada")
    if isinstance(fecha_entrega, str):
        fecha_entrega = date.fromisoformat(fecha_entrega)

    orden = OrdenCompra(
        folio=folio,
        proveedor_id=data["proveedor_id"],
        sucursal_id=data.get("sucursal_id"),
        fecha_emision=date.today(),
        fecha_entrega_esperada=fecha_entrega,
        estado=EstadoOrdenCompra.BORRADOR,
        subtotal=subtotal,
        iva=iva,
        total=total,
        notas=data.get("notas"),
        usuario_id=data.get("usuario_id"),
        detalles=detalles,
    )
    db.add(orden)
    db.commit()
    db.refresh(orden)

    return _orden_to_dict(orden)


def listar_ordenes_compra(
    db: Session,
    estado: str | None = None,
    proveedor_id: int | None = None,
    skip: int = 0, limit: int = 100) -> list[dict]:
    """Lista órdenes de compra con filtros opcionales."""
    query = db.query(OrdenCompra).options(
        joinedload(OrdenCompra.proveedor),
    )
    if estado:
        query = query.filter(OrdenCompra.estado == EstadoOrdenCompra(estado))
    if proveedor_id:
        query = query.filter(OrdenCompra.proveedor_id == proveedor_id)

    ordenes = query.order_by(OrdenCompra.creado_en.desc()).offset(skip).limit(limit).all()
    return [_orden_to_dict(o, incluir_detalles=False) for o in ordenes]


def obtener_orden_compra(db: Session, orden_id: int) -> dict:
    """Obtiene una orden de compra con sus detalles."""
    orden = db.query(OrdenCompra).options(
        joinedload(OrdenCompra.proveedor),
        joinedload(OrdenCompra.detalles).joinedload(DetalleOrdenCompra.ingrediente),
    ).filter(OrdenCompra.id == orden_id).first()

    if not orden:
        raise ValueError("Orden de compra no encontrada")
    return _orden_to_dict(orden)


def _orden_to_dict(orden: OrdenCompra, incluir_detalles: bool = True) -> dict:
    """Convierte OrdenCompra a diccionario."""
    resultado = {
        "id": orden.id,
        "folio": orden.folio,
        "proveedor_id": orden.proveedor_id,
        "proveedor_nombre": orden.proveedor.nombre if orden.proveedor else None,
        "sucursal_id": orden.sucursal_id,
        "fecha_emision": orden.fecha_emision.isoformat() if orden.fecha_emision else None,
        "fecha_entrega_esperada": orden.fecha_entrega_esperada.isoformat() if orden.fecha_entrega_esperada else None,
        "fecha_recepcion": orden.fecha_recepcion.isoformat() if orden.fecha_recepcion else None,
        "estado": orden.estado.value,
        "subtotal": float(orden.subtotal),
        "iva": float(orden.iva),
        "total": float(orden.total),
        "notas": orden.notas,
        "creado_en": orden.creado_en.isoformat() if orden.creado_en else None,
    }
    if incluir_detalles:
        resultado["detalles"] = [
            {
                "id": d.id,
                "ingrediente_id": d.ingrediente_id,
                "ingrediente_nombre": d.ingrediente.nombre if d.ingrediente else None,
                "cantidad_solicitada": float(d.cantidad_solicitada),
                "cantidad_recibida": float(d.cantidad_recibida),
                "precio_unitario": float(d.precio_unitario),
                "subtotal": float(d.subtotal),
                "notas": d.notas,
            }
            for d in orden.detalles
        ]
    return resultado


# ─── Recepción de mercancía ──────────────────────────────────────

def recibir_orden(
    db: Session,
    orden_id: int,
    items_recibidos: list[dict],
    idempotency_key: str | None = None,
    usuario_id: int | None = None,
) -> dict:
    """
    Recibe mercancía de una orden de compra.
    items_recibidos: [{detalle_id, cantidad_recibida}]
    Actualiza stock de ingredientes y crea movimientos de inventario.
    """
    if idempotency_key:
        recepcion_existente = db.query(RecepcionOrdenCompra).filter(
            RecepcionOrdenCompra.idempotency_key == idempotency_key
        ).first()
        if recepcion_existente:
            if recepcion_existente.orden_id != orden_id:
                raise ValueError("La clave idempotente ya fue usada en otra orden")
            return obtener_orden_compra(db, orden_id)

    try:
        orden = db.query(OrdenCompra).options(
            joinedload(OrdenCompra.detalles).joinedload(DetalleOrdenCompra.ingrediente),
        ).filter(OrdenCompra.id == orden_id).with_for_update().first()

        if not orden:
            raise ValueError("Orden de compra no encontrada")
        if orden.estado in (EstadoOrdenCompra.RECIBIDA, EstadoOrdenCompra.CANCELADA):
            raise ValueError(f"No se puede recibir una orden en estado '{orden.estado.value}'")
        if not items_recibidos:
            raise ValueError("Debe registrar al menos un item recibido")

        if idempotency_key:
            recepcion = RecepcionOrdenCompra(
                orden_id=orden_id,
                idempotency_key=idempotency_key,
                usuario_id=usuario_id,
                payload_json=json.dumps(items_recibidos, default=str, sort_keys=True),
            )
            db.add(recepcion)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                return obtener_orden_compra(db, orden_id)

        detalles_map = {d.id: d for d in orden.detalles}
        toda_completa = True
        datos_anteriores: dict[str, dict] = {"estado": orden.estado.value, "detalles": {}}
        datos_nuevos: dict[str, dict] = {"detalles": {}}

        for item in items_recibidos:
            detalle = detalles_map.get(item["detalle_id"])
            if not detalle:
                raise ValueError(f"Detalle ID {item['detalle_id']} no pertenece a esta orden")

            cantidad = Decimal(str(item["cantidad_recibida"]))
            if cantidad <= 0:
                raise ValueError("La cantidad recibida debe ser mayor a cero")

            pendiente = detalle.cantidad_solicitada - detalle.cantidad_recibida
            if cantidad > pendiente:
                raise ValueError(
                    "La cantidad recibida excede lo pendiente para el detalle "
                    f"{detalle.id}: pendiente {pendiente}, recibido {cantidad}"
                )

            ingrediente = db.query(Ingrediente).filter(
                Ingrediente.id == detalle.ingrediente_id
            ).with_for_update().first()
            if not ingrediente:
                raise ValueError(f"Ingrediente ID {detalle.ingrediente_id} no encontrado")

            datos_anteriores["detalles"][str(detalle.id)] = {
                "cantidad_recibida": detalle.cantidad_recibida,
                "stock_ingrediente": ingrediente.stock_actual,
            }

            detalle.cantidad_recibida = detalle.cantidad_recibida + cantidad
            ingrediente.stock_actual = ingrediente.stock_actual + cantidad

            mov = MovimientoInventario(
                tipo=TipoMovimiento.ENTRADA_COMPRA,
                ingrediente_id=ingrediente.id,
                cantidad=cantidad,
                costo_unitario=detalle.precio_unitario,
                referencia=f"OC {orden.folio}",
                notas=f"Recepcion orden de compra {orden.folio}",
                usuario_id=usuario_id,
            )
            db.add(mov)

            datos_nuevos["detalles"][str(detalle.id)] = {
                "cantidad_recibida": detalle.cantidad_recibida,
                "stock_ingrediente": ingrediente.stock_actual,
            }

        # Determinar estado de la orden
        for detalle in orden.detalles:
            if detalle.cantidad_recibida < detalle.cantidad_solicitada:
                toda_completa = False
                break

        if toda_completa:
            orden.estado = EstadoOrdenCompra.RECIBIDA
            orden.fecha_recepcion = date.today()
        else:
            orden.estado = EstadoOrdenCompra.PARCIAL

        datos_nuevos["estado"] = orden.estado.value
        registrar_evento(
            db,
            usuario_id=usuario_id,
            usuario_nombre=None,
            accion="recibir",
            modulo="compras",
            entidad="ordenes_compra",
            entidad_id=orden.id,
            datos_anteriores=datos_anteriores,
            datos_nuevos=datos_nuevos,
            commit=False,
        )

        db.commit()
        db.refresh(orden)
        return _orden_to_dict(orden)
    except Exception:
        db.rollback()
        raise


# ─── Cuentas por pagar ──────────────────────────────────────────

def crear_cuenta_pagar(db: Session, data: dict) -> dict:
    """
    Crea una cuenta por pagar.
    data: {proveedor_id, orden_compra_id?, concepto, monto_total,
           fecha_factura, fecha_vencimiento, numero_factura?, notas?}
    """
    proveedor = db.query(Proveedor).filter(
        Proveedor.id == data["proveedor_id"]
    ).first()
    if not proveedor:
        raise ValueError("Proveedor no encontrado")

    monto_total = Decimal(str(data["monto_total"]))
    if monto_total <= ZERO:
        raise ValueError("El monto total debe ser mayor a cero")

    fecha_factura = data["fecha_factura"]
    if isinstance(fecha_factura, str):
        fecha_factura = date.fromisoformat(fecha_factura)
    fecha_vencimiento = data["fecha_vencimiento"]
    if isinstance(fecha_vencimiento, str):
        fecha_vencimiento = date.fromisoformat(fecha_vencimiento)
    if fecha_vencimiento < fecha_factura:
        raise ValueError("La fecha de vencimiento no puede ser anterior a la factura")

    cuenta = CuentaPagar(
        proveedor_id=data["proveedor_id"],
        orden_compra_id=data.get("orden_compra_id"),
        concepto=data["concepto"],
        monto_total=monto_total,
        monto_pagado=ZERO,
        saldo_pendiente=monto_total,
        fecha_factura=fecha_factura,
        fecha_vencimiento=fecha_vencimiento,
        estado=EstadoCuentaPagar.PENDIENTE,
        numero_factura=data.get("numero_factura"),
        notas=data.get("notas"),
    )
    db.add(cuenta)
    db.commit()
    db.refresh(cuenta)
    return _cuenta_to_dict(cuenta)


def listar_cuentas_pagar(
    db: Session,
    estado: str | None = None,
    proveedor_id: int | None = None,
    skip: int = 0, limit: int = 100) -> list[dict]:
    """Lista cuentas por pagar con filtros opcionales."""
    query = db.query(CuentaPagar).options(
        joinedload(CuentaPagar.proveedor),
    )
    if estado:
        query = query.filter(CuentaPagar.estado == EstadoCuentaPagar(estado))
    if proveedor_id:
        query = query.filter(CuentaPagar.proveedor_id == proveedor_id)

    cuentas = query.order_by(CuentaPagar.fecha_vencimiento).offset(skip).limit(limit).all()
    return [_cuenta_to_dict(c) for c in cuentas]


def _cuenta_to_dict(cuenta: CuentaPagar) -> dict:
    """Convierte CuentaPagar a diccionario."""
    return {
        "id": cuenta.id,
        "proveedor_id": cuenta.proveedor_id,
        "proveedor_nombre": cuenta.proveedor.nombre if cuenta.proveedor else None,
        "orden_compra_id": cuenta.orden_compra_id,
        "concepto": cuenta.concepto,
        "monto_total": float(cuenta.monto_total),
        "monto_pagado": float(cuenta.monto_pagado),
        "saldo_pendiente": float(cuenta.saldo_pendiente),
        "fecha_factura": cuenta.fecha_factura.isoformat(),
        "fecha_vencimiento": cuenta.fecha_vencimiento.isoformat(),
        "estado": cuenta.estado.value,
        "numero_factura": cuenta.numero_factura,
        "notas": cuenta.notas,
        "creado_en": cuenta.creado_en.isoformat() if cuenta.creado_en else None,
    }


# ─── Pagos ───────────────────────────────────────────────────────

def registrar_pago(db: Session, cuenta_id: int, data: dict) -> dict:
    """
    Registra un pago a una cuenta por pagar.
    data: {monto, metodo_pago, referencia?, fecha_pago, notas?}
    Actualiza monto_pagado, saldo_pendiente y estado.
    """
    cuenta = db.query(CuentaPagar).options(
        joinedload(CuentaPagar.proveedor),
        joinedload(CuentaPagar.pagos),
    ).filter(CuentaPagar.id == cuenta_id).first()

    if not cuenta:
        raise ValueError("Cuenta por pagar no encontrada")
    if cuenta.estado in (EstadoCuentaPagar.PAGADA, EstadoCuentaPagar.CANCELADA):
        raise ValueError(f"No se puede pagar una cuenta en estado '{cuenta.estado.value}'")

    monto = Decimal(str(data["monto"]))
    if monto <= ZERO:
        raise ValueError("El monto del pago debe ser mayor a cero")
    if monto > cuenta.saldo_pendiente:
        raise ValueError(
            f"El monto ({monto}) excede el saldo pendiente ({cuenta.saldo_pendiente})"
        )

    fecha_pago = data["fecha_pago"]
    if isinstance(fecha_pago, str):
        fecha_pago = date.fromisoformat(fecha_pago)

    pago = PagoCuentaPagar(
        cuenta_id=cuenta_id,
        monto=monto,
        metodo_pago=data["metodo_pago"],
        referencia=data.get("referencia"),
        fecha_pago=fecha_pago,
        notas=data.get("notas"),
    )
    db.add(pago)

    cuenta.monto_pagado = cuenta.monto_pagado + monto
    cuenta.saldo_pendiente = cuenta.monto_total - cuenta.monto_pagado

    if cuenta.saldo_pendiente <= ZERO:
        cuenta.estado = EstadoCuentaPagar.PAGADA
    else:
        cuenta.estado = EstadoCuentaPagar.PARCIAL

    db.commit()
    db.refresh(cuenta)
    db.refresh(pago)

    return {
        "pago": {
            "id": pago.id,
            "monto": float(pago.monto),
            "metodo_pago": pago.metodo_pago,
            "referencia": pago.referencia,
            "fecha_pago": pago.fecha_pago.isoformat(),
            "notas": pago.notas,
        },
        "cuenta": _cuenta_to_dict(cuenta),
    }


# ─── Calendario de pagos ────────────────────────────────────────

def calendario_pagos(db: Session, dias: int = 30) -> list[dict]:
    """Cuentas por pagar que vencen en los próximos N días."""
    hoy = date.today()
    limite = hoy + timedelta(days=dias)

    cuentas = db.query(CuentaPagar).options(
        joinedload(CuentaPagar.proveedor),
    ).filter(
        and_(
            CuentaPagar.estado.in_([
                EstadoCuentaPagar.PENDIENTE,
                EstadoCuentaPagar.PARCIAL,
                EstadoCuentaPagar.VENCIDA,
            ]),
            CuentaPagar.fecha_vencimiento <= limite,
        )
    ).order_by(CuentaPagar.fecha_vencimiento).all()

    resultado = []
    for c in cuentas:
        dias_restantes = (c.fecha_vencimiento - hoy).days
        resultado.append({
            **_cuenta_to_dict(c),
            "dias_restantes": dias_restantes,
            "vencida": dias_restantes < 0,
        })
    return resultado


# ─── Evaluación de proveedores ───────────────────────────────────

def evaluar_proveedor(
    db: Session,
    proveedor_id: int,
    periodo_inicio: date,
    periodo_fin: date,
) -> dict:
    """
    Evalúa automáticamente un proveedor con base en sus órdenes del periodo.
    Calcula entregas a tiempo, entregas completas y valor promedio.
    """
    proveedor = db.query(Proveedor).filter(Proveedor.id == proveedor_id).first()
    if not proveedor:
        raise ValueError("Proveedor no encontrado")

    ordenes = db.query(OrdenCompra).filter(
        and_(
            OrdenCompra.proveedor_id == proveedor_id,
            OrdenCompra.fecha_emision >= periodo_inicio,
            OrdenCompra.fecha_emision <= periodo_fin,
            OrdenCompra.estado.in_([
                EstadoOrdenCompra.RECIBIDA,
                EstadoOrdenCompra.PARCIAL,
            ]),
        )
    ).options(
        joinedload(OrdenCompra.detalles),
    ).all()

    total_ordenes = len(ordenes)
    if total_ordenes == 0:
        raise ValueError("No hay ordenes completadas en el periodo para evaluar")

    entregas_a_tiempo = 0
    entregas_completas = 0
    valor_total = ZERO

    for orden in ordenes:
        valor_total += orden.total

        # A tiempo: recibida en o antes de la fecha esperada
        if orden.fecha_recepcion and orden.fecha_entrega_esperada:
            if orden.fecha_recepcion <= orden.fecha_entrega_esperada:
                entregas_a_tiempo += 1
        elif orden.fecha_recepcion:
            # Si no hay fecha esperada, se considera a tiempo
            entregas_a_tiempo += 1

        # Completa: todas las cantidades recibidas >= solicitadas
        completa = all(
            d.cantidad_recibida >= d.cantidad_solicitada
            for d in orden.detalles
        )
        if completa:
            entregas_completas += 1

    pct_puntualidad = round(entregas_a_tiempo / total_ordenes * 100, 1)
    pct_completas = round(entregas_completas / total_ordenes * 100, 1)
    valor_promedio = float((valor_total / Decimal(str(total_ordenes))).quantize(Decimal("0.01")))

    # Calificaciones 1-5
    cal_puntualidad = min(5, max(1, round(pct_puntualidad / 20)))
    cal_completitud = min(5, max(1, round(pct_completas / 20)))
    cal_global = Decimal(str(round((cal_puntualidad + cal_completitud) / 2, 1)))

    evaluacion = EvaluacionProveedor(
        proveedor_id=proveedor_id,
        periodo_inicio=periodo_inicio,
        periodo_fin=periodo_fin,
        puntualidad_entrega=cal_puntualidad,
        calidad_producto=3,  # Default, se ajusta manualmente
        precio_competitivo=3,
        atencion_servicio=3,
        calificacion_global=cal_global,
        ordenes_evaluadas=total_ordenes,
        entregas_a_tiempo=entregas_a_tiempo,
        entregas_completas=entregas_completas,
    )
    db.add(evaluacion)
    db.commit()
    db.refresh(evaluacion)

    return {
        "id": evaluacion.id,
        "proveedor_id": proveedor_id,
        "proveedor_nombre": proveedor.nombre,
        "periodo_inicio": periodo_inicio.isoformat(),
        "periodo_fin": periodo_fin.isoformat(),
        "ordenes_evaluadas": total_ordenes,
        "entregas_a_tiempo": entregas_a_tiempo,
        "entregas_completas": entregas_completas,
        "pct_puntualidad": pct_puntualidad,
        "pct_completas": pct_completas,
        "valor_promedio_orden": valor_promedio,
        "calificaciones": {
            "puntualidad_entrega": cal_puntualidad,
            "calidad_producto": evaluacion.calidad_producto,
            "precio_competitivo": evaluacion.precio_competitivo,
            "atencion_servicio": evaluacion.atencion_servicio,
            "global": float(cal_global),
        },
    }


# ─── Dashboard de compras ───────────────────────────────────────

def dashboard_compras(db: Session) -> dict:
    """
    Resumen del módulo de compras:
    - Total cuentas por pagar pendientes
    - Cuentas vencidas
    - Órdenes en progreso
    - Top proveedores por volumen
    """
    hoy = date.today()

    # Cuentas por pagar pendientes
    pendientes = db.query(
        func.coalesce(func.sum(CuentaPagar.saldo_pendiente), 0),
        func.count(CuentaPagar.id),
    ).filter(
        CuentaPagar.estado.in_([
            EstadoCuentaPagar.PENDIENTE,
            EstadoCuentaPagar.PARCIAL,
        ])
    ).first()
    total_por_pagar = float(pendientes[0])
    num_cuentas_pendientes = pendientes[1]

    # Cuentas vencidas
    vencidas = db.query(
        func.coalesce(func.sum(CuentaPagar.saldo_pendiente), 0),
        func.count(CuentaPagar.id),
    ).filter(
        and_(
            CuentaPagar.estado.in_([
                EstadoCuentaPagar.PENDIENTE,
                EstadoCuentaPagar.PARCIAL,
                EstadoCuentaPagar.VENCIDA,
            ]),
            CuentaPagar.fecha_vencimiento < hoy,
        )
    ).first()
    total_vencido = float(vencidas[0])
    num_cuentas_vencidas = vencidas[1]

    # Órdenes en progreso (borrador, enviada, parcial)
    ordenes_progreso = db.query(func.count(OrdenCompra.id)).filter(
        OrdenCompra.estado.in_([
            EstadoOrdenCompra.BORRADOR,
            EstadoOrdenCompra.ENVIADA,
            EstadoOrdenCompra.PARCIAL,
        ])
    ).scalar()

    # Top 5 proveedores por volumen (últimos 90 días)
    hace_90 = hoy - timedelta(days=90)
    top_proveedores = db.query(
        Proveedor.id,
        Proveedor.nombre,
        func.count(OrdenCompra.id).label("num_ordenes"),
        func.coalesce(func.sum(OrdenCompra.total), 0).label("total_compras"),
    ).join(
        OrdenCompra, OrdenCompra.proveedor_id == Proveedor.id
    ).filter(
        and_(
            OrdenCompra.fecha_emision >= hace_90,
            OrdenCompra.estado.in_([
                EstadoOrdenCompra.RECIBIDA,
                EstadoOrdenCompra.PARCIAL,
                EstadoOrdenCompra.ENVIADA,
            ]),
        )
    ).group_by(
        Proveedor.id, Proveedor.nombre
    ).order_by(
        func.sum(OrdenCompra.total).desc()
    ).limit(5).all()

    top_list = [
        {
            "proveedor_id": p.id,
            "proveedor_nombre": p.nombre,
            "num_ordenes": p.num_ordenes,
            "total_compras": float(p.total_compras),
        }
        for p in top_proveedores
    ]

    # Próximos pagos (7 días)
    proximos = db.query(func.count(CuentaPagar.id)).filter(
        and_(
            CuentaPagar.estado.in_([
                EstadoCuentaPagar.PENDIENTE,
                EstadoCuentaPagar.PARCIAL,
            ]),
            CuentaPagar.fecha_vencimiento >= hoy,
            CuentaPagar.fecha_vencimiento <= hoy + timedelta(days=7),
        )
    ).scalar()

    return {
        "total_por_pagar": total_por_pagar,
        "num_cuentas_pendientes": num_cuentas_pendientes,
        "total_vencido": total_vencido,
        "num_cuentas_vencidas": num_cuentas_vencidas,
        "ordenes_en_progreso": ordenes_progreso,
        "pagos_proximos_7_dias": proximos,
        "top_proveedores": top_list,
    }
