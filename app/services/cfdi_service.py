"""
Servicio de facturación electrónica CFDI 4.0.
Genera XML conforme a especificaciones del SAT.
Nota: El timbrado requiere integración con un PAC (Proveedor Autorizado de Certificación).
"""

from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.facturacion import (
    CFDIComprobante, CFDIConcepto, EstadoCFDI, TipoComprobante,
)
from app.models.venta import Venta, DetalleVenta
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

    cliente = db.query(Cliente).filter(Cliente.id == data.cliente_id).first()
    if not cliente:
        raise ValueError("Cliente no encontrado")
    if not cliente.rfc:
        raise ValueError("El cliente no tiene RFC registrado")
    if not cliente.regimen_fiscal:
        raise ValueError("El cliente no tiene régimen fiscal registrado")
    if not cliente.domicilio_fiscal_cp:
        raise ValueError("El cliente no tiene código postal fiscal registrado")

    folio = _generar_folio_cfdi(db, settings.CFDI_SERIE_FACTURAS)
    ahora = datetime.now(timezone.utc)

    # Crear comprobante
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
        subtotal=venta.subtotal,
        descuento=venta.descuento,
        total_impuestos_trasladados=venta.total_impuestos,
        total=venta.total,
        # Relación con venta
        venta_id=venta.id,
        cliente_id=cliente.id,
    )
    db.add(comprobante)
    db.flush()

    # Crear conceptos desde detalles de venta
    for detalle in venta.detalles:
        producto = detalle.producto
        concepto = CFDIConcepto(
            comprobante_id=comprobante.id,
            clave_prod_serv=detalle.clave_prod_serv_sat,
            no_identificacion=producto.codigo if producto else None,
            cantidad=detalle.cantidad,
            clave_unidad=detalle.clave_unidad_sat,
            unidad=producto.unidad_medida.value if producto else "pz",
            descripcion=producto.nombre if producto else "Producto",
            valor_unitario=detalle.precio_unitario,
            importe=detalle.subtotal + detalle.monto_iva,
            descuento=detalle.descuento,
            objeto_imp=detalle.objeto_impuesto,
            impuesto_traslado_base=detalle.subtotal,
            impuesto_traslado_tipo="002",  # IVA
            impuesto_traslado_tasa=detalle.tasa_iva,
            impuesto_traslado_importe=detalle.monto_iva,
        )
        db.add(concepto)

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
        if c.impuesto_traslado_importe > 0 or c.impuesto_traslado_tasa == Decimal("0"):
            impuestos_concepto = f"""
        <cfdi:Impuestos>
          <cfdi:Traslados>
            <cfdi:Traslado Base="{c.impuesto_traslado_base}" Impuesto="002"
              TipoFactor="Tasa" TasaOCuota="{c.impuesto_traslado_tasa:.6f}"
              Importe="{c.impuesto_traslado_importe}" />
          </cfdi:Traslados>
        </cfdi:Impuestos>"""

        conceptos_xml += f"""
      <cfdi:Concepto ClaveProdServ="{c.clave_prod_serv}"
        NoIdentificacion="{c.no_identificacion or ''}"
        Cantidad="{c.cantidad}" ClaveUnidad="{c.clave_unidad}"
        Unidad="{c.unidad or ''}" Descripcion="{c.descripcion}"
        ValorUnitario="{c.valor_unitario}" Importe="{c.importe}"
        Descuento="{c.descuento}" ObjetoImp="{c.objeto_imp}">{impuestos_concepto}
      </cfdi:Concepto>"""

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.sat.gob.mx/cfd/4
    http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd"
  Version="{comprobante.version}"
  Serie="{comprobante.serie}" Folio="{comprobante.folio}"
  Fecha="{comprobante.fecha.strftime('%Y-%m-%dT%H:%M:%S')}"
  FormaPago="{comprobante.forma_pago}"
  MetodoPago="{comprobante.metodo_pago}"
  TipoDeComprobante="{comprobante.tipo_comprobante.value}"
  Moneda="{comprobante.moneda}"
  LugarExpedicion="{comprobante.lugar_expedicion}"
  SubTotal="{comprobante.subtotal}"
  Descuento="{comprobante.descuento}"
  Total="{comprobante.total}"
  Exportacion="{comprobante.exportacion}">

  <cfdi:Emisor Rfc="{comprobante.emisor_rfc}"
    Nombre="{comprobante.emisor_nombre}"
    RegimenFiscal="{comprobante.emisor_regimen_fiscal}" />

  <cfdi:Receptor Rfc="{comprobante.receptor_rfc}"
    Nombre="{comprobante.receptor_nombre}"
    RegimenFiscalReceptor="{comprobante.receptor_regimen_fiscal}"
    DomicilioFiscalReceptor="{comprobante.receptor_domicilio_fiscal}"
    UsoCFDI="{comprobante.receptor_uso_cfdi}" />

  <cfdi:Conceptos>{conceptos_xml}
  </cfdi:Conceptos>

  <cfdi:Impuestos TotalImpuestosTrasladados="{comprobante.total_impuestos_trasladados}">
    <cfdi:Traslados>
      <cfdi:Traslado Base="{comprobante.subtotal}" Impuesto="002"
        TipoFactor="Tasa" TasaOCuota="0.160000"
        Importe="{comprobante.total_impuestos_trasladados}" />
    </cfdi:Traslados>
  </cfdi:Impuestos>

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
