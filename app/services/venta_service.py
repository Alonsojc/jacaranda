"""
Servicio de punto de venta (POS).
Procesa ventas con desglose fiscal correcto de IVA.
Genera tickets conforme a Ley Federal de Protección al Consumidor.
"""

from decimal import Decimal
from datetime import datetime, timezone, date
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.models.venta import Venta, DetalleVenta, CorteCaja, MetodoPago, EstadoVenta
from app.models.inventario import Producto, TasaIVA, TipoMovimiento
from app.schemas.venta import VentaCreate, CorteCajaCreate
from app.schemas.inventario import MovimientoCreate
from app.services.inventario_service import registrar_movimiento
from app.core.config import settings


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


def procesar_venta(db: Session, data: VentaCreate, usuario_id: int) -> Venta:
    """
    Procesa una venta completa:
    1. Valida productos y stock
    2. Calcula IVA por partida (0% o 16%)
    3. Descuenta inventario
    4. Genera ticket
    """
    folio = _generar_folio(db)
    subtotal_total = Decimal("0")
    descuento_total = Decimal("0")
    iva_0_total = Decimal("0")
    iva_16_total = Decimal("0")

    detalles = []

    for item in data.detalles:
        producto = db.query(Producto).filter(Producto.id == item.producto_id).first()
        if not producto:
            raise ValueError(f"Producto ID {item.producto_id} no encontrado")
        if not producto.activo:
            raise ValueError(f"Producto '{producto.nombre}' no está activo")
        if producto.stock_actual < item.cantidad:
            raise ValueError(
                f"Stock insuficiente de '{producto.nombre}': "
                f"disponible {producto.stock_actual}, solicitado {item.cantidad}"
            )

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

    total_impuestos = iva_16_total
    total = subtotal_total + total_impuestos

    # Validar pago
    cambio = Decimal("0")
    if data.metodo_pago == MetodoPago.EFECTIVO:
        if data.monto_recibido < total:
            raise ValueError(
                f"Monto recibido ({data.monto_recibido}) menor al total ({total})"
            )
        cambio = data.monto_recibido - total

    venta = Venta(
        folio=folio,
        serie="T",
        cliente_id=data.cliente_id,
        usuario_id=usuario_id,
        subtotal=subtotal_total,
        descuento=descuento_total,
        iva_0=iva_0_total,
        iva_16=iva_16_total,
        total_impuestos=total_impuestos,
        total=total,
        metodo_pago=data.metodo_pago,
        forma_pago=data.forma_pago,
        monto_recibido=data.monto_recibido,
        cambio=cambio,
        notas=data.notas,
    )
    db.add(venta)
    db.flush()

    # Agregar detalles
    for detalle in detalles:
        detalle.venta_id = venta.id
        db.add(detalle)

    # Descontar inventario
    for item in data.detalles:
        mov = MovimientoCreate(
            tipo=TipoMovimiento.SALIDA_VENTA,
            producto_id=item.producto_id,
            cantidad=item.cantidad,
            referencia=f"Venta {folio}",
        )
        registrar_movimiento(db, mov, usuario_id)

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

    venta.estado = EstadoVenta.CANCELADA

    # Devolver inventario
    for detalle in venta.detalles:
        mov = MovimientoCreate(
            tipo=TipoMovimiento.ENTRADA_DEVOLUCION,
            producto_id=detalle.producto_id,
            cantidad=detalle.cantidad,
            referencia=f"Cancelación venta {venta.folio}",
        )
        registrar_movimiento(db, mov, usuario_id)

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
        "metodo_pago": metodo_pago_desc.get(venta.metodo_pago.value, "Otro"),
        "monto_recibido": f"${venta.monto_recibido:,.2f}",
        "cambio": f"${venta.cambio:,.2f}",
        "leyenda_fiscal": (
            "Este ticket NO es un comprobante fiscal. "
            "Solicite su factura en los 30 días siguientes."
        ),
    }


# --- Corte de caja ---

def realizar_corte_caja(db: Session, data: CorteCajaCreate, usuario_id: int) -> CorteCaja:
    """Realiza corte de caja del día."""
    hoy_inicio = datetime.combine(date.today(), datetime.min.time())
    hoy_fin = datetime.combine(date.today(), datetime.max.time())

    ventas_hoy = db.query(Venta).filter(
        and_(
            Venta.fecha >= hoy_inicio,
            Venta.fecha <= hoy_fin,
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).all()

    total_efectivo = sum(
        v.total for v in ventas_hoy if v.metodo_pago == MetodoPago.EFECTIVO
    )
    total_tarjeta = sum(
        v.total for v in ventas_hoy
        if v.metodo_pago in (MetodoPago.TARJETA_CREDITO, MetodoPago.TARJETA_DEBITO)
    )
    total_transferencia = sum(
        v.total for v in ventas_hoy if v.metodo_pago == MetodoPago.TRANSFERENCIA
    )
    total_ventas = total_efectivo + total_tarjeta + total_transferencia

    cancelaciones = db.query(func.count(Venta.id)).filter(
        and_(
            Venta.fecha >= hoy_inicio,
            Venta.fecha <= hoy_fin,
            Venta.estado == EstadoVenta.CANCELADA,
        )
    ).scalar() or 0

    efectivo_esperado = data.fondo_inicial + total_efectivo
    diferencia = data.efectivo_real - efectivo_esperado

    corte = CorteCaja(
        usuario_id=usuario_id,
        fecha=datetime.now(timezone.utc),
        fondo_inicial=data.fondo_inicial,
        total_ventas_efectivo=total_efectivo,
        total_ventas_tarjeta=total_tarjeta,
        total_ventas_transferencia=total_transferencia,
        total_ventas=total_ventas,
        efectivo_esperado=efectivo_esperado,
        efectivo_real=data.efectivo_real,
        diferencia=diferencia,
        numero_ventas=len(ventas_hoy),
        numero_cancelaciones=cancelaciones,
        notas=data.notas,
    )
    db.add(corte)
    db.commit()
    db.refresh(corte)
    return corte
