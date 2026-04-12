"""
Jacaranda - Sistema de Gestión de Panadería
Cumple con normativa mexicana: SAT/CFDI 4.0, LFT, IMSS, COFEPRIS, NOM-051.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base
from app.api.routes import router as api_router

# Importar todos los modelos para que se registren en Base.metadata
import app.models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Crear tablas al inicio
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Sistema integral de gestión para panadería y pastelería.\n\n"
        "## Módulos\n"
        "- **Inventario**: Control de ingredientes, productos, lotes y proveedores\n"
        "- **Recetas y Producción**: Costeo, planificación y trazabilidad\n"
        "- **Punto de Venta**: Ventas con desglose fiscal IVA 0%/16%, tickets, corte de caja\n"
        "- **Facturación CFDI 4.0**: Emisión de comprobantes fiscales conforme al SAT\n"
        "- **Clientes**: Gestión con datos fiscales para facturación\n"
        "- **Empleados y Nómina**: LFT, IMSS, ISR, aguinaldo, vacaciones, PTU\n"
        "- **COFEPRIS**: Temperaturas, limpieza, inspecciones, control de plagas\n"
        "- **NOM-051**: Etiquetado con sellos de advertencia para productos empacados\n"
        "- **Reportes**: Ventas, IVA mensual, ISR provisional, dashboard\n\n"
        "## Cumplimiento Legal\n"
        "- SAT: CFDI 4.0, IVA (0% alimentos básicos / 16% preparados)\n"
        "- LFT: Jornadas, horas extra, aguinaldo, vacaciones (reforma 2023), PTU\n"
        "- IMSS: Cuotas obrero-patronales, SDI\n"
        "- COFEPRIS: NOM-251-SSA1-2009 (higiene alimentos)\n"
        "- NOM-051: Etiquetado frontal con sellos de advertencia"
    ),
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rutas API
app.include_router(api_router, prefix="/api/v1")


@app.get("/", tags=["Root"])
def root():
    return {
        "sistema": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "documentacion": "/docs",
        "modulos": [
            "inventario", "recetas", "produccion", "punto-de-venta",
            "facturacion-cfdi", "clientes", "empleados", "nomina",
            "cofepris", "nom-051", "reportes",
        ],
    }


@app.get("/health", tags=["Root"])
def health():
    return {"status": "ok"}
