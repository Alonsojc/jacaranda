"""
Modelos de facturación electrónica CFDI 4.0.
Cumple con las especificaciones del SAT para emisión de comprobantes fiscales.
"""

from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    String, DateTime, ForeignKey, Text, Numeric, Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base


class EstadoCFDI(str, enum.Enum):
    GENERADO = "generado"         # XML generado, pendiente de timbrado
    TIMBRADO = "timbrado"         # Timbrado exitoso por PAC
    CANCELADO = "cancelado"       # Cancelado ante SAT
    ERROR = "error"


class TipoComprobante(str, enum.Enum):
    INGRESO = "I"       # Facturas de venta
    EGRESO = "E"        # Notas de crédito
    TRASLADO = "T"      # Carta porte
    NOMINA = "N"        # Recibos de nómina
    PAGO = "P"          # Complemento de pago


class TipoRelacion(str, enum.Enum):
    """Tipos de relación entre CFDI (catálogo SAT c_TipoRelacion)."""
    NOTA_CREDITO = "01"
    NOTA_DEBITO = "02"
    DEVOLUCION = "03"
    SUSTITUCION = "04"


class CFDIComprobante(Base):
    """Comprobante Fiscal Digital por Internet versión 4.0."""
    __tablename__ = "cfdi_comprobantes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Datos del comprobante
    version: Mapped[str] = mapped_column(String(5), default="4.0")
    serie: Mapped[str] = mapped_column(String(25))
    folio: Mapped[str] = mapped_column(String(40))
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tipo_comprobante: Mapped[TipoComprobante] = mapped_column(SAEnum(TipoComprobante))
    forma_pago: Mapped[str] = mapped_column(String(2))  # Catálogo SAT c_FormaPago
    metodo_pago: Mapped[str] = mapped_column(String(3))  # PUE o PPD
    moneda: Mapped[str] = mapped_column(String(3), default="MXN")
    tipo_cambio: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal("1"))
    lugar_expedicion: Mapped[str] = mapped_column(String(5))  # CP
    exportacion: Mapped[str] = mapped_column(String(2), default="01")  # 01=No aplica

    # Emisor
    emisor_rfc: Mapped[str] = mapped_column(String(13))
    emisor_nombre: Mapped[str] = mapped_column(String(300))
    emisor_regimen_fiscal: Mapped[str] = mapped_column(String(3))

    # Receptor (Cliente)
    receptor_rfc: Mapped[str] = mapped_column(String(13))
    receptor_nombre: Mapped[str] = mapped_column(String(300))
    receptor_regimen_fiscal: Mapped[str] = mapped_column(String(3))
    receptor_domicilio_fiscal: Mapped[str] = mapped_column(String(5))
    receptor_uso_cfdi: Mapped[str] = mapped_column(String(4))

    # Totales
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    descuento: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    total_impuestos_trasladados: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0")
    )
    total_impuestos_retenidos: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0")
    )
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    # Timbrado (datos del PAC)
    uuid: Mapped[str | None] = mapped_column(String(36), unique=True, index=True)
    fecha_timbrado: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sello_cfdi: Mapped[str | None] = mapped_column(Text)
    sello_sat: Mapped[str | None] = mapped_column(Text)
    no_certificado_sat: Mapped[str | None] = mapped_column(String(20))
    no_certificado_emisor: Mapped[str | None] = mapped_column(String(20))
    cadena_original_timbrado: Mapped[str | None] = mapped_column(Text)

    # Relaciones con otros CFDI
    cfdi_relacionado_uuid: Mapped[str | None] = mapped_column(String(36))
    tipo_relacion: Mapped[str | None] = mapped_column(String(2))

    # XML
    xml_generado: Mapped[str | None] = mapped_column(Text)
    xml_timbrado: Mapped[str | None] = mapped_column(Text)

    # Estado
    estado: Mapped[EstadoCFDI] = mapped_column(
        SAEnum(EstadoCFDI), default=EstadoCFDI.GENERADO
    )
    motivo_cancelacion: Mapped[str | None] = mapped_column(String(2))
    fecha_cancelacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Venta asociada
    venta_id: Mapped[int | None] = mapped_column(ForeignKey("ventas.id"))
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"))

    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    venta: Mapped["Venta | None"] = relationship(back_populates="cfdi")  # noqa: F821
    conceptos: Mapped[list["CFDIConcepto"]] = relationship(
        back_populates="comprobante", cascade="all, delete-orphan"
    )


class CFDIConcepto(Base):
    """Conceptos (partidas) del CFDI."""
    __tablename__ = "cfdi_conceptos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    comprobante_id: Mapped[int] = mapped_column(ForeignKey("cfdi_comprobantes.id"))

    clave_prod_serv: Mapped[str] = mapped_column(String(8))
    no_identificacion: Mapped[str | None] = mapped_column(String(100))
    cantidad: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    clave_unidad: Mapped[str] = mapped_column(String(4))
    unidad: Mapped[str | None] = mapped_column(String(20))
    descripcion: Mapped[str] = mapped_column(String(1000))
    valor_unitario: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    importe: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    descuento: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    objeto_imp: Mapped[str] = mapped_column(String(2), default="02")

    # Impuestos trasladados
    impuesto_traslado_base: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0")
    )
    impuesto_traslado_tipo: Mapped[str | None] = mapped_column(String(3))  # 002=IVA
    impuesto_traslado_tasa: Mapped[Decimal] = mapped_column(
        Numeric(6, 6), default=Decimal("0")
    )
    impuesto_traslado_importe: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0")
    )

    comprobante: Mapped["CFDIComprobante"] = relationship(back_populates="conceptos")
