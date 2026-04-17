"""Tests para el servicio de timbrado PAC (sandbox)."""

import pytest
from decimal import Decimal
from datetime import datetime, timezone

from app.models.facturacion import CFDIComprobante, EstadoCFDI, TipoComprobante


def _crear_cfdi(db, **kwargs):
    """Helper: crea un CFDI de prueba."""
    defaults = dict(
        version="4.0",
        serie="A",
        folio="1",
        fecha=datetime.now(timezone.utc),
        tipo_comprobante=TipoComprobante.INGRESO,
        forma_pago="01",
        metodo_pago="PUE",
        lugar_expedicion="76146",
        emisor_rfc="JRM250227BZ2",
        emisor_nombre="JACARANDA TEST",
        emisor_regimen_fiscal="601",
        receptor_rfc="XAXX010101000",
        receptor_nombre="PUBLICO GENERAL",
        receptor_regimen_fiscal="616",
        receptor_domicilio_fiscal="76146",
        receptor_uso_cfdi="S01",
        subtotal=Decimal("100.00"),
        total=Decimal("116.00"),
        total_impuestos_trasladados=Decimal("16.00"),
        xml_generado='<?xml version="1.0"?><cfdi:Comprobante></cfdi:Comprobante>',
        estado=EstadoCFDI.GENERADO,
    )
    defaults.update(kwargs)
    cfdi = CFDIComprobante(**defaults)
    db.add(cfdi)
    db.commit()
    db.refresh(cfdi)
    return cfdi


class TestTimbradoPAC:
    def test_timbrar_cfdi_sandbox(self, db):
        """Timbrado en sandbox genera UUID y actualiza estado."""
        from app.services.pac_service import timbrar_cfdi

        cfdi = _crear_cfdi(db)
        resultado = timbrar_cfdi(db, cfdi.id)

        assert resultado["uuid"]
        assert resultado["estado"] == "timbrado"
        assert resultado["cfdi_id"] == cfdi.id

        # Verificar BD
        db.refresh(cfdi)
        assert cfdi.uuid is not None
        assert cfdi.estado == EstadoCFDI.TIMBRADO
        assert cfdi.sello_sat is not None
        assert "TimbreFiscalDigital" in cfdi.xml_generado

    def test_timbrar_cfdi_ya_timbrado(self, db):
        """No se puede timbrar un CFDI que ya fue timbrado."""
        from app.services.pac_service import timbrar_cfdi

        cfdi = _crear_cfdi(db, uuid="EXISTING-UUID")
        with pytest.raises(ValueError, match="ya fue timbrado"):
            timbrar_cfdi(db, cfdi.id)

    def test_timbrar_cfdi_cancelado(self, db):
        """No se puede timbrar un CFDI cancelado."""
        from app.services.pac_service import timbrar_cfdi

        cfdi = _crear_cfdi(db, estado=EstadoCFDI.CANCELADO)
        with pytest.raises(ValueError, match="cancelado"):
            timbrar_cfdi(db, cfdi.id)

    def test_timbrar_cfdi_sin_xml(self, db):
        """No se puede timbrar sin XML generado."""
        from app.services.pac_service import timbrar_cfdi

        cfdi = _crear_cfdi(db, xml_generado=None)
        with pytest.raises(ValueError, match="no tiene XML"):
            timbrar_cfdi(db, cfdi.id)

    def test_timbrar_cfdi_no_existe(self, db):
        """Error cuando el CFDI no existe."""
        from app.services.pac_service import timbrar_cfdi

        with pytest.raises(ValueError, match="no encontrado"):
            timbrar_cfdi(db, 99999)


class TestCancelacionSAT:
    def test_cancelar_cfdi_sat(self, db):
        """Cancelación ante SAT en sandbox."""
        from app.services.pac_service import timbrar_cfdi, cancelar_cfdi_sat

        cfdi = _crear_cfdi(db)
        timbrar_cfdi(db, cfdi.id)

        resultado = cancelar_cfdi_sat(db, cfdi.id, motivo="02")
        assert resultado["estado"] == "cancelado"
        assert resultado["acuse"]

        db.refresh(cfdi)
        assert cfdi.estado == EstadoCFDI.CANCELADO
        assert cfdi.motivo_cancelacion == "02"

    def test_cancelar_cfdi_motivo_01_sin_uuid(self, db):
        """Motivo 01 requiere UUID de sustitución."""
        from app.services.pac_service import timbrar_cfdi, cancelar_cfdi_sat

        cfdi = _crear_cfdi(db)
        timbrar_cfdi(db, cfdi.id)

        with pytest.raises(ValueError, match="UUID"):
            cancelar_cfdi_sat(db, cfdi.id, motivo="01")

    def test_cancelar_cfdi_no_timbrado(self, db):
        """No se puede cancelar ante SAT sin timbrado."""
        from app.services.pac_service import cancelar_cfdi_sat

        cfdi = _crear_cfdi(db)
        with pytest.raises(ValueError, match="no ha sido timbrado"):
            cancelar_cfdi_sat(db, cfdi.id, motivo="02")


class TestDescargaXML:
    def test_descargar_xml(self, db):
        """Descarga XML de un CFDI."""
        from app.services.pac_service import descargar_xml

        cfdi = _crear_cfdi(db)
        xml = descargar_xml(db, cfdi.id)
        assert "cfdi:Comprobante" in xml

    def test_descargar_xml_masivo(self, db):
        """Descarga múltiples XMLs."""
        from app.services.pac_service import descargar_xml_masivo

        cfdi1 = _crear_cfdi(db, serie="B", folio="1")
        cfdi2 = _crear_cfdi(db, serie="B", folio="2")

        resultado = descargar_xml_masivo(db, [cfdi1.id, cfdi2.id, 99999])
        assert len(resultado) == 3
        assert resultado[0]["xml"] is not None
        assert resultado[1]["xml"] is not None
        assert resultado[2]["error"] is not None


class TestConsultaEstatus:
    def test_consultar_estatus_no_timbrado(self, db):
        """Consulta de CFDI no timbrado."""
        from app.services.pac_service import consultar_estatus_sat

        cfdi = _crear_cfdi(db)
        result = consultar_estatus_sat(db, cfdi.id)
        assert result["estatus"] == "no_timbrado"
        assert result["es_cancelable"] is False

    def test_consultar_estatus_timbrado(self, db):
        """Consulta de CFDI timbrado."""
        from app.services.pac_service import timbrar_cfdi, consultar_estatus_sat

        cfdi = _crear_cfdi(db)
        timbrar_cfdi(db, cfdi.id)

        result = consultar_estatus_sat(db, cfdi.id)
        assert result["estatus"] == "timbrado"
        assert result["es_cancelable"] is True
        assert result["uuid"]
