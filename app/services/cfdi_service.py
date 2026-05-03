"""
Servicio de facturación electrónica CFDI 4.0.
Genera XML conforme a especificaciones del SAT.
Nota: El timbrado requiere integración con un PAC (Proveedor Autorizado de Certificación).
"""

from decimal import Decimal
from datetime import datetime, timezone
from html import escape
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.facturacion import (
    CFDIComprobante, CFDIConcepto, EstadoCFDI, TipoComprobante,
)
from app.models.venta import Venta, EstadoVenta
from app.models.cliente import Cliente
from app.schemas.facturacion import CFDIGenerarRequest, CFDICancelRequest
from app.core.config import settings


def _generar_folio_cfdi(db: Session, serie: str = "A") -> str:
    ultimo = (
        db.query(CFDIComprobante)
        .filter(CFDIComprobante.serie == serie)
        .order_by(CFDIComprobante.id.desc())
        .first()
    )
    if ultimo:
        numero = int(ultimo.folio) + 1
    else:
        numero = 1
    return str(numero)


def _decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or "0"))


def _money(value) -> str:
    return f"{_decimal(value).quantize(Decimal('0.01')):.2f}"


def _quantity(value) -> str:
    return f"{_decimal(value):.4f}"


def _rate(value) -> str:
    return f"{_decimal(value):.6f}"


def _xml_attr(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def generar_cfdi(db: Session, data: CFDIGenerarRequest) -> CFDIComprobante:
    """
    Genera un CFDI 4.0 a partir de una venta.
    Construye el XML con todos los nodos requeridos por el SAT.
    """
    venta = db.query(Venta).filter(Venta.id == data.venta_id).first()
    if not venta:
        raise ValueError("Venta no encontrada")
    if venta.facturada:
        raise ValueError("Esta venta ya fue facturada")
    if venta.estado == EstadoVenta.CANCELADA:
        raise ValueError("No se puede facturar una venta cancelada")

    cliente = db.query(Cliente).filter(Cliente.id == data.cliente_id).first()
    if not cliente:
        raise ValueError("Cliente no encontrado")
    if not cliente.rfc:
        raise ValueError("El cliente no tiene RFC registrado")
    if not cliente.regimen_fiscal:
        raise ValueError("El cliente no tiene régimen fiscal registrado")
    if not cliente.domicilio_fiscal_cp:
        raise ValueError("El cliente no tiene código postal fiscal registrado")

    ahora = datetime.now(timezone.utc)

    cfdi_subtotal = sum(
        (detalle.precio_unitario * detalle.cantidad).quantize(Decimal("0.01"))
        for detalle in venta.detalles
    )
    cfdi_descuento = sum((detalle.descuento for detalle in venta.detalles), Decimal("0"))

    # Retry folio generation to handle race conditions
    for _attempt in range(3):
        folio = _generar_folio_cfdi(db, settings.CFDI_SERIE_FACTURAS)
        comprobante = CFDIComprobante(
            version=settings.CFDI_VERSION,
            serie=settings.CFDI_SERIE_FACTURAS,
            folio=folio,
            fecha=ahora,
            tipo_comprobante=TipoComprobante.INGRESO,
            forma_pago=data.forma_pago,
            metodo_pago=data.metodo_pago,
            lugar_expedicion=settings.LUGAR_EXPEDICION,
            # Emisor
            emisor_rfc=settings.RFC,
            emisor_nombre=settings.RAZON_SOCIAL,
            emisor_regimen_fiscal=settings.REGIMEN_FISCAL,
            # Receptor
            receptor_rfc=cliente.rfc,
            receptor_nombre=cliente.razon_social or cliente.nombre,
            receptor_regimen_fiscal=cliente.regimen_fiscal,
            receptor_domicilio_fiscal=cliente.domicilio_fiscal_cp,
            receptor_uso_cfdi=data.uso_cfdi,
            # Totales
            subtotal=cfdi_subtotal,
            descuento=cfdi_descuento,
            total_impuestos_trasladados=venta.total_impuestos,
            total=venta.total,
            # Relación con venta
            venta_id=venta.id,
            cliente_id=cliente.id,
        )
        db.add(comprobante)
        try:
            db.flush()
            break
        except IntegrityError:
            db.rollback()
    else:
        raise ValueError("No se pudo generar un folio único para el CFDI")

    # Crear conceptos desde detalles de venta
    for detalle in venta.detalles:
        producto = detalle.producto
        importe_bruto = (detalle.precio_unitario * detalle.cantidad).quantize(
            Decimal("0.01")
        )
        concepto = CFDIConcepto(
            comprobante_id=comprobante.id,
            clave_prod_serv=detalle.clave_prod_serv_sat,
            no_identificacion=producto.codigo if producto else None,
            cantidad=detalle.cantidad,
            clave_unidad=detalle.clave_unidad_sat,
            unidad=producto.unidad_medida.value if producto else "pz",
            descripcion=producto.nombre if producto else "Producto",
            valor_unitario=detalle.precio_unitario,
            importe=importe_bruto,
            descuento=detalle.descuento,
            objeto_imp=detalle.objeto_impuesto,
            impuesto_traslado_base=detalle.subtotal,
            impuesto_traslado_tipo="002",  # IVA
            impuesto_traslado_tasa=detalle.tasa_iva,
            impuesto_traslado_importe=detalle.monto_iva,
        )
        db.add(concepto)

    db.flush()

    # Generar XML
    xml = _construir_xml_cfdi(comprobante, db)
    comprobante.xml_generado = xml

    # Marcar venta como facturada
    venta.facturada = True

    db.commit()
    db.refresh(comprobante)
    return comprobante


def _construir_xml_cfdi(comprobante: CFDIComprobante, db: Session) -> str:
    """
    Construye el XML del CFDI 4.0.
    En producción se usaría lxml para generar XML validado contra XSD del SAT.
    """
    conceptos = db.query(CFDIConcepto).filter(
        CFDIConcepto.comprobante_id == comprobante.id
    ).all()

    conceptos_xml = ""
    for c in conceptos:
        impuestos_concepto = ""
        if c.impuesto_traslado_tipo:
            impuestos_concepto = f"""
        <cfdi:Impuestos>
          <cfdi:Traslados>
            <cfdi:Traslado Base="{_money(c.impuesto_traslado_base)}" Impuesto="002"
              TipoFactor="Tasa" TasaOCuota="{_rate(c.impuesto_traslado_tasa)}"
              Importe="{_money(c.impuesto_traslado_importe)}" />
          </cfdi:Traslados>
        </cfdi:Impuestos>"""

        conceptos_xml += f"""
      <cfdi:Concepto ClaveProdServ="{_xml_attr(c.clave_prod_serv)}"
        NoIdentificacion="{_xml_attr(c.no_identificacion)}"
        Cantidad="{_quantity(c.cantidad)}" ClaveUnidad="{_xml_attr(c.clave_unidad)}"
        Unidad="{_xml_attr(c.unidad)}" Descripcion="{_xml_attr(c.descripcion)}"
        ValorUnitario="{_money(c.valor_unitario)}" Importe="{_money(c.importe)}"
        Descuento="{_money(c.descuento)}" ObjetoImp="{_xml_attr(c.objeto_imp)}">{impuestos_concepto}
      </cfdi:Concepto>"""

    traslados_por_tasa: dict[str, dict[str, Decimal]] = {}
    for c in conceptos:
        if not c.impuesto_traslado_tipo:
            continue
        tasa = _rate(c.impuesto_traslado_tasa)
        acumulado = traslados_por_tasa.setdefault(
            tasa, {"base": Decimal("0"), "importe": Decimal("0")}
        )
        acumulado["base"] += _decimal(c.impuesto_traslado_base)
        acumulado["importe"] += _decimal(c.impuesto_traslado_importe)

    impuestos_xml = ""
    if traslados_por_tasa:
        traslados_xml = ""
        for tasa, valores in sorted(traslados_por_tasa.items()):
            traslados_xml += f"""
      <cfdi:Traslado Base="{_money(valores['base'])}" Impuesto="002"
        TipoFactor="Tasa" TasaOCuota="{tasa}"
        Importe="{_money(valores['importe'])}" />"""
        impuestos_xml = f"""
  <cfdi:Impuestos TotalImpuestosTrasladados="{_money(comprobante.total_impuestos_trasladados)}">
    <cfdi:Traslados>{traslados_xml}
    </cfdi:Traslados>
  </cfdi:Impuestos>
"""

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.sat.gob.mx/cfd/4
    http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
  Version="{_xml_attr(comprobante.version)}"
  Serie="{_xml_attr(comprobante.serie)}" Folio="{_xml_attr(comprobante.folio)}"
  Fecha="{comprobante.fecha.strftime('%Y-%m-%dT%H:%M:%S')}"
  FormaPago="{_xml_attr(comprobante.forma_pago)}"
  MetodoPago="{_xml_attr(comprobante.metodo_pago)}"
  TipoDeComprobante="{_xml_attr(comprobante.tipo_comprobante.value)}"
  Moneda="{_xml_attr(comprobante.moneda)}"
  LugarExpedicion="{_xml_attr(comprobante.lugar_expedicion)}"
  SubTotal="{_money(comprobante.subtotal)}"
  Descuento="{_money(comprobante.descuento)}"
  Total="{_money(comprobante.total)}"
  Exportacion="{_xml_attr(comprobante.exportacion)}">

  <cfdi:Emisor Rfc="{_xml_attr(comprobante.emisor_rfc)}"
    Nombre="{_xml_attr(comprobante.emisor_nombre)}"
    RegimenFiscal="{_xml_attr(comprobante.emisor_regimen_fiscal)}" />

  <cfdi:Receptor Rfc="{_xml_attr(comprobante.receptor_rfc)}"
    Nombre="{_xml_attr(comprobante.receptor_nombre)}"
    RegimenFiscalReceptor="{_xml_attr(comprobante.receptor_regimen_fiscal)}"
    DomicilioFiscalReceptor="{_xml_attr(comprobante.receptor_domicilio_fiscal)}"
    UsoCFDI="{_xml_attr(comprobante.receptor_uso_cfdi)}" />

  <cfdi:Conceptos>{conceptos_xml}
  </cfdi:Conceptos>

{impuestos_xml}

  <!-- Complemento TimbreFiscalDigital se agrega después del timbrado por el PAC -->

</cfdi:Comprobante>"""

    return xml


def cancelar_cfdi(db: Session, cfdi_id: int, data: CFDICancelRequest) -> CFDIComprobante:
    """
    Cancela un CFDI.
    Motivos SAT:
    01 - Con relación (requiere UUID de sustitución)
    02 - Sin relación
    03 - No se llevó a cabo la operación
    04 - Operación nominativa en factura global
    """
    comprobante = db.query(CFDIComprobante).filter(CFDIComprobante.id == cfdi_id).first()
    if not comprobante:
        raise ValueError("CFDI no encontrado")
    if comprobante.estado == EstadoCFDI.CANCELADO:
        raise ValueError("El CFDI ya está cancelado")

    if data.motivo == "01" and not data.uuid_sustitucion:
        raise ValueError("Motivo '01' requiere UUID de CFDI de sustitución")

    comprobante.estado = EstadoCFDI.CANCELADO
    comprobante.motivo_cancelacion = data.motivo
    comprobante.fecha_cancelacion = datetime.now(timezone.utc)
    if data.uuid_sustitucion:
        comprobante.cfdi_relacionado_uuid = data.uuid_sustitucion

    db.commit()
    db.refresh(comprobante)
    return comprobante


def obtener_cfdi(db: Session, cfdi_id: int) -> CFDIComprobante:
    comprobante = db.query(CFDIComprobante).filter(CFDIComprobante.id == cfdi_id).first()
    if not comprobante:
        raise ValueError("CFDI no encontrado")
    return comprobante


def listar_cfdis(db: Session, cliente_id: int | None = None, limit: int = 100):
    query = db.query(CFDIComprobante)
    if cliente_id:
        query = query.filter(CFDIComprobante.cliente_id == cliente_id)
    return query.order_by(CFDIComprobante.fecha.desc()).limit(limit).all()
