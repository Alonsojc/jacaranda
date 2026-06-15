"""Servicio de ventas a cafeterías con crédito."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.cafeteria import (
    CafeteriaCliente,
    CafeteriaVenta,
    DetalleCafeteriaVenta,
    EstadoCuentaCafeteria,
    PagoCafeteriaVenta,
)
from app.models.inventario import Producto, TipoMovimiento
from app.schemas.cafeteria import (
    CafeteriaClienteCreate,
    CafeteriaClienteUpdate,
    CafeteriaVentaCreate,
    PagoCafeteriaCreate,
)
from app.schemas.inventario import MovimientoCreate
from app.services.auditoria_service import registrar_evento
from app.services.inventario_service import registrar_empaque_producto, registrar_movimiento
from app.services.venta_service import (
    _normalizar_fecha_db,
    _normalizar_metodo_terminal,
    _obtener_tasa_iva,
    _zona_operacion,
)

CENTAVO = Decimal("0.01")


def _q(valor: Decimal) -> Decimal:
    return Decimal(valor or 0).quantize(CENTAVO)


def _limpiar_texto(valor: str | None) -> str | None:
    limpio = (valor or "").strip()
    return limpio or None


def _estado_por_montos(total: Decimal, pagado: Decimal) -> EstadoCuentaCafeteria:
    total_q = _q(total)
    pagado_q = _q(pagado)
    if pagado_q <= 0:
        return EstadoCuentaCafeteria.PENDIENTE
    if pagado_q >= total_q:
        return EstadoCuentaCafeteria.PAGADA
    return EstadoCuentaCafeteria.PARCIAL


def _generar_folio(db: Session) -> str:
    ultima = db.query(CafeteriaVenta).order_by(CafeteriaVenta.id.desc()).first()
    if not ultima:
        numero = 1
    else:
        try:
            numero = int(str(ultima.folio).split("-")[-1]) + 1
        except (TypeError, ValueError):
            numero = ultima.id + 1
    return f"CAF-{numero:08d}"


def listar_cafeterias(db: Session, q: str | None = None, limit: int = 200) -> list[CafeteriaCliente]:
    query = db.query(CafeteriaCliente).filter(CafeteriaCliente.activo.is_(True))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(CafeteriaCliente.nombre.ilike(like))
    return query.order_by(CafeteriaCliente.nombre).limit(limit).all()


def _buscar_cafeteria_por_nombre(db: Session, nombre: str) -> CafeteriaCliente | None:
    normalizado = nombre.strip().lower()
    return (
        db.query(CafeteriaCliente)
        .filter(func.lower(CafeteriaCliente.nombre) == normalizado)
        .first()
    )


def crear_cafeteria(
    db: Session,
    data: CafeteriaClienteCreate,
    usuario_id: int | None,
    *,
    commit: bool = True,
) -> CafeteriaCliente:
    nombre = data.nombre.strip()
    if not nombre:
        raise ValueError("El nombre de la cafetería es obligatorio")
    existente = _buscar_cafeteria_por_nombre(db, nombre)
    if existente:
        if not existente.activo:
            existente.activo = True
        existente.contacto_nombre = _limpiar_texto(data.contacto_nombre) or existente.contacto_nombre
        existente.telefono = _limpiar_texto(data.telefono) or existente.telefono
        existente.dias_credito = data.dias_credito
        existente.actualizado_por_id = usuario_id
        cliente = existente
        accion = "actualizar"
    else:
        cliente = CafeteriaCliente(
            nombre=nombre,
            contacto_nombre=_limpiar_texto(data.contacto_nombre),
            telefono=_limpiar_texto(data.telefono),
            dias_credito=data.dias_credito,
            creado_por_id=usuario_id,
            actualizado_por_id=usuario_id,
        )
        db.add(cliente)
        accion = "crear"
    db.flush()
    registrar_evento(
        db,
        usuario_id=usuario_id,
        usuario_nombre=None,
        accion=accion,
        modulo="cafeteria",
        entidad="cafeteria_cliente",
        entidad_id=cliente.id,
        datos_nuevos={
            "nombre": cliente.nombre,
            "contacto_nombre": cliente.contacto_nombre,
            "telefono": cliente.telefono,
            "dias_credito": cliente.dias_credito,
            "activo": cliente.activo,
        },
        commit=False,
    )
    if commit:
        db.commit()
        db.refresh(cliente)
    return cliente


def actualizar_cafeteria(
    db: Session,
    cliente_id: int,
    data: CafeteriaClienteUpdate,
    usuario_id: int | None,
) -> CafeteriaCliente:
    cliente = db.query(CafeteriaCliente).filter(CafeteriaCliente.id == cliente_id).first()
    if not cliente:
        raise ValueError("Cafetería no encontrada")
    antes = {
        "nombre": cliente.nombre,
        "contacto_nombre": cliente.contacto_nombre,
        "telefono": cliente.telefono,
        "dias_credito": cliente.dias_credito,
        "activo": cliente.activo,
    }
    updates = data.model_dump(exclude_unset=True)
    if "nombre" in updates and updates["nombre"]:
        nombre = updates["nombre"].strip()
        existente = _buscar_cafeteria_por_nombre(db, nombre)
        if existente and existente.id != cliente.id:
            raise ValueError("Ya existe una cafetería con ese nombre")
        cliente.nombre = nombre
    for campo in ("contacto_nombre", "telefono", "dias_credito", "activo"):
        if campo in updates:
            valor = updates[campo]
            if campo in ("contacto_nombre", "telefono"):
                valor = _limpiar_texto(valor)
            setattr(cliente, campo, valor)
    cliente.actualizado_por_id = usuario_id
    registrar_evento(
        db,
        usuario_id=usuario_id,
        usuario_nombre=None,
        accion="actualizar",
        modulo="cafeteria",
        entidad="cafeteria_cliente",
        entidad_id=cliente.id,
        datos_anteriores=antes,
        datos_nuevos={
            "nombre": cliente.nombre,
            "contacto_nombre": cliente.contacto_nombre,
            "telefono": cliente.telefono,
            "dias_credito": cliente.dias_credito,
            "activo": cliente.activo,
        },
        commit=False,
    )
    db.commit()
    db.refresh(cliente)
    return cliente


def _resolver_cafeteria(
    db: Session,
    data: CafeteriaVentaCreate,
    usuario_id: int,
) -> CafeteriaCliente:
    if data.cafeteria_id:
        cliente = (
            db.query(CafeteriaCliente)
            .filter(CafeteriaCliente.id == data.cafeteria_id)
            .first()
        )
        if not cliente or not cliente.activo:
            raise ValueError("Cafetería no encontrada")
        antes = {
            "contacto_nombre": cliente.contacto_nombre,
            "telefono": cliente.telefono,
            "dias_credito": cliente.dias_credito,
        }
        cambiado = False
        if data.contacto_nombre and data.contacto_nombre.strip() != (cliente.contacto_nombre or ""):
            cliente.contacto_nombre = data.contacto_nombre.strip()
            cambiado = True
        if data.telefono and data.telefono.strip() != (cliente.telefono or ""):
            cliente.telefono = data.telefono.strip()
            cambiado = True
        if data.dias_credito != cliente.dias_credito:
            cliente.dias_credito = data.dias_credito
            cambiado = True
        if cambiado:
            cliente.actualizado_por_id = usuario_id
            registrar_evento(
                db,
                usuario_id=usuario_id,
                usuario_nombre=None,
                accion="actualizar",
                modulo="cafeteria",
                entidad="cafeteria_cliente",
                entidad_id=cliente.id,
                datos_anteriores=antes,
                datos_nuevos={
                    "contacto_nombre": cliente.contacto_nombre,
                    "telefono": cliente.telefono,
                    "dias_credito": cliente.dias_credito,
                },
                commit=False,
            )
        return cliente

    return crear_cafeteria(
        db,
        CafeteriaClienteCreate(
            nombre=data.cafeteria_nombre,
            contacto_nombre=data.contacto_nombre,
            telefono=data.telefono,
            dias_credito=data.dias_credito,
        ),
        usuario_id,
        commit=False,
    )


def _cargar_venta(db: Session, venta_id: int) -> CafeteriaVenta | None:
    return (
        db.query(CafeteriaVenta)
        .options(
            joinedload(CafeteriaVenta.detalles).joinedload(DetalleCafeteriaVenta.producto),
            joinedload(CafeteriaVenta.pagos),
        )
        .filter(CafeteriaVenta.id == venta_id)
        .first()
    )


def obtener_venta(db: Session, venta_id: int) -> CafeteriaVenta:
    venta = _cargar_venta(db, venta_id)
    if not venta:
        raise ValueError("Venta de cafetería no encontrada")
    return venta


def crear_venta(db: Session, data: CafeteriaVentaCreate, usuario_id: int) -> CafeteriaVenta:
    if data.idempotency_key:
        existente = (
            db.query(CafeteriaVenta)
            .filter(CafeteriaVenta.idempotency_key == data.idempotency_key)
            .first()
        )
        if existente:
            return obtener_venta(db, existente.id)

    cafeteria = _resolver_cafeteria(db, data, usuario_id)
    subtotal_total = Decimal("0")
    iva_0_total = Decimal("0")
    iva_16_total = Decimal("0")
    detalles: list[DetalleCafeteriaVenta] = []
    productos_por_id: dict[int, Producto] = {}

    for item in data.detalles:
        producto = (
            db.query(Producto)
            .filter(Producto.id == item.producto_id)
            .with_for_update()
            .first()
        )
        if not producto:
            raise ValueError(f"Producto ID {item.producto_id} no encontrado")
        if not producto.activo:
            raise ValueError(f"Producto '{producto.nombre}' no está activo")
        productos_por_id[producto.id] = producto

        cantidad = Decimal(str(item.cantidad))
        precio = Decimal(producto.precio_cafeteria or producto.precio_unitario or 0)
        if precio <= 0:
            raise ValueError(f"Producto '{producto.nombre}' no tiene precio de cafetería válido")

        subtotal_linea = _q(precio * cantidad)
        tasa_iva = _obtener_tasa_iva(producto)
        monto_iva = _q(subtotal_linea * tasa_iva)
        subtotal_total += subtotal_linea
        if tasa_iva == Decimal("0.00"):
            iva_0_total += subtotal_linea
        else:
            iva_16_total += monto_iva

        detalles.append(
            DetalleCafeteriaVenta(
                producto_id=producto.id,
                cantidad=cantidad,
                precio_unitario=precio,
                subtotal=subtotal_linea,
                tasa_iva=tasa_iva,
                monto_iva=monto_iva,
            )
        )

    subtotal_total = _q(subtotal_total)
    iva_0_total = _q(iva_0_total)
    iva_16_total = _q(iva_16_total)
    total_impuestos = iva_16_total
    total = _q(subtotal_total + total_impuestos)
    pago_inicial = _q(Decimal(data.pago_inicial or 0))
    if pago_inicial > total:
        raise ValueError("El pago inicial no puede ser mayor al total")

    ahora_local = datetime.now(_zona_operacion())
    fecha = _normalizar_fecha_db(ahora_local)
    dias_credito = data.dias_credito
    fecha_credito = ahora_local.date() + timedelta(days=dias_credito)

    for _attempt in range(3):
        venta = CafeteriaVenta(
            folio=_generar_folio(db),
            idempotency_key=data.idempotency_key,
            cafeteria_id=cafeteria.id,
            cafeteria_nombre=cafeteria.nombre,
            contacto_nombre=_limpiar_texto(data.contacto_nombre) or cafeteria.contacto_nombre,
            telefono=_limpiar_texto(data.telefono) or cafeteria.telefono,
            usuario_id=usuario_id,
            subtotal=subtotal_total,
            iva_0=iva_0_total,
            iva_16=iva_16_total,
            total_impuestos=total_impuestos,
            total=total,
            monto_pagado=pago_inicial,
            estado=_estado_por_montos(total, pago_inicial),
            fecha=fecha,
            dias_credito=dias_credito,
            fecha_credito=fecha_credito,
            notas=data.notas,
        )
        db.add(venta)
        try:
            db.flush()
            break
        except IntegrityError:
            db.rollback()
            if data.idempotency_key:
                existente = (
                    db.query(CafeteriaVenta)
                    .filter(CafeteriaVenta.idempotency_key == data.idempotency_key)
                    .first()
                )
                if existente:
                    return obtener_venta(db, existente.id)
    else:
        raise ValueError("No se pudo generar folio único de cafetería")

    for detalle in detalles:
        producto = productos_por_id.get(detalle.producto_id)
        detalle.venta_id = venta.id
        db.add(detalle)
        registrar_movimiento(
            db,
            MovimientoCreate(
                tipo=TipoMovimiento.SALIDA_VENTA,
                producto_id=detalle.producto_id,
                cantidad=detalle.cantidad,
                referencia=f"Cafetería {venta.folio}",
            ),
            usuario_id,
            commit=False,
            permitir_stock_negativo=True,
        )
        if producto:
            registrar_empaque_producto(
                db,
                producto,
                Decimal(str(detalle.cantidad)),
                referencia=f"Cafetería {venta.folio}",
                usuario_id=usuario_id,
                commit=False,
                permitir_stock_negativo=True,
            )

    if pago_inicial > 0:
        metodo_pago = _normalizar_metodo_terminal(data.metodo_pago, data.terminal)
        db.add(
            PagoCafeteriaVenta(
                venta_id=venta.id,
                monto=pago_inicial,
                metodo_pago=metodo_pago,
                terminal=data.terminal,
                referencia=data.referencia_pago,
                usuario_id=usuario_id,
                fecha=fecha,
            )
        )

    registrar_evento(
        db,
        usuario_id=usuario_id,
        usuario_nombre=None,
        accion="crear",
        modulo="cafeteria",
        entidad="cafeteria_venta",
        entidad_id=venta.id,
        datos_nuevos={
            "folio": venta.folio,
            "cafeteria": venta.cafeteria_nombre,
            "cafeteria_id": cafeteria.id,
            "total": str(total),
            "monto_pagado": str(pago_inicial),
            "estado": venta.estado.value,
            "dias_credito": dias_credito,
            "fecha_credito": fecha_credito.isoformat(),
        },
        commit=False,
    )
    db.commit()
    return obtener_venta(db, venta.id)


def listar_ventas(
    db: Session,
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    estado: EstadoCuentaCafeteria | None = None,
    limit: int = 100,
) -> list[CafeteriaVenta]:
    query = (
        db.query(CafeteriaVenta)
        .options(
            joinedload(CafeteriaVenta.detalles).joinedload(DetalleCafeteriaVenta.producto),
            joinedload(CafeteriaVenta.pagos),
        )
        .order_by(CafeteriaVenta.fecha.desc(), CafeteriaVenta.id.desc())
    )
    if fecha_inicio:
        inicio = _normalizar_fecha_db(datetime.combine(fecha_inicio, time.min, _zona_operacion()))
        query = query.filter(CafeteriaVenta.fecha >= inicio)
    if fecha_fin:
        fin = _normalizar_fecha_db(datetime.combine(fecha_fin, time.max, _zona_operacion()))
        query = query.filter(CafeteriaVenta.fecha <= fin)
    if estado:
        query = query.filter(CafeteriaVenta.estado == estado)
    return query.limit(limit).all()


def registrar_pago(db: Session, venta_id: int, data: PagoCafeteriaCreate, usuario_id: int) -> CafeteriaVenta:
    venta = (
        db.query(CafeteriaVenta)
        .filter(CafeteriaVenta.id == venta_id)
        .with_for_update()
        .first()
    )
    if not venta:
        raise ValueError("Venta de cafetería no encontrada")
    if venta.estado == EstadoCuentaCafeteria.CANCELADA:
        raise ValueError("No se puede pagar una venta cancelada")

    saldo = _q(Decimal(venta.total or 0) - Decimal(venta.monto_pagado or 0))
    if saldo <= 0:
        venta.estado = EstadoCuentaCafeteria.PAGADA
        db.commit()
        return obtener_venta(db, venta.id)

    monto = _q(Decimal(data.monto or saldo))
    if monto <= 0:
        raise ValueError("El pago debe ser mayor a cero")
    if monto > saldo:
        raise ValueError("El pago no puede ser mayor al saldo pendiente")

    antes = {
        "monto_pagado": str(venta.monto_pagado),
        "estado": venta.estado.value,
        "saldo": str(saldo),
    }
    venta.monto_pagado = _q(Decimal(venta.monto_pagado or 0) + monto)
    venta.estado = _estado_por_montos(Decimal(venta.total or 0), Decimal(venta.monto_pagado or 0))
    metodo_pago = _normalizar_metodo_terminal(data.metodo_pago, data.terminal)
    db.add(
        PagoCafeteriaVenta(
            venta_id=venta.id,
            monto=monto,
            metodo_pago=metodo_pago,
            terminal=data.terminal,
            referencia=data.referencia,
            usuario_id=usuario_id,
            fecha=_normalizar_fecha_db(datetime.now(_zona_operacion())),
        )
    )
    registrar_evento(
        db,
        usuario_id=usuario_id,
        usuario_nombre=None,
        accion="pago",
        modulo="cafeteria",
        entidad="cafeteria_venta",
        entidad_id=venta.id,
        datos_anteriores=antes,
        datos_nuevos={
            "monto_pagado": str(venta.monto_pagado),
            "estado": venta.estado.value,
            "pago": str(monto),
            "referencia": data.referencia,
            "motivo": data.motivo or "Registro de pago cafetería",
        },
        commit=False,
    )
    db.commit()
    return obtener_venta(db, venta.id)


def cancelar_venta(db: Session, venta_id: int, usuario_id: int) -> CafeteriaVenta:
    venta = obtener_venta(db, venta_id)
    if venta.estado == EstadoCuentaCafeteria.CANCELADA:
        return venta
    antes = {
        "estado": venta.estado.value,
        "monto_pagado": str(venta.monto_pagado),
        "total": str(venta.total),
    }
    venta.estado = EstadoCuentaCafeteria.CANCELADA
    for detalle in venta.detalles:
        producto = detalle.producto
        registrar_movimiento(
            db,
            MovimientoCreate(
                tipo=TipoMovimiento.ENTRADA_DEVOLUCION,
                producto_id=detalle.producto_id,
                cantidad=detalle.cantidad,
                referencia=f"Cancelación cafetería {venta.folio}",
            ),
            usuario_id,
            commit=False,
            permitir_stock_negativo=True,
        )
        if producto:
            registrar_empaque_producto(
                db,
                producto,
                Decimal(str(detalle.cantidad)),
                referencia=f"Cancelación cafetería {venta.folio}",
                usuario_id=usuario_id,
                tipo=TipoMovimiento.ENTRADA_DEVOLUCION,
                commit=False,
                permitir_stock_negativo=True,
            )
    registrar_evento(
        db,
        usuario_id=usuario_id,
        usuario_nombre=None,
        accion="cancelar",
        modulo="cafeteria",
        entidad="cafeteria_venta",
        entidad_id=venta.id,
        datos_anteriores=antes,
        datos_nuevos={"estado": venta.estado.value},
        commit=False,
    )
    db.commit()
    return obtener_venta(db, venta.id)


def _rango_semana(fecha: date | None = None) -> tuple[date, date]:
    base = fecha or datetime.now(_zona_operacion()).date()
    inicio = base - timedelta(days=base.weekday())
    return inicio, inicio + timedelta(days=6)


def _rango_mes(mes: str | None = None) -> tuple[date, date]:
    if mes:
        anio_s, mes_s = mes.split("-", 1)
        inicio = date(int(anio_s), int(mes_s), 1)
    else:
        hoy = datetime.now(_zona_operacion()).date()
        inicio = date(hoy.year, hoy.month, 1)
    if inicio.month == 12:
        siguiente = date(inicio.year + 1, 1, 1)
    else:
        siguiente = date(inicio.year, inicio.month + 1, 1)
    return inicio, siguiente - timedelta(days=1)


def _reporte(db: Session, inicio: date, fin: date) -> dict:
    ventas = listar_ventas(db, inicio, fin, limit=1000)
    ventas_validas = [v for v in ventas if v.estado != EstadoCuentaCafeteria.CANCELADA]
    total_llevado = _q(sum((Decimal(v.total or 0) for v in ventas_validas), Decimal("0")))
    total_pagado = _q(sum((Decimal(v.monto_pagado or 0) for v in ventas_validas), Decimal("0")))
    por_producto: dict[int, dict] = {}
    por_cafeteria: dict[str, dict] = defaultdict(
        lambda: {
            "cafeteria": "",
            "cafeteria_id": None,
            "entregas": 0,
            "total": Decimal("0"),
            "pagado": Decimal("0"),
            "saldo": Decimal("0"),
        }
    )
    pagos = []
    estados = {"pendiente": 0, "parcial": 0, "pagada": 0}

    for venta in ventas_validas:
        cafe = por_cafeteria[venta.cafeteria_nombre]
        cafe["cafeteria"] = venta.cafeteria_nombre
        cafe["cafeteria_id"] = venta.cafeteria_id
        cafe["entregas"] += 1
        cafe["total"] += Decimal(venta.total or 0)
        cafe["pagado"] += Decimal(venta.monto_pagado or 0)
        cafe["saldo"] += venta.saldo_pendiente
        if venta.estado.value in estados:
            estados[venta.estado.value] += 1
        for detalle in venta.detalles:
            item = por_producto.setdefault(
                detalle.producto_id,
                {
                    "producto_id": detalle.producto_id,
                    "nombre": detalle.producto_nombre or f"Producto #{detalle.producto_id}",
                    "cantidad": Decimal("0"),
                    "total": Decimal("0"),
                },
            )
            item["cantidad"] += Decimal(detalle.cantidad or 0)
            item["total"] += Decimal(detalle.subtotal or 0) + Decimal(detalle.monto_iva or 0)
        for pago in venta.pagos:
            pagos.append({
                "folio": venta.folio,
                "cafeteria_nombre": venta.cafeteria_nombre,
                "fecha": pago.fecha,
                "metodo_pago": pago.metodo_pago.value,
                "terminal": pago.terminal.value,
                "monto": pago.monto,
            })

    return {
        "fecha_inicio": inicio,
        "fecha_fin": fin,
        "total_llevado": total_llevado,
        "total_pagado": total_pagado,
        "saldo_pendiente": _q(total_llevado - total_pagado),
        "estado_cuentas": estados,
        "corte_mensual": {
            "ingreso_reconocido": total_llevado,
            "cobrado": total_pagado,
            "cuentas_por_cobrar": _q(total_llevado - total_pagado),
            "separado_corte_diario_mostrador": True,
        },
        "entregas": ventas_validas,
        "productos": sorted(por_producto.values(), key=lambda p: p["total"], reverse=True),
        "pagos": sorted(pagos, key=lambda p: p["fecha"], reverse=True),
        "por_cafeteria": sorted(por_cafeteria.values(), key=lambda c: c["saldo"], reverse=True),
    }


def reporte_semanal(db: Session, fecha: date | None = None) -> dict:
    inicio, fin = _rango_semana(fecha)
    return _reporte(db, inicio, fin)


def reporte_mensual(db: Session, mes: str | None = None) -> dict:
    inicio, fin = _rango_mes(mes)
    return _reporte(db, inicio, fin)
