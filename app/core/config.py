"""
Configuración central del sistema de gestión de panadería.
Incluye configuración fiscal mexicana (SAT, IVA, ISR, IMSS).
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from decimal import Decimal


class Settings(BaseSettings):
    # --- Aplicación ---
    APP_NAME: str = "Jacaranda - Sistema de Gestión de Panadería"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = "cambiar-en-produccion-clave-secreta-segura"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 horas

    # --- Base de datos ---
    DATABASE_URL: str = "sqlite:///./jacaranda.db"

    # --- Datos del negocio ---
    RAZON_SOCIAL: str = "Panadería Jacaranda S.A. de C.V."
    RFC: str = "XAXX010101000"  # RFC del negocio
    REGIMEN_FISCAL: str = "612"  # Personas Físicas con Actividades Empresariales
    DOMICILIO_FISCAL_CP: str = "00000"
    LUGAR_EXPEDICION: str = "00000"

    # --- Configuración fiscal mexicana ---
    # IVA
    IVA_TASA_GENERAL: Decimal = Decimal("0.16")  # 16%
    IVA_TASA_ALIMENTOS_BASICOS: Decimal = Decimal("0.00")  # 0% pan básico
    IVA_TASA_FRONTERA: Decimal = Decimal("0.08")  # 8% zona fronteriza
    ZONA_FRONTERIZA: bool = False

    # IEPS (Impuesto Especial sobre Producción y Servicios)
    IEPS_BEBIDAS_AZUCARADAS: Decimal = Decimal("0.08")  # si aplica
    IEPS_ALIMENTOS_CALORICOS: Decimal = Decimal("0.08")  # >275 kcal/100g

    # ISR - Retenciones
    ISR_RETENCION_SERVICIOS: Decimal = Decimal("0.10")

    # --- IMSS / Nómina ---
    SALARIO_MINIMO_GENERAL: Decimal = Decimal("278.80")  # 2025 diario
    SALARIO_MINIMO_ZONA_FRONTERIZA: Decimal = Decimal("419.88")
    UMA_DIARIO: Decimal = Decimal("113.14")  # Unidad de Medida y Actualización
    UMA_MENSUAL: Decimal = Decimal("3439.46")

    # Cuotas patronales IMSS (porcentajes)
    IMSS_ENFERMEDADES_MATERNIDAD_PATRON: Decimal = Decimal("0.2040")
    IMSS_INVALIDEZ_VIDA_PATRON: Decimal = Decimal("0.0175")
    IMSS_RETIRO_PATRON: Decimal = Decimal("0.02")
    IMSS_CESANTIA_VEJEZ_PATRON: Decimal = Decimal("0.0315")
    IMSS_GUARDERIAS: Decimal = Decimal("0.01")
    INFONAVIT_PATRON: Decimal = Decimal("0.05")

    # Prestaciones LFT
    AGUINALDO_DIAS_MINIMO: int = 15
    PRIMA_VACACIONAL_PORCENTAJE: Decimal = Decimal("0.25")
    PTU_PORCENTAJE: Decimal = Decimal("0.10")  # 10% utilidades
    PTU_TOPE_MESES: int = 3  # Tope de 3 meses de salario

    # --- CFDI 4.0 ---
    CFDI_VERSION: str = "4.0"
    CFDI_SERIE_FACTURAS: str = "A"
    CFDI_SERIE_TICKETS: str = "T"
    CFDI_MONEDA: str = "MXN"
    CFDI_TIPO_COMPROBANTE_INGRESO: str = "I"
    CFDI_TIPO_COMPROBANTE_EGRESO: str = "E"
    CFDI_TIPO_COMPROBANTE_NOMINA: str = "N"
    CFDI_METODO_PAGO_PUE: str = "PUE"  # Pago en Una sola Exhibición
    CFDI_METODO_PAGO_PPD: str = "PPD"  # Pago en Parcialidades o Diferido

    # --- COFEPRIS ---
    TEMPERATURA_MAXIMA_REFRIGERACION: Decimal = Decimal("4.0")  # °C
    TEMPERATURA_MAXIMA_CONGELACION: Decimal = Decimal("-18.0")  # °C
    TEMPERATURA_MINIMA_COCCION: Decimal = Decimal("74.0")  # °C
    DIAS_REVISION_COFEPRIS: int = 30  # Frecuencia de revisión interna

    # --- NOM-051 Etiquetado ---
    CALORIAS_EXCESO_100ML: int = 10
    CALORIAS_EXCESO_100G: int = 275
    SODIO_EXCESO_MG: int = 350
    AZUCAR_EXCESO_G: Decimal = Decimal("10.0")
    GRASA_SATURADA_EXCESO_G: Decimal = Decimal("4.0")
    GRASA_TRANS_EXCESO_G: Decimal = Decimal("0.5")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
