"""
Configuración central del sistema de gestión de panadería.
Incluye configuración fiscal mexicana (SAT, IVA, ISR, IMSS).
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from decimal import Decimal
import secrets


def _default_secret():
    """Genera una clave secreta aleatoria si no se configura una."""
    return secrets.token_urlsafe(64)


class Settings(BaseSettings):
    # --- Aplicación ---
    APP_NAME: str = "Jacaranda - Sistema de Gestión de Panadería"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    RAILWAY_ENVIRONMENT: str = ""
    DEBUG: bool = False
    SECRET_KEY: str = Field(default_factory=_default_secret)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 horas

    # --- Base de datos ---
    DATABASE_URL: str = "sqlite:///./jacaranda.db"
    ALLOW_SQLITE_IN_PRODUCTION: bool = False
    ALLOW_CREATE_ALL_FALLBACK: bool = False

    # --- CORS (comma-separated origins) ---
    CORS_ORIGINS: str = "https://alonsojc.github.io"

    # --- Datos del negocio ---
    RAZON_SOCIAL: str = "JACARANDA REPOSTERIA MEXICANA"
    RFC: str = "JRM250227BZ2"  # Persona Moral - 12 caracteres
    REGIMEN_FISCAL: str = "601"  # General de Ley Personas Morales
    DOMICILIO_FISCAL_CP: str = "76146"  # Querétaro, QRO
    LUGAR_EXPEDICION: str = "76146"  # Querétaro, QRO

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

    # Anthropic API (OCR de tickets)
    ANTHROPIC_API_KEY: str = ""

    # Conekta (pagos online)
    CONEKTA_API_KEY: str = ""
    CONEKTA_API_VERSION: str = "2.1.0"
    CONEKTA_SANDBOX_MODE: bool = True
    CONEKTA_WEBHOOK_KEY: str = ""
    CONEKTA_WEBHOOK_PUBLIC_KEY: str = ""

    # CLIP API (terminal de pagos)
    CLIP_API_KEY: str = ""
    CLIP_API_SECRET: str = ""
    CLIP_API_URL: str = "https://api.clip.mx"

    # BBVA API Market (conciliación de pagos)
    BBVA_CLIENT_ID: str = ""
    BBVA_CLIENT_SECRET: str = ""
    BBVA_API_URL: str = "https://apis.bbva.com/mexico/v1"
    BBVA_TOKEN_URL: str = "https://connect.bbva.com/token"
    BBVA_ACCOUNT_ID: str = ""

    # PAXSTORE Cloud API (terminal PAX A910S)
    PAXSTORE_API_KEY: str = ""
    PAXSTORE_API_SECRET: str = ""
    PAXSTORE_API_URL: str = "https://api.whatspos.com/p-market-api"
    PAX_TERMINAL_SN: str = "2841093742"  # S/N de la terminal Jacaranda

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

    # --- WhatsApp Business API ---
    WA_API_TOKEN: str = ""
    WA_PHONE_NUMBER_ID: str = ""
    WA_VERIFY_TOKEN: str = "jacaranda_wa_verify"
    WA_APP_SECRET: str = ""
    WA_ALLOW_UNSIGNED_WEBHOOKS: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def is_production(self) -> bool:
        environment = (self.RAILWAY_ENVIRONMENT or self.ENVIRONMENT).lower()
        return environment in {"prod", "production"} and not self.DEBUG


settings = Settings()
