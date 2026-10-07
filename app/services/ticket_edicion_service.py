"""Atomic, audited corrections of completed, non-fiscal POS tickets."""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.inventario import Producto, TipoMovimiento
from app.models.venta import EstadoVenta, MetodoPago, Venta
from app.schemas.inventario import MovimientoCreate
from app.schemas.venta import VentaEdicion, VentaResponse
from app.services.auditoria_service import registrar_evento
from app.services.inventario_service import registrar_empaque_producto, registrar_movimiento
from app.services.venta_service import (
    CENTAVO, _cortes_cerrados_del_dia, _fecha_hora_operacion, _normalizar_fecha_db,
    _rango_dia_corte, _recalcular_totales, bloquear_venta_y_caja, obtener_venta,
)


class EdicionDesactualizada(ValueError):
    pass


def _bloqueo_edicion(db: Session, venta: Venta) -> str | None:
    if venta.estado != EstadoVenta.COMPLETADA:
        return "Solo se puede editar un ticket de venta completada"
    if venta.facturada or venta.cfdi is not None:
        return "Este ticket tiene un comprobante fiscal; no se puede editar"
    if venta.pago_integrado or venta.pago_externo_id or any(p.pago_externo_id for p in venta.pagos):
        return "Este ticket tiene un pago integrado; corrige el pago desde su flujo original"
    if venta.canal != "mostrador":
        return "Solo se pueden corregir tickets de mostrador"
    if venta.recompensa_lealtad_canjeada:
        return "Este ticket canjeo una recompensa; requiere cancelar y registrar la venta correcta"
    fecha = _fecha_hora_operacion(venta.fecha).date()
    momento = _normalizar_fecha_db(venta.fecha)
    inicio_dia, fin_dia = _rango_dia_corte(fecha)
    for corte in _cortes_cerrados_del_dia(db, fecha):
        inicio = _normalizar_fecha_db(corte.periodo_inicio) if corte.periodo_inicio else inicio_dia
        fin = _normalizar_fecha_db(corte.periodo_fin) if corte.periodo_fin else fin_dia
        pertenece = inicio < momento <= fin if (corte.turno or 1) > 1 else inicio <= momento <= fin
        if pertenece:
            return f"Reabre primero el corte de caja #{corte.id} que incluye este ticket"
    return None


def _bloqueo_precios(venta: Venta) -> str | None:
    if venta.cliente_id:
        return "Este ticket tiene lealtad de cliente; para cambiar el importe cancela y registra la venta correcta"
    if len(venta.pagos) > 1:
        return "Este ticket tiene pago dividido; para cambiar el importe cancela y registra la venta correcta"
    if any(p.estado != "pagado" for p in venta.pagos):
        return "El pago del ticket no esta confirmado"
    return None


def contexto_edicion(db: Session, venta_id: int) -> dict:
    venta = obtener_venta(db, venta_id)
    bloqueo = _bloqueo_edicion(db, venta)
    productos = [] if bloqueo else db.query(Producto).filter(Producto.activo.is_(True)).order_by(Producto.nombre).all()
    return {
        "venta": VentaResponse.model_validate(venta).model_dump(mode="json"),
        "productos": [{"id": p.id, "nombre": p.nombre} for p in productos],
        "bloqueo": bloqueo,
        "bloqueo_precios": _bloqueo_precios(venta),
    }


def _datos_ticket(venta: Venta) -> dict:
    return VentaResponse.model_validate(venta).model_dump(mode="json")


def editar_ticket(db: Session, venta_id: int, data: VentaEdicion, usuario_id: int) -> Venta:
    try:
        # Lock the sale before loading its collections (outer joins cannot be locked on PostgreSQL).
        venta = bloquear_venta_y_caja(db, venta_id)
        bloqueo = _bloqueo_edicion(db, venta)
        if bloqueo:
            raise ValueError(bloqueo)
        if venta.edicion_revision != data.revision:
            raise EdicionDesactualizada("Este ticket ya cambio. Cierra el editor y vuelve a abrirlo")
        if data.modo == "precios" and (bloqueo := _bloqueo_precios(venta)):
            raise ValueError(bloqueo)
        detalles = {d.id: d for d in venta.detalles}
        if any(item.id not in detalles for item in data.detalles):
            raise ValueError("Una partida no pertenece a este ticket")
        anterior = _datos_ticket(venta)
        if data.modo == "productos":
            cambios = [(detalles[i.id], i.producto_id) for i in data.detalles if detalles[i.id].producto_id != i.producto_id]
            if not cambios:
                raise ValueError("No hay cambios de producto")
            ids = {pid for d, pid in cambios} | {d.producto_id for d, _ in cambios}
            productos = {p.id: p for p in db.query(Producto).filter(Producto.id.in_(ids)).order_by(Producto.id)
                         .populate_existing().with_for_update().all()}
            for _, pid in cambios:
                if pid not in productos or not productos[pid].activo:
                    raise ValueError("El producto elegido no existe o esta inactivo")
            # Return every original item first, so exchanging two lines needs no extra stock.
            for tipo in (TipoMovimiento.ENTRADA_DEVOLUCION, TipoMovimiento.SALIDA_VENTA):
                for detalle, pid in cambios:
                    producto = productos[detalle.producto_id if tipo == TipoMovimiento.ENTRADA_DEVOLUCION else pid]
                    registrar_movimiento(db, MovimientoCreate(
                        tipo=tipo, producto_id=producto.id, cantidad=detalle.cantidad,
                        referencia=f"Correccion {venta.folio}", notas=data.motivo,
                    ), usuario_id, commit=False, permitir_stock_negativo=tipo == TipoMovimiento.ENTRADA_DEVOLUCION)
                    registrar_empaque_producto(db, producto, detalle.cantidad, f"Correccion {venta.folio}",
                                               usuario_id, tipo=tipo, commit=False,
                                               permitir_stock_negativo=tipo == TipoMovimiento.ENTRADA_DEVOLUCION)
            for detalle, pid in cambios:
                producto = productos[pid]
                detalle.producto_id = pid
                detalle.producto = producto
                detalle.clave_prod_serv_sat = producto.clave_prod_serv_sat
                detalle.clave_unidad_sat = producto.clave_unidad_sat
        else:
            if all(detalles[i.id].precio_unitario == i.precio_unitario for i in data.detalles):
                raise ValueError("No hay cambios de precio")
            for item in data.detalles:
                detalle = detalles[item.id]
                base = (item.precio_unitario * detalle.cantidad - detalle.descuento).quantize(CENTAVO)
                if base < 0:
                    raise ValueError("El precio no puede ser menor que el descuento registrado")
                detalle.precio_unitario = item.precio_unitario
                detalle.subtotal = base
                detalle.monto_iva = (base * detalle.tasa_iva).quantize(CENTAVO)
            venta.subtotal, venta.descuento, venta.iva_0, venta.iva_16, venta.total_impuestos = _recalcular_totales(venta.detalles)
            venta.total = (venta.subtotal + venta.total_impuestos + venta.ieps).quantize(CENTAVO)
            if venta.total > Decimal("999999999999.99"):
                raise ValueError("El total excede el limite del ticket")
            if venta.metodo_pago == MetodoPago.EFECTIVO:
                recibido = data.monto_recibido if data.monto_recibido is not None else venta.monto_recibido
                if recibido < venta.total:
                    raise ValueError("El efectivo recibido no alcanza para el total corregido")
                venta.monto_recibido = recibido
                venta.cambio = (recibido - venta.total).quantize(CENTAVO)
            else:
                if "monto_recibido" in data.model_fields_set:
                    raise ValueError("Solo se puede corregir efectivo recibido en un pago en efectivo")
                venta.monto_recibido = venta.total
                venta.cambio = Decimal("0")
            if venta.pagos:
                venta.pagos[0].monto = venta.total
        venta.edicion_revision += 1
        db.flush()
        registrar_evento(db, usuario_id=usuario_id, usuario_nombre=None, accion="editar_ticket", modulo="pos",
                         entidad="ventas", entidad_id=venta.id, datos_anteriores=anterior,
                         datos_nuevos={**_datos_ticket(venta), "modo": data.modo}, motivo=data.motivo, commit=False)
        db.commit()
        return obtener_venta(db, venta_id)
    except Exception:
        db.rollback()
        raise
