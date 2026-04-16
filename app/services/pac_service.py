"""
Servicio de integración con PAC (Proveedor Autorizado de Certificación).
Timbrado, cancelación y consulta de CFDIs ante el SAT.
En modo sandbox simula respuestas del PAC.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.facturacion import CFDIComprobante, EstadoCFDI

logger = logging.getLogger("jacaranda.pac")


# ─── Timbrado ─────────────────────────────────────────────────────

def timbrar_cfdi(db: Session, cfdi_id: int) -> dict:
    """
    Envía un CFDI al PAC para timbrado.
    En sandbox genera UUID y sellos simulados.
    """
    comprobante = db.query(CFDIComprobante).filter(CFDIComprobante.id == cfdi_id).first()
    if not comprobante:
        raise ValueError("CFDI no encontrado")
    if comprobante.estado == EstadoCFDI.CANCELADO:
        raise ValueError("No se puede timbrar un CFDI cancelado")
    if comprobante.uuid:
        raise ValueError("El CFDI ya fue timbrado")
    if not comprobante.xml_generado:
        raise ValueError("El CFDI no tiene XML generado")

    resultado = _timbrar_sandbox(comprobante)

    # Actualizar comprobante
    comprobante.uuid = resultado["uuid"]
    comprobante.sello_sat = resultado["sello_sat"]
    comprobante.no_certificado_sat = resultado["certificado_sat"]
    comprobante.cadena_original_timbrado = resultado["cadena_original"]
    comprobante.fecha_timbrado = resultado["fecha_timbrado"]
    comprobante.estado = EstadoCFDI.TIMBRADO

    # Insertar complemento TimbreFiscalDigital en el XML
    comprobante.xml_generado = _insertar_timbre_xml(
        comprobante.xml_generado, resultado
    )

    db.commit()
    db.refresh(comprobante)

    logger.info("CFDI timbrado: UUID=%s", resultado["uuid"])

    return {
        "cfdi_id": comprobante.id,
        "uuid": resultado["uuid"],
        "fecha_timbrado": resultado["fecha_timbrado"].isoformat(),
        "estado": comprobante.estado.value,
    }


def _timbrar_sandbox(comprobante: CFDIComprobante) -> dict:
    """Simula respuesta de timbrado del PAC."""
    ahora = datetime.now(timezone.utc)
    fake_uuid = str(uuid.uuid4()).upper()
    xml_hash = hashlib.sha256(
        (comprobante.xml_generado or "").encode()
    ).hexdigest()[:64]

    return {
        "uuid": fake_uuid,
        "sello_sat": f"SANDBOX_{xml_hash}",
        "certificado_sat": "00001000000504465028",
        "cadena_original": (
            f"||1.1|{fake_uuid}|{ahora.strftime('%Y-%m-%dT%H:%M:%S')}|"
            f"{comprobante.emisor_rfc}|{comprobante.receptor_rfc}|{comprobante.total}||"
        ),
        "fecha_timbrado": ahora,
    }


def _insertar_timbre_xml(xml: str, timbrado: dict) -> str:
    """Inserta el complemento TimbreFiscalDigital en el XML del CFDI."""
    complemento = (
        '\n  <cfdi:Complemento>'
        '\n    <tfd:TimbreFiscalDigital'
        '\n      xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"'
        '\n      Version="1.1"'
        f'\n      UUID="{timbrado["uuid"]}"'
        f'\n      FechaTimbrado="{timbrado["fecha_timbrado"].strftime("%Y-%m-%dT%H:%M:%S")}"'
        '\n      RfcProvCertif="SPR190613I52"'
        f'\n      NoCertificadoSAT="{timbrado["certificado_sat"]}"'
        f'\n      SelloSAT="{timbrado["sello_sat"]}" />'
        '\n  </cfdi:Complemento>'
    )
    return xml.replace("</cfdi:Comprobante>", f"{complemento}\n</cfdi:Comprobante>")


# ─── Cancelación ante SAT ─────────────────────────────────────────

def cancelar_cfdi_sat(
    db: Session,
    cfdi_id: int,
    motivo: str,
    uuid_sustitucion: str | None = None,
) -> dict:
    """
    Cancela un CFDI ante el SAT vía PAC.
    Motivos SAT: 01=Con relación, 02=Sin relación, 03=No se realizó, 04=Nominativa global.
    """
    comprobante = db.query(CFDIComprobante).filter(CFDIComprobante.id == cfdi_id).first()
    if not comprobante:
        raise ValueError("CFDI no encontrado")
    if comprobante.estado == EstadoCFDI.CANCELADO:
        raise ValueError("El CFDI ya está cancelado")
    if not comprobante.uuid:
        raise ValueError("El CFDI no ha sido timbrado")
    if motivo == "01" and not uuid_sustitucion:
        raise ValueError("Motivo '01' requiere UUID del CFDI de sustitución")

    comprobante.estado = EstadoCFDI.CANCELADO
    comprobante.motivo_cancelacion = motivo
    comprobante.fecha_cancelacion = datetime.now(timezone.utc)
    if uuid_sustitucion:
        comprobante.cfdi_relacionado_uuid = uuid_sustitucion

    db.commit()
    db.refresh(comprobante)

    logger.info("CFDI cancelado: UUID=%s motivo=%s", comprobante.uuid, motivo)

    return {
        "cfdi_id": comprobante.id,
        "uuid": comprobante.uuid,
        "estado": "cancelado",
        "acuse": f"SANDBOX_ACUSE_{comprobante.uuid}_{motivo}",
        "fecha_cancelacion": comprobante.fecha_cancelacion.isoformat(),
    }


# ─── Descarga XML ─────────────────────────────────────────────────

def descargar_xml(db: Session, cfdi_id: int) -> str:
    """Retorna el XML completo del CFDI."""
    comprobante = db.query(CFDIComprobante).filter(CFDIComprobante.id == cfdi_id).first()
    if not comprobante:
        raise ValueError("CFDI no encontrado")
    if not comprobante.xml_generado:
        raise ValueError("El CFDI no tiene XML generado")
    return comprobante.xml_generado


def descargar_xml_masivo(db: Session, cfdi_ids: list[int]) -> list[dict]:
    """Descarga múltiples XMLs."""
    resultado = []
    for cfdi_id in cfdi_ids:
        try:
            xml = descargar_xml(db, cfdi_id)
            comp = db.query(CFDIComprobante).filter(CFDIComprobante.id == cfdi_id).first()
            resultado.append({
                "cfdi_id": cfdi_id,
                "uuid": comp.uuid if comp else None,
                "xml": xml,
                "error": None,
            })
        except ValueError as e:
            resultado.append({
                "cfdi_id": cfdi_id,
                "uuid": None,
                "xml": None,
                "error": str(e),
            })
    return resultado


# ─── Consulta de estatus ──────────────────────────────────────────

def consultar_estatus_sat(db: Session, cfdi_id: int) -> dict:
    """Consulta estatus de un CFDI ante el SAT (sandbox)."""
    comprobante = db.query(CFDIComprobante).filter(CFDIComprobante.id == cfdi_id).first()
    if not comprobante:
        raise ValueError("CFDI no encontrado")
    if not comprobante.uuid:
        return {
            "cfdi_id": cfdi_id,
            "estatus": "no_timbrado",
            "es_cancelable": False,
        }

    return {
        "cfdi_id": cfdi_id,
        "uuid": comprobante.uuid,
        "estatus": comprobante.estado.value,
        "es_cancelable": comprobante.estado != EstadoCFDI.CANCELADO,
        "validacion_efos": "200",  # 200 = No listado en EFOS
        "sandbox": True,
    }
