"""
Servicio de punto de venta (POS).
Procesa ventas con desglose fiscal correcto de IVA.
Genera tickets conforme a Ley Federal de Protección al Consumidor.
"""

from decimal import Decimal
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from sqlalchemy.exc import IntegrityError

from app.models.venta import Venta, DetalleVenta, PagoVenta, CorteCaja, MetodoPago, EstadoVenta
from app.models.inventario import Producto, TasaIVA, TipoMovimiento
from app.models.cliente import Cliente
from app.schemas.venta import VentaCreate, CorteCajaCreate
from app.schemas.inventario import MovimientoCreate
from app.services.inventario_service import registrar_movimiento
from app.services.auditoria_service import registrar_evento
from app.core.config import settings

# Loyalty: 1 punto por cada $10 MXN gastados, 100 puntos = $50 descuento
PUNTOS_POR_PESO = Decimal("0.1")  # 1 punto por $10
VALOR_PUNTO = Decimal("0.5")      # cada punto vale $0.50
CENTAVO = Decimal("0.01")


def _zona_operacion() -> ZoneInfo:
    try:
        return ZoneInfo(settings.APP_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/Mexico_City")


def _hoy_operacion() -> date:
    return datetime.now(_zona_operacion()).date()


def _normalizar_fecha_db(valor: datetime) -> datetime:
    valor_utc = valor.astimezone(timezone.utc)
    if settings.DATABASE_URL.startswith("sqlite"):
        return valor_utc.replace(tzinfo=None)
    return valor_utc


def _generar_folio(db: Session, serie: str = "T") -> str:
    """Genera folio secuencial por serie."""
    ultima_venta = (
        db.query(Venta)
        .filter(Venta.serie == serie)
        .order_by(Venta.id.desc())
        .first()
    )
    if ultima_venta:
        numero = int(ultima_venta.folio.split("-")[-1]) + 1
    else:
        numero = 1
    return f"{serie}-{numero:08d}"


def _obtener_tasa_iva(producto: Producto) -> Decimal:
    """Determina tasa IVA según tipo de producto."""
    if producto.tasa_iva == TasaIVA.TASA_0:
        return Decimal("0.00")
    elif producto.tasa_iva == TasaIVA.TASA_16:
        if settings.ZONA_FRONTERIZA:
            return Decimal("0.08")
        return Decimal("0.16")
    else:  # Exento
        return Decimal("0.00")


def _aplicar_descuento_global(detalles: list[DetalleVenta], descuento_bruto: Decimal) -> None:
    """Distribuye un descuento con IVA incluido entre partidas."""
    if descuento_bruto <= 0:
        return

    totales_brutos = [d.subtotal + d.monto_iva for d in detalles]
    total_bruto = sum(totales_brutos, Decimal("0"))
    if total_bruto <= 0:
        raise ValueError("No se puede aplicar descuento a una venta sin total")
    if descuento_bruto > total_bruto:
        raise ValueError("El descuento por puntos no puede exceder el total de la venta")

    restante_bruto = descuento_bruto
    for index, detalle in enumerate(detalles):
        if index == len(detalles) - 1:
            descuento_linea_bruto = restante_bruto
        else:
            descuento_linea_bruto = (
                descuento_bruto * (totales_brutos[index] / total_bruto)
            ).quantize(CENTAVO)
            restante_bruto -= descuento_linea_bruto

        divisor = Decimal("1") + detalle.tasa_iva
        descuento_base = (descuento_linea_bruto / divisor).quantize(CENTAVO)
        descuento_base = min(descuento_base, detalle.subtotal)
        if descuento_base <= 0:
            continue

        detalle.descuento += descuento_base
        detalle.subtotal -= descuento_base
        detalle.monto_iva = (detalle.subtotal * detalle.tasa_iva).quantize(CENTAVO)


def _recalcular_totales(
    detalles: list[DetalleVenta],
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    subtotal_total = sum((d.subtotal for d in detalles), Decimal("0")).quantize(CENTAVO)
    descuento_total = sum((d.descuento for d in detalles), Decimal("0")).quantize(CENTAVO)
    iva_0_total = sum(
        (d.subtotal for d in detalles if d.tasa_iva == Decimal("0.00")),
        Decimal("0"),
    ).quantize(CENTAVO)
    iva_16_total = sum(
        (d.monto_iva for d in detalles if d.tasa_iva != Decimal("0.00")),
        Decimal("0"),
    ).quantize(CENTAVO)
    total_impuestos = iva_16_total
    return subtotal_total, descuento_total, iva_0_total, iva_16_total, total_impuestos


def procesar_venta(db: Session, data: VentaCreate, usuario_id: int) -> Venta:
    """
    Procesa una venta completa:
    1. Valida productos activos
    2. Calcula IVA por partida (0% o 16%)
    3. Descuenta inventario
    4. Genera ticket
    """
    if data.idempotency_key:
        venta_existente = db.query(Venta).filter(
            Venta.idempotency_key == data.idempotency_key
        ).first()
        if venta_existente:
            return venta_existente

    cliente_lealtad = None
    if data.cliente_id:
        cliente_lealtad = db.query(Cliente).filter(
            Cliente.id == data.cliente_id
        ).with_for_update().first()
        if not cliente_lealtad:
            raise ValueError("Cliente no encontrado")
    if data.puntos_canjeados:
        if not cliente_lealtad:
            raise ValueError("El canje de puntos requiere cliente asociado")
        if data.puntos_canjeados > cliente_lealtad.puntos_acumulados:
            raise ValueError(
                "Puntos insuficientes: tiene "
                f"{cliente_lealtad.puntos_acumulados}, pidió {data.puntos_canjeados}"
            )

    subtotal_total = Decimal("0")
    descuento_total = Decimal("0")
    iva_0_total = Decimal("0")
    iva_16_total = Decimal("0")

    detalles = []
    stock_por_producto: dict[int, dict] = {}

    for item in data.detalles:
        producto = db.query(Producto).filter(
            Producto.id == item.producto_id
        ).with_for_update().first()
        if not producto:
            raise ValueError(f"Producto ID {item.producto_id} no encontrado")
        if not producto.activo:
            raise ValueError(f"Producto '{producto.nombre}' no está activo")
        stock_antes = Decimal(str(producto.stock_actual or 0))
        cantidad_solicitada = Decimal(str(item.cantidad))
        stock_info = stock_por_producto.setdefault(
            producto.id,
            {
                "producto_id": producto.id,
                "producto": producto.nombre,
                "stock_antes": stock_antes,
                "cantidad_vendida": Decimal("0"),
            },
        )
        stock_info["cantidad_vendida"] += cantidad_solicitada

        precio = producto.precio_unitario
        subtotal_linea = (precio * item.cantidad) - item.descuento
        tasa_iva = _obtener_tasa_iva(producto)
        monto_iva = (subtotal_linea * tasa_iva).quantize(Decimal("0.01"))

        subtotal_total += subtotal_linea
        descuento_total += item.descuento

        if tasa_iva == Decimal("0.00"):
            iva_0_total += subtotal_linea  # Base gravable a 0%
        else:
            iva_16_total += monto_iva

        detalle = DetalleVenta(
            producto_id=producto.id,
            cantidad=item.cantidad,
            precio_unitario=precio,
            descuento=item.descuento,
            subtotal=subtotal_linea,
            clave_prod_serv_sat=producto.clave_prod_serv_sat,
            clave_unidad_sat=producto.clave_unidad_sat,
            tasa_iva=tasa_iva,
            monto_iva=monto_iva,
            objeto_impuesto=producto.objeto_impuesto,
        )
        detalles.append(detalle)

    if data.puntos_canjeados:
        descuento_puntos = Decimal(str(data.puntos_canjeados)) * VALOR_PUNTO
        _aplicar_descuento_global(detalles, descuento_puntos)
        subtotal_total, descuento_total, iva_0_total, iva_16_total, total_impuestos = (
            _recalcular_totales(detalles)
        )
    else:
        total_impuestos = iva_16_total
    total = subtotal_total + total_impuestos

    # Validar pago
    cambio = Decimal("0")
    monto_recibido = data.monto_recibido
    metodo_principal = data.metodo_pago

    if data.pagos:
        # Split payment: validate sum covers total
        suma_pagos = sum(p.monto for p in data.pagos)
        if suma_pagos < total:
            raise ValueError(
                f"Suma de pagos ({suma_pagos}) menor al total ({total})"
            )
        # Set monto_recibido to sum, cambio from cash portion
        monto_recibido = suma_pagos
        efectivo_recibido = sum(
            p.monto for p in data.pagos if p.metodo_pago == MetodoPago.EFECTIVO
        )
        no_efectivo = suma_pagos - efectivo_recibido
        # Change = cash given - (total - card/transfer portion)
        parte_efectivo = total - no_efectivo
        if efectivo_recibido > 0 and parte_efectivo > 0:
            cambio = efectivo_recibido - parte_efectivo
        elif efectivo_recibido > total:
            cambio = efectivo_recibido - total
        # Primary method = largest payment
        metodo_principal = max(data.pagos, key=lambda p: p.monto).metodo_pago
    else:
        # Single payment
        if data.metodo_pago == MetodoPago.EFECTIVO:
            if data.monto_recibido < total:
                raise ValueError(
                    f"Monto recibido ({data.monto_recibido}) menor al total ({total})"
                )
            cambio = data.monto_recibido - total

    # Retry folio generation to handle race conditions
    for _attempt in range(3):
        folio = _generar_folio(db, "T")
        venta = Venta(
            folio=folio,
            serie="T",
            idempotency_key=data.idempotency_key,
            cliente_id=data.cliente_id,
            usuario_id=usuario_id,
            subtotal=subtotal_total,
            descuento=descuento_total,
            iva_0=iva_0_total,
            iva_16=iva_16_total,
            total_impuestos=total_impuestos,
            total=total,
            metodo_pago=metodo_principal,
            forma_pago=data.forma_pago,
            monto_recibido=monto_recibido,
            cambio=cambio,
            notas=data.notas,
        )
        db.add(venta)
        try:
            db.flush()
            break
        except IntegrityError:
            db.rollback()
            if data.idempotency_key:
                venta_existente = db.query(Venta).filter(
                    Venta.idempotency_key == data.idempotency_key
                ).first()
                if venta_existente:
                    return venta_existente
    else:
        raise ValueError("No se pudo generar un folio único, intente de nuevo")

    productos_sin_stock = []
    for stock_info in stock_por_producto.values():
        stock_despues = stock_info["stock_antes"] - stock_info["cantidad_vendida"]
        if stock_despues < 0:
            productos_sin_stock.append({
                "producto_id": stock_info["producto_id"],
                "producto": stock_info["producto"],
                "stock_antes": str(stock_info["stock_antes"]),
                "cantidad_vendida": str(stock_info["cantidad_vendida"]),
                "stock_despues": str(stock_despues),
            })

    # Agregar detalles
    for detalle in detalles:
        detalle.venta_id = venta.id
        db.add(detalle)

    if data.puntos_canjeados and cliente_lealtad:
        from app.models.lealtad import HistorialPuntos

        saldo_anterior = cliente_lealtad.puntos_acumulados
        cliente_lealtad.puntos_acumulados -= data.puntos_canjeados
        db.add(HistorialPuntos(
            cliente_id=cliente_lealtad.id,
            puntos=-data.puntos_canjeados,
            concepto=f"Canje en venta {folio}",
            venta_id=venta.id,
            saldo_anterior=saldo_anterior,
            saldo_nuevo=cliente_lealtad.puntos_acumulados,
        ))

    # Agregar pagos (split payment records)
    if data.pagos:
        for pago_data in data.pagos:
            pago = PagoVenta(
                venta_id=venta.id,
                metodo_pago=pago_data.metodo_pago,
                monto=pago_data.monto,
                referencia=pago_data.referencia,
            )
            db.add(pago)

    # Descontar inventario
    for item in data.detalles:
        mov = MovimientoCreate(
            tipo=TipoMovimiento.SALIDA_VENTA,
            producto_id=item.producto_id,
            cantidad=item.cantidad,
            referencia=f"Venta {folio}",
        )
        registrar_movimiento(
            db,
            mov,
            usuario_id,
            commit=False,
            permitir_stock_negativo=True,
        )

    if productos_sin_stock:
        registrar_evento(
            db,
            usuario_id=usuario_id,
            usuario_nombre=None,
            accion="venta_stock_negativo",
            modulo="ventas",
            entidad="ventas",
            entidad_id=venta.id,
            datos_anteriores={
                "productos": [
                    {
                        "producto_id": item["producto_id"],
                        "producto": item["producto"],
                        "stock": item["stock_antes"],
                    }
                    for item in productos_sin_stock
                ],
            },
            datos_nuevos={
                "folio": folio,
                "productos": productos_sin_stock,
            },
            commit=False,
        )

    # Acumular puntos de lealtad si hay cliente asociado
    if venta.cliente_id:
        from app.services.lealtad_service import acumular_puntos
        acumular_puntos(db, venta.cliente_id, venta.id, total)

    db.commit()
    db.refresh(venta)
    return venta


def cancelar_venta(db: Session, venta_id: int, usuario_id: int) -> Venta:
    """Cancela una venta y devuelve el inventario."""
    venta = db.query(Venta).filter(Venta.id == venta_id).first()
    if not venta:
        raise ValueError("Venta no encontrada")
    if venta.estado == EstadoVenta.CANCELADA:
        raise ValueError("La venta ya está cancelada")

    estado_anterior = venta.estado.value
    puntos_revertidos = 0
    puntos_restaurados = 0
    puntos_antes = None
    puntos_despues = None

    venta.estado = EstadoVenta.CANCELADA

    # Devolver inventario
    for detalle in venta.detalles:
        mov = MovimientoCreate(
            tipo=TipoMovimiento.ENTRADA_DEVOLUCION,
            producto_id=detalle.producto_id,
            cantidad=detalle.cantidad,
            referencia=f"Cancelación venta {venta.folio}",
        )
        registrar_movimiento(db, mov, usuario_id, commit=False)

    if venta.cliente_id:
        from app.models.lealtad import HistorialPuntos
        from app.services.lealtad_service import calcular_nivel

        cliente = db.query(Cliente).filter(
            Cliente.id == venta.cliente_id
        ).with_for_update().first()
        if cliente:
            puntos_antes = cliente.puntos_acumulados
            puntos_generados = db.query(func.coalesce(func.sum(HistorialPuntos.puntos), 0)).filter(
                HistorialPuntos.cliente_id == cliente.id,
                HistorialPuntos.venta_id == venta.id,
                HistorialPuntos.puntos > 0,
                HistorialPuntos.concepto.like("Compra%"),
            ).scalar()
            puntos_canjeados = db.query(func.coalesce(func.sum(HistorialPuntos.puntos), 0)).filter(
                HistorialPuntos.cliente_id == cliente.id,
                HistorialPuntos.venta_id == venta.id,
                HistorialPuntos.puntos < 0,
            ).scalar()
            puntos_revertidos = int(puntos_generados or int(venta.total * PUNTOS_POR_PESO))
            puntos_restaurados = abs(int(puntos_canjeados or 0))
            saldo_actual = cliente.puntos_acumulados
            cliente.puntos_totales_historicos = max(
                0,
                cliente.puntos_totales_historicos - puntos_revertidos,
            )
            cliente.nivel_lealtad = calcular_nivel(cliente.puntos_totales_historicos).value
            if puntos_revertidos:
                saldo_despues_reversion = saldo_actual - puntos_revertidos
                db.add(HistorialPuntos(
                    cliente_id=cliente.id,
                    puntos=-puntos_revertidos,
                    concepto=f"Cancelación venta {venta.folio}",
                    venta_id=venta.id,
                    saldo_anterior=saldo_actual,
                    saldo_nuevo=saldo_despues_reversion,
                ))
                saldo_actual = saldo_despues_reversion
            if puntos_restaurados:
                saldo_despues_restauracion = saldo_actual + puntos_restaurados
                db.add(HistorialPuntos(
                    cliente_id=cliente.id,
                    puntos=puntos_restaurados,
                    concepto=f"Restauración canje venta {venta.folio}",
                    venta_id=venta.id,
                    saldo_anterior=saldo_actual,
                    saldo_nuevo=saldo_despues_restauracion,
                ))
                saldo_actual = saldo_despues_restauracion
            cliente.puntos_acumulados = saldo_actual
            puntos_despues = cliente.puntos_acumulados

    registrar_evento(
        db,
        usuario_id=usuario_id,
        usuario_nombre=None,
        accion="cancelar",
        modulo="ventas",
        entidad="ventas",
        entidad_id=venta.id,
        datos_anteriores={
            "estado": estado_anterior,
            "cliente_id": venta.cliente_id,
            "puntos_acumulados": puntos_antes,
        },
        datos_nuevos={
            "estado": EstadoVenta.CANCELADA.value,
            "puntos_revertidos": puntos_revertidos,
            "puntos_restaurados": puntos_restaurados,
            "puntos_acumulados": puntos_despues,
        },
        commit=False,
    )

    db.commit()
    db.refresh(venta)
    return venta


def obtener_venta(db: Session, venta_id: int) -> Venta:
    venta = db.query(Venta).filter(Venta.id == venta_id).first()
    if not venta:
        raise ValueError("Venta no encontrada")
    return venta


def listar_ventas(
    db: Session,
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    limit: int = 100,
):
    query = db.query(Venta)
    if fecha_inicio:
        query = query.filter(Venta.fecha >= datetime.combine(fecha_inicio, datetime.min.time()))
    if fecha_fin:
        query = query.filter(Venta.fecha <= datetime.combine(fecha_fin, datetime.max.time()))
    return query.order_by(Venta.fecha.desc()).limit(limit).all()


def generar_ticket(db: Session, venta_id: int) -> dict:
    """
    Genera datos del ticket de venta.
    Cumple Ley Federal de Protección al Consumidor:
    - Razón social y RFC del negocio
    - Desglose de productos con precio
    - Desglose de IVA
    - Fecha y folio
    """
    venta = obtener_venta(db, venta_id)
    productos = []
    for d in venta.detalles:
        prod = db.query(Producto).filter(Producto.id == d.producto_id).first()
        productos.append({
            "nombre": prod.nombre if prod else "Producto",
            "cantidad": float(d.cantidad),
            "precio_unitario": float(d.precio_unitario),
            "subtotal": float(d.subtotal),
            "iva": float(d.monto_iva),
        })

    metodo_pago_desc = {
        "01": "Efectivo", "04": "Tarjeta de crédito",
        "28": "Tarjeta de débito", "03": "Transferencia",
    }

    # Build payment description
    pagos_info = []
    if venta.pagos:
        for p in venta.pagos:
            desc = metodo_pago_desc.get(p.metodo_pago.value, "Otro")
            pagos_info.append({"metodo": desc, "monto": float(p.monto)})
    metodo_str = metodo_pago_desc.get(venta.metodo_pago.value, "Otro")
    if pagos_info and len(pagos_info) > 1:
        metodo_str = " + ".join(f"{p['metodo']} ${p['monto']:,.2f}" for p in pagos_info)

    return {
        "razon_social": settings.RAZON_SOCIAL,
        "rfc": settings.RFC,
        "direccion": f"C.P. {settings.DOMICILIO_FISCAL_CP}",
        "folio": venta.folio,
        "fecha": venta.fecha.strftime("%d/%m/%Y %H:%M:%S"),
        "cajero": f"Usuario #{venta.usuario_id}",
        "productos": productos,
        "subtotal": f"${venta.subtotal:,.2f}",
        "iva": f"${venta.total_impuestos:,.2f}",
        "total": f"${venta.total:,.2f}",
        "metodo_pago": metodo_str,
        "pagos": pagos_info,
        "monto_recibido": f"${venta.monto_recibido:,.2f}",
        "cambio": f"${venta.cambio:,.2f}",
        "leyenda_fiscal": (
            "Este ticket NO es un comprobante fiscal. "
            "Solicite su factura en los 30 días siguientes."
        ),
    }


# --- Corte de caja ---

def _rango_dia_corte(fecha: date) -> tuple[datetime, datetime]:
    zona = _zona_operacion()
    return (
        _normalizar_fecha_db(datetime.combine(fecha, datetime.min.time(), tzinfo=zona)),
        _normalizar_fecha_db(datetime.combine(fecha, datetime.max.time(), tzinfo=zona)),
    )


def _totales_corte(db: Session, fecha: date) -> dict:
    inicio, fin = _rango_dia_corte(fecha)

    ventas = db.query(Venta).filter(
        and_(
            Venta.fecha >= inicio,
            Venta.fecha <= fin,
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).all()

    # Calculate totals by payment method, considering split payments
    total_efectivo = Decimal("0")
    total_tarjeta = Decimal("0")
    total_transferencia = Decimal("0")
    for v in ventas:
        if v.pagos:
            # Split payment: sum each method's portion
            for p in v.pagos:
                if p.metodo_pago == MetodoPago.EFECTIVO:
                    total_efectivo += p.monto
                elif p.metodo_pago in (MetodoPago.TARJETA_CREDITO, MetodoPago.TARJETA_DEBITO):
                    total_tarjeta += p.monto
                elif p.metodo_pago == MetodoPago.TRANSFERENCIA:
                    total_transferencia += p.monto
        else:
            # Single payment
            if v.metodo_pago == MetodoPago.EFECTIVO:
                total_efectivo += v.total
            elif v.metodo_pago in (MetodoPago.TARJETA_CREDITO, MetodoPago.TARJETA_DEBITO):
                total_tarjeta += v.total
            elif v.metodo_pago == MetodoPago.TRANSFERENCIA:
                total_transferencia += v.total
    total_ventas = total_efectivo + total_tarjeta + total_transferencia

    cancelaciones = db.query(func.count(Venta.id)).filter(
        and_(
            Venta.fecha >= inicio,
            Venta.fecha <= fin,
            Venta.estado == EstadoVenta.CANCELADA,
        )
    ).scalar() or 0

    corte_existente = db.query(CorteCaja).filter(
        CorteCaja.fecha >= inicio,
        CorteCaja.fecha <= fin,
    ).order_by(CorteCaja.fecha.desc()).first()

    return {
        "fecha": fecha,
        "inicio": inicio,
        "fin": fin,
        "ventas": ventas,
        "total_efectivo": total_efectivo,
        "total_tarjeta": total_tarjeta,
        "total_transferencia": total_transferencia,
        "total_ventas": total_ventas,
        "numero_ventas": len(ventas),
        "numero_cancelaciones": int(cancelaciones),
        "corte_existente": corte_existente,
    }


def resumen_corte_caja(db: Session, fecha: date | None = None) -> dict:
    """Resumen calculado antes de registrar el corte."""
    dia = fecha or _hoy_operacion()
    totales = _totales_corte(db, dia)
    corte_existente = totales["corte_existente"]
    return {
        "fecha": dia.isoformat(),
        "total_ventas_efectivo": totales["total_efectivo"],
        "total_ventas_tarjeta": totales["total_tarjeta"],
        "total_ventas_transferencia": totales["total_transferencia"],
        "total_ventas": totales["total_ventas"],
        "efectivo_esperado_base": totales["total_efectivo"],
        "numero_ventas": totales["numero_ventas"],
        "numero_cancelaciones": totales["numero_cancelaciones"],
        "corte_existente": corte_existente is not None,
        "corte_id": corte_existente.id if corte_existente else None,
    }


def realizar_corte_caja(db: Session, data: CorteCajaCreate, usuario_id: int) -> CorteCaja:
    """Realiza corte de caja del día."""
    totales = _totales_corte(db, _hoy_operacion())
    if totales["corte_existente"] and not data.permitir_repetir:
        raise ValueError("Ya existe un corte de caja registrado para hoy")

    efectivo_esperado = data.fondo_inicial + totales["total_efectivo"]
    diferencia = data.efectivo_real - efectivo_esperado
    if abs(diferencia) >= Decimal("1") and not (data.notas or "").strip():
        raise ValueError("Agrega una nota explicando la diferencia de caja")

    corte = CorteCaja(
        usuario_id=usuario_id,
        fecha=datetime.now(timezone.utc),
        fondo_inicial=data.fondo_inicial,
        total_ventas_efectivo=totales["total_efectivo"],
        total_ventas_tarjeta=totales["total_tarjeta"],
        total_ventas_transferencia=totales["total_transferencia"],
        total_ventas=totales["total_ventas"],
        efectivo_esperado=efectivo_esperado,
        efectivo_real=data.efectivo_real,
        diferencia=diferencia,
        numero_ventas=totales["numero_ventas"],
        numero_cancelaciones=totales["numero_cancelaciones"],
        notas=data.notas,
    )
    db.add(corte)
    db.flush()
    registrar_evento(
        db,
        usuario_id=usuario_id,
        usuario_nombre=None,
        accion="crear",
        modulo="corte",
        entidad="corte_caja",
        entidad_id=corte.id,
        datos_nuevos={
            "fondo_inicial": data.fondo_inicial,
            "total_ventas_efectivo": totales["total_efectivo"],
            "total_ventas_tarjeta": totales["total_tarjeta"],
            "total_ventas_transferencia": totales["total_transferencia"],
            "total_ventas": totales["total_ventas"],
            "efectivo_esperado": efectivo_esperado,
            "efectivo_real": data.efectivo_real,
            "diferencia": diferencia,
            "numero_ventas": totales["numero_ventas"],
            "numero_cancelaciones": totales["numero_cancelaciones"],
            "notas": data.notas,
        },
        commit=False,
    )
    db.commit()
    db.refresh(corte)
    return corte
