"""
Jacaranda - Sistema de Gestión de Panadería
Cumple con normativa mexicana: SAT/CFDI 4.0, LFT, IMSS, COFEPRIS, NOM-051.
"""

import json
import logging
import os
import secrets
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base, SessionLocal
from app.core.security import get_password_hash
from app.api.routes import router as api_router

# Importar todos los modelos para que se registren en Base.metadata
import app.models  # noqa: F401
from app.models.usuario import Usuario, RolUsuario


# ─── Logging estructurado ──────────────────────────────────────────
class JSONFormatter(logging.Formatter):
    """Formato JSON para logs en Railway/producción."""
    def format(self, record):
        log = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log["exception"] = self.formatException(record.exc_info)
        return json.dumps(log, ensure_ascii=False)


def _setup_logging():
    level = logging.DEBUG if settings.DEBUG else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    # Clear existing handlers
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    if settings.DEBUG:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
        ))
    else:
        handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


_setup_logging()
logger = logging.getLogger("jacaranda")


def _seed_admin():
    """Crea usuario administrador inicial sin usar credenciales predecibles."""
    db = SessionLocal()
    try:
        admin = db.query(Usuario).filter(Usuario.rol == RolUsuario.ADMINISTRADOR).first()
        if not admin:
            # Usar contraseña de variable de entorno o generar una aleatoria
            password = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
            if os.environ.get("ADMIN_PASSWORD") and len(password) < 12:
                raise RuntimeError("ADMIN_PASSWORD debe tener al menos 12 caracteres")
            admin = Usuario(
                nombre="Administrador",
                email="admin@jacaranda.mx",
                hashed_password=get_password_hash(password),
                rol=RolUsuario.ADMINISTRADOR,
            )
            db.add(admin)
            db.commit()
            if not os.environ.get("ADMIN_PASSWORD"):
                logger.warning(
                    "========================================\n"
                    "  ADMIN CREADO - Cambie la contraseña!\n"
                    "  Email: admin@jacaranda.mx\n"
                    "  Password: (ver variable ADMIN_PASSWORD)\n"
                    "  Establezca ADMIN_PASSWORD en .env\n"
                    "========================================"
                )
                # Escribir password temporal a archivo seguro, no a logs
                try:
                    with open(".admin_password", "w") as f:
                        f.write(password)
                    os.chmod(".admin_password", 0o600)
                    logger.info("Password temporal guardado en .admin_password")
                except OSError:
                    pass  # En entornos read-only simplemente skip
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.security_validation import validate_secret_key
    validate_secret_key()

    # Run Alembic migrations, fallback to create_all
    try:
        from alembic.config import Config
        from alembic import command
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations applied")
    except Exception as e:
        logger.warning("Alembic migration failed (%s), using create_all fallback", e)
        Base.metadata.create_all(bind=engine)
    _seed_admin()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
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

# Rate limiting global
from app.core.rate_limit import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

# Auditoría automática de operaciones de escritura
from app.core.audit_middleware import AuditMiddleware
app.add_middleware(AuditMiddleware)

# CORS — restringido a dominios configurados
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
)

# Rutas API
app.include_router(api_router, prefix="/api/v1")


# ─── Request logging middleware ─────────────────────────────────────
import time as _time

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = _time.time()
    response = await call_next(request)
    ms = round((_time.time() - start) * 1000)
    if not request.url.path.startswith("/health"):
        logger.info(
            "%s %s %s %dms",
            request.method, request.url.path, response.status_code, ms,
        )
    return response


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
