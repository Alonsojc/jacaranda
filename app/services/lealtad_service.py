"""
Servicio del sistema de lealtad avanzado.
Niveles, cupones, tarjeta digital QR, promociones de cumpleanos.
"""

import base64
import hashlib
import io
import json
import re
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import quote

from sqlalchemy.orm import Session
from sqlalchemy import func, extract

from app.core.time_utils import operation_today
from app.models.cliente import Cliente
from app.models.lealtad import (
    Cupon, CuponCliente, HistorialPuntos,
    NivelLealtad, TipoCupon, EstadoCupon, LealtadConfiguracion,
)
from app.core.config import settings


MONTO_RECOMPENSA_PASTEL_CHICO = Decimal("10000")
RECOMPENSA_NOMBRE = "Pastel chico gratis"
PUNTOS_POR_PESO_DEFAULT = Decimal("0.1000")
VALOR_PUNTO_DEFAULT = Decimal("0.50")
CUMPLEANOS_DESCUENTO_DEFAULT = Decimal("10")


# ── Configuracion ────────────────────────────────────────────────────

def obtener_configuracion(db: Session) -> LealtadConfiguracion:
    """Obtiene o crea la configuracion editable del programa."""
    config = db.get(LealtadConfiguracion, 1)
    if config:
        return config
    config = LealtadConfiguracion(
        id=1,
        recompensa_monto_meta=MONTO_RECOMPENSA_PASTEL_CHICO,
        recompensa_nombre=RECOMPENSA_NOMBRE,
        puntos_por_peso=PUNTOS_POR_PESO_DEFAULT,
        valor_punto=VALOR_PUNTO_DEFAULT,
        cumpleanos_promo_activa=True,
        cumpleanos_descuento_porcentaje=CUMPLEANOS_DESCUENTO_DEFAULT,
        puntos_expiran_dias=None,
    )
    db.add(config)
    db.flush()
    return config


def _decimal_config(valor, default: Decimal) -> Decimal:
    if valor is None:
        return default
    return Decimal(str(valor))


def configuracion_dict(config: LealtadConfiguracion) -> dict:
    return {
        "id": config.id,
        "recompensa_monto_meta": float(_decimal_config(
            config.recompensa_monto_meta,
            MONTO_RECOMPENSA_PASTEL_CHICO,
        )),
        "recompensa_nombre": config.recompensa_nombre or RECOMPENSA_NOMBRE,
        "puntos_por_peso": float(_decimal_config(
            config.puntos_por_peso,
            PUNTOS_POR_PESO_DEFAULT,
        )),
        "valor_punto": float(_decimal_config(config.valor_punto, VALOR_PUNTO_DEFAULT)),
        "cumpleanos_promo_activa": bool(config.cumpleanos_promo_activa),
        "cumpleanos_descuento_porcentaje": float(_decimal_config(
            config.cumpleanos_descuento_porcentaje,
            CUMPLEANOS_DESCUENTO_DEFAULT,
        )),
        "puntos_expiran_dias": config.puntos_expiran_dias,
        "actualizado_en": (
            config.actualizado_en.isoformat() if config.actualizado_en else None
        ),
    }


def actualizar_configuracion(db: Session, data: dict) -> LealtadConfiguracion:
    config = obtener_configuracion(db)
    campos_decimal = {
        "recompensa_monto_meta",
        "puntos_por_peso",
        "valor_punto",
        "cumpleanos_descuento_porcentaje",
    }
    campos_permitidos = campos_decimal | {
        "recompensa_nombre",
        "cumpleanos_promo_activa",
        "puntos_expiran_dias",
    }
    for key, value in data.items():
        if key not in campos_permitidos:
            continue
        if key in campos_decimal and value is not None:
            value = Decimal(str(value))
        if key == "recompensa_nombre" and value is not None:
            value = value.strip()
        setattr(config, key, value)
    config.actualizado_en = datetime.now(timezone.utc)
    db.flush()
    return config


def _monto_meta(config: LealtadConfiguracion | None = None) -> Decimal:
    return max(
        Decimal("0.01"),
        _decimal_config(
            getattr(config, "recompensa_monto_meta", None),
            MONTO_RECOMPENSA_PASTEL_CHICO,
        ),
    )


def _nombre_recompensa(config: LealtadConfiguracion | None = None) -> str:
    return (getattr(config, "recompensa_nombre", None) or RECOMPENSA_NOMBRE).strip()


def puntos_por_peso(config: LealtadConfiguracion | None = None) -> Decimal:
    return _decimal_config(getattr(config, "puntos_por_peso", None), PUNTOS_POR_PESO_DEFAULT)


def valor_punto(config: LealtadConfiguracion | None = None) -> Decimal:
    return _decimal_config(getattr(config, "valor_punto", None), VALOR_PUNTO_DEFAULT)


def aplicar_expiracion_puntos(
    db: Session,
    cliente: Cliente,
    config: LealtadConfiguracion | None = None,
    ahora: datetime | None = None,
) -> dict:
    """Expira puntos vencidos usando FIFO conservador sin cambiar el esquema."""
    config = config or obtener_configuracion(db)
    dias = int(getattr(config, "puntos_expiran_dias", None) or 0)
    if dias <= 0:
        return {"puntos_expirados": 0, "saldo": int(cliente.puntos_acumulados or 0)}

    ahora = ahora or datetime.now(timezone.utc)
    corte = ahora - timedelta(days=dias)
    puntos_vencidos = db.query(func.coalesce(func.sum(HistorialPuntos.puntos), 0)).filter(
        HistorialPuntos.cliente_id == cliente.id,
        HistorialPuntos.puntos > 0,
        HistorialPuntos.creado_en < corte,
    ).scalar() or 0
    puntos_ya_expirados = db.query(func.coalesce(func.sum(HistorialPuntos.puntos), 0)).filter(
        HistorialPuntos.cliente_id == cliente.id,
        HistorialPuntos.puntos < 0,
        HistorialPuntos.concepto.like("Expiracion de puntos%"),
    ).scalar() or 0
    puntos_consumidos = db.query(func.coalesce(func.sum(HistorialPuntos.puntos), 0)).filter(
        HistorialPuntos.cliente_id == cliente.id,
        HistorialPuntos.puntos < 0,
        HistorialPuntos.concepto.notlike("Expiracion de puntos%"),
    ).scalar() or 0
    por_expirar = int(puntos_vencidos or 0) - abs(int(puntos_ya_expirados or 0))
    por_expirar -= abs(int(puntos_consumidos or 0))
    por_expirar = min(max(0, por_expirar), int(cliente.puntos_acumulados or 0))
    if por_expirar <= 0:
        return {"puntos_expirados": 0, "saldo": int(cliente.puntos_acumulados or 0)}

    saldo_anterior = int(cliente.puntos_acumulados or 0)
    cliente.puntos_acumulados = max(0, saldo_anterior - por_expirar)
    db.add(HistorialPuntos(
        cliente_id=cliente.id,
        puntos=-por_expirar,
        concepto=f"Expiracion de puntos ({dias} dias)",
        venta_id=None,
        saldo_anterior=saldo_anterior,
        saldo_nuevo=cliente.puntos_acumulados,
    ))
    db.flush()
    return {"puntos_expirados": por_expirar, "saldo": cliente.puntos_acumulados}


# ── Niveles ──────────────────────────────────────────────────────────

NIVELES_CONFIG = {
    NivelLealtad.BRONCE: {"min": 0, "max": 499, "multiplicador": 1.0},
    NivelLealtad.PLATA:  {"min": 500, "max": 1499, "multiplicador": 1.5},
    NivelLealtad.ORO:    {"min": 1500, "max": None, "multiplicador": 2.0},
}


def calcular_nivel(puntos_historicos: int) -> NivelLealtad:
    """Determina el nivel de lealtad segun puntos historicos acumulados."""
    if puntos_historicos >= 1500:
        return NivelLealtad.ORO
    if puntos_historicos >= 500:
        return NivelLealtad.PLATA
    return NivelLealtad.BRONCE


def multiplicador_puntos(nivel: NivelLealtad) -> float:
    """Retorna el multiplicador de puntos segun nivel."""
    return NIVELES_CONFIG[nivel]["multiplicador"]


# ── Puntos ───────────────────────────────────────────────────────────

def acumular_puntos(
    db: Session,
    cliente_id: int,
    venta_id: int,
    monto_venta: Decimal,
) -> dict:
    """
    Calcula y acumula puntos por una venta.
    1 punto por cada $10 * multiplicador del nivel.
    Actualiza puntos_acumulados, puntos_totales_historicos y nivel.
    Registra movimiento en HistorialPuntos.
    """
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).with_for_update().first()
    if not cliente:
        raise ValueError("Cliente no encontrado")

    config = obtener_configuracion(db)
    aplicar_expiracion_puntos(db, cliente, config)
    nivel = calcular_nivel(cliente.puntos_totales_historicos)
    mult = multiplicador_puntos(nivel)

    puntos_base = int(monto_venta * puntos_por_peso(config))
    puntos_ganados = int(puntos_base * mult)

    saldo_anterior = cliente.puntos_acumulados
    cliente.puntos_acumulados += puntos_ganados
    cliente.puntos_totales_historicos += puntos_ganados
    cliente.monto_lealtad_acumulado = (
        Decimal(str(cliente.monto_lealtad_acumulado or 0)) + monto_venta
    )

    # Recalcular nivel despues de acumular
    nuevo_nivel = calcular_nivel(cliente.puntos_totales_historicos)
    cliente.nivel_lealtad = nuevo_nivel.value

    historial = HistorialPuntos(
        cliente_id=cliente_id,
        puntos=puntos_ganados,
        concepto=f"Compra (venta #{venta_id}) - x{mult} nivel {nivel.value}",
        venta_id=venta_id,
        saldo_anterior=saldo_anterior,
        saldo_nuevo=cliente.puntos_acumulados,
    )
    db.add(historial)
    db.flush()

    return {
        "puntos_ganados": puntos_ganados,
        "multiplicador": mult,
        "nivel": nuevo_nivel.value,
        "saldo": cliente.puntos_acumulados,
        "monto_acumulado": cliente.monto_lealtad_acumulado,
        "recompensas_disponibles": recompensas_disponibles(cliente, config),
    }


# ── Tarjeta digital QR ──────────────────────────────────────────────

def _url_tarjeta_cliente(qr_code: str) -> str:
    base = settings.FRONTEND_URL.rstrip("/") + "/"
    return f"{base}#cliente/{qr_code}"


def _whatsapp_tarjeta_url(cliente: Cliente) -> str | None:
    if not cliente.telefono or not cliente.tarjeta_qr:
        return None
    tel = "".join(ch for ch in cliente.telefono if ch.isdigit())
    if len(tel) == 10:
        tel = "52" + tel
    if not tel:
        return None
    link = _url_tarjeta_cliente(cliente.tarjeta_qr)
    mensaje = (
        "Hola "
        + cliente.nombre
        + ", aqui esta tu tarjeta de cliente frecuente Jacaranda: "
        + link
    )
    return f"https://wa.me/{tel}?text={quote(mensaje)}"


def recompensas_disponibles(
    cliente: Cliente,
    config: LealtadConfiguracion | None = None,
) -> int:
    monto = Decimal(str(cliente.monto_lealtad_acumulado or 0))
    generadas = int(monto // _monto_meta(config))
    return max(0, generadas - int(cliente.recompensas_lealtad_canjeadas or 0))


def progreso_recompensa(
    cliente: Cliente,
    config: LealtadConfiguracion | None = None,
) -> dict:
    monto = Decimal(str(cliente.monto_lealtad_acumulado or 0))
    meta = _monto_meta(config)
    disponibles = recompensas_disponibles(cliente, config)
    avance_actual = monto % meta
    restante = meta - avance_actual
    if disponibles > 0:
        restante = Decimal("0")
    elif avance_actual == 0 and monto > 0:
        restante = meta
    progreso = Decimal("0")
    if meta > 0:
        progreso = min(
            Decimal("100"),
            (avance_actual / meta) * Decimal("100"),
        )
        if disponibles > 0:
            progreso = Decimal("100")
    return {
        "nombre": _nombre_recompensa(config),
        "monto_meta": float(meta),
        "monto_acumulado": float(monto),
        "monto_restante": float(max(Decimal("0"), restante)),
        "progreso_porcentaje": float(progreso.quantize(Decimal("0.01"))),
        "disponibles": disponibles,
        "canjeadas": int(cliente.recompensas_lealtad_canjeadas or 0),
    }


def _generar_qr_unico(db: Session) -> str:
    for _ in range(5):
        codigo = str(uuid.uuid4())
        existe = db.query(Cliente.id).filter(Cliente.tarjeta_qr == codigo).first()
        if not existe:
            return codigo
    raise ValueError("No se pudo generar una tarjeta unica")

def generar_tarjeta_qr(db: Session, cliente_id: int) -> dict:
    """Genera un UUID unico para la tarjeta QR del cliente."""
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise ValueError("Cliente no encontrado")

    qr_code = cliente.tarjeta_qr or _generar_qr_unico(db)
    cliente.tarjeta_qr = qr_code
    cliente.cliente_frecuente = True
    db.flush()

    return {
        "cliente_id": cliente.id,
        "nombre": cliente.nombre,
        "tarjeta_qr": qr_code,
        "url_publica": _url_tarjeta_cliente(qr_code),
        "whatsapp_url": _whatsapp_tarjeta_url(cliente),
    }


def obtener_tarjeta(db: Session, cliente_id: int) -> dict:
    """Obtiene los datos de la tarjeta de lealtad digital."""
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise ValueError("Cliente no encontrado")
    config = obtener_configuracion(db)
    aplicar_expiracion_puntos(db, cliente, config)

    return {
        "cliente_id": cliente.id,
        "nombre": cliente.nombre,
        "telefono": cliente.telefono,
        "cliente_frecuente": cliente.cliente_frecuente,
        "nivel": cliente.nivel_lealtad,
        "puntos_acumulados": cliente.puntos_acumulados,
        "puntos_totales_historicos": cliente.puntos_totales_historicos,
        "monto_lealtad_acumulado": float(cliente.monto_lealtad_acumulado or 0),
        "recompensa": progreso_recompensa(cliente, config),
        "tarjeta_qr": cliente.tarjeta_qr,
        "url_publica": _url_tarjeta_cliente(cliente.tarjeta_qr) if cliente.tarjeta_qr else None,
        "whatsapp_url": _whatsapp_tarjeta_url(cliente),
    }


def buscar_por_qr(db: Session, qr_code: str) -> Cliente | None:
    """Busca un cliente por su codigo QR de tarjeta digital."""
    return db.query(Cliente).filter(
        Cliente.tarjeta_qr == qr_code,
        Cliente.activo.is_(True),
    ).first()


def obtener_tarjeta_publica(db: Session, qr_code: str) -> dict:
    """Obtiene tarjeta publica sin datos sensibles para el cliente final."""
    cliente = buscar_por_qr(db, qr_code)
    if not cliente:
        raise ValueError("Tarjeta no encontrada")
    config = obtener_configuracion(db)
    aplicar_expiracion_puntos(db, cliente, config)
    return {
        "nombre": cliente.nombre,
        "nivel": cliente.nivel_lealtad,
        "puntos_acumulados": cliente.puntos_acumulados,
        "monto_lealtad_acumulado": float(cliente.monto_lealtad_acumulado or 0),
        "recompensa": progreso_recompensa(cliente, config),
        "programa": {
            "recompensa_nombre": _nombre_recompensa(config),
            "puntos_expiran_dias": config.puntos_expiran_dias,
            "cumpleanos_promo_activa": bool(config.cumpleanos_promo_activa),
        },
        "tarjeta_qr": cliente.tarjeta_qr,
        "url_publica": _url_tarjeta_cliente(cliente.tarjeta_qr),
    }


def historial_cliente_completo(db: Session, cliente_id: int) -> dict:
    """Vista operativa del cliente: compras, puntos y recompensas."""
    from app.models.venta import Venta, EstadoVenta

    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise ValueError("Cliente no encontrado")

    config = obtener_configuracion(db)
    aplicar_expiracion_puntos(db, cliente, config)
    valor = valor_punto(config)

    ventas = (
        db.query(Venta)
        .filter(
            Venta.cliente_id == cliente_id,
            Venta.estado == EstadoVenta.COMPLETADA,
        )
        .order_by(Venta.fecha.desc())
        .limit(50)
        .all()
    )
    movimientos = (
        db.query(HistorialPuntos)
        .filter(HistorialPuntos.cliente_id == cliente_id)
        .order_by(HistorialPuntos.creado_en.desc())
        .limit(100)
        .all()
    )
    recompensas = [v for v in ventas if v.recompensa_lealtad_canjeada]
    total_compras = sum(v.total for v in ventas)

    return {
        "cliente": {
            "id": cliente.id,
            "nombre": cliente.nombre,
            "telefono": cliente.telefono,
            "email": cliente.email,
            "rfc": cliente.rfc,
            "fecha_cumpleanos": (
                cliente.fecha_cumpleanos.isoformat() if cliente.fecha_cumpleanos else None
            ),
            "cliente_frecuente": cliente.cliente_frecuente,
            "tarjeta_qr": cliente.tarjeta_qr,
            "nivel": cliente.nivel_lealtad,
            "puntos": cliente.puntos_acumulados,
        },
        "resumen": {
            "total_compras": float(total_compras),
            "numero_visitas": len(ventas),
            "ticket_promedio": float(total_compras / len(ventas)) if ventas else 0,
            "ultima_visita": ventas[0].fecha.isoformat() if ventas else None,
            "descuento_disponible": float(Decimal(str(cliente.puntos_acumulados)) * valor),
            "valor_punto": float(valor),
            "recompensa": progreso_recompensa(cliente, config),
        },
        "total_compras": float(total_compras),
        "numero_visitas": len(ventas),
        "ticket_promedio": float(total_compras / len(ventas)) if ventas else 0,
        "ultima_visita": ventas[0].fecha.isoformat() if ventas else None,
        "compras": [
            {
                "id": v.id,
                "folio": v.folio,
                "total": float(v.total),
                "fecha": v.fecha.strftime("%Y-%m-%d %H:%M"),
                "metodo_pago": v.metodo_pago.value,
                "recompensa_lealtad_canjeada": v.recompensa_lealtad_canjeada,
                "recompensa_lealtad_nombre": v.recompensa_lealtad_nombre,
                "recompensa_lealtad_monto": float(v.recompensa_lealtad_monto or 0),
            }
            for v in ventas
        ],
        "puntos": [
            {
                "id": m.id,
                "puntos": m.puntos,
                "concepto": m.concepto,
                "venta_id": m.venta_id,
                "saldo_anterior": m.saldo_anterior,
                "saldo_nuevo": m.saldo_nuevo,
                "fecha": m.creado_en.isoformat() if m.creado_en else None,
            }
            for m in movimientos
        ],
        "recompensas": [
            {
                "venta_id": v.id,
                "folio": v.folio,
                "fecha": v.fecha.strftime("%Y-%m-%d %H:%M"),
                "nombre": v.recompensa_lealtad_nombre,
                "monto": float(v.recompensa_lealtad_monto or 0),
            }
            for v in recompensas
        ],
    }


# ── Apple Wallet / Google Wallet ────────────────────────────────────

def _missing_wallet_fields(fields: dict[str, str]) -> list[str]:
    return [name for name, value in fields.items() if not value]


def _public_cliente_por_qr(db: Session, qr_code: str) -> Cliente:
    cliente = buscar_por_qr(db, qr_code)
    if not cliente:
        raise ValueError("Tarjeta no encontrada")
    return cliente


def wallet_status_publico(db: Session, qr_code: str) -> dict:
    cliente = _public_cliente_por_qr(db, qr_code)
    google_missing = _missing_wallet_fields({
        "GOOGLE_WALLET_ISSUER_ID": settings.GOOGLE_WALLET_ISSUER_ID,
        "GOOGLE_WALLET_CLASS_ID": settings.GOOGLE_WALLET_CLASS_ID,
        "GOOGLE_WALLET_SERVICE_ACCOUNT_JSON": (
            settings.GOOGLE_WALLET_SERVICE_ACCOUNT_JSON
            or settings.FIREBASE_SERVICE_ACCOUNT_JSON
        ),
    })
    apple_missing = _missing_wallet_fields({
        "APPLE_WALLET_PASS_TYPE_ID": settings.APPLE_WALLET_PASS_TYPE_ID,
        "APPLE_WALLET_TEAM_ID": settings.APPLE_WALLET_TEAM_ID,
        "APPLE_WALLET_CERT_PEM": settings.APPLE_WALLET_CERT_PEM,
        "APPLE_WALLET_KEY_PEM": settings.APPLE_WALLET_KEY_PEM,
        "APPLE_WALLET_WWDR_PEM": settings.APPLE_WALLET_WWDR_PEM,
    })
    status = {
        "apple_wallet_disponible": not apple_missing,
        "apple_wallet_faltante": apple_missing,
        "apple_wallet_url": None,
        "google_wallet_disponible": not google_missing,
        "google_wallet_faltante": google_missing,
        "google_wallet_url": None,
    }
    if not apple_missing:
        status["apple_wallet_url"] = (
            f"/api/v1/lealtad/publico/{cliente.tarjeta_qr}/apple.pkpass"
        )
    if not google_missing:
        status["google_wallet_url"] = generar_google_wallet_url(db, cliente)
    return status


def _pem_bytes(value: str) -> bytes:
    return value.replace("\\n", "\n").strip().encode("utf-8")


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def generar_apple_pkpass(db: Session, qr_code: str) -> bytes:
    """Genera un .pkpass firmado cuando las credenciales Apple estan configuradas."""
    status = wallet_status_publico(db, qr_code)
    if status["apple_wallet_faltante"]:
        raise ValueError(
            "Faltan credenciales Apple Wallet: "
            + ", ".join(status["apple_wallet_faltante"])
        )

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.serialization import pkcs7

    cliente = _public_cliente_por_qr(db, qr_code)
    config = obtener_configuracion(db)
    recompensa = progreso_recompensa(cliente, config)
    public_url = _url_tarjeta_cliente(cliente.tarjeta_qr)
    serial = "jacaranda-" + re.sub(r"[^A-Za-z0-9.-]", "-", cliente.tarjeta_qr)
    pass_json = {
        "formatVersion": 1,
        "passTypeIdentifier": settings.APPLE_WALLET_PASS_TYPE_ID,
        "serialNumber": serial,
        "teamIdentifier": settings.APPLE_WALLET_TEAM_ID,
        "organizationName": settings.APPLE_WALLET_ORG_NAME or "Jacaranda",
        "description": "Tarjeta de cliente frecuente Jacaranda",
        "logoText": "Jacaranda",
        "foregroundColor": "rgb(74, 53, 48)",
        "backgroundColor": "rgb(250, 243, 240)",
        "labelColor": "rgb(164, 130, 121)",
        "generic": {
            "primaryFields": [
                {"key": "cliente", "label": "Cliente frecuente", "value": cliente.nombre}
            ],
            "secondaryFields": [
                {
                    "key": "acumulado",
                    "label": "Acumulado",
                    "value": f"${Decimal(str(cliente.monto_lealtad_acumulado or 0)):,.2f}",
                },
                {
                    "key": "puntos",
                    "label": "Puntos",
                    "value": str(cliente.puntos_acumulados or 0),
                },
            ],
            "auxiliaryFields": [
                {
                    "key": "recompensa",
                    "label": recompensa["nombre"],
                    "value": (
                        f"{recompensa['disponibles']} disponibles"
                        if recompensa["disponibles"]
                        else f"Faltan ${recompensa['monto_restante']:,.2f}"
                    ),
                }
            ],
            "backFields": [
                {
                    "key": "instrucciones",
                    "label": "Uso",
                    "value": "Presenta este QR en Jacaranda para acumular compras.",
                },
                {"key": "url", "label": "Link", "value": public_url},
            ],
        },
        "barcodes": [
            {
                "message": public_url,
                "format": "PKBarcodeFormatQR",
                "messageEncoding": "iso-8859-1",
                "altText": "Jacaranda",
            }
        ],
        "barcode": {
            "message": public_url,
            "format": "PKBarcodeFormatQR",
            "messageEncoding": "iso-8859-1",
            "altText": "Jacaranda",
        },
    }

    files = {
        "pass.json": json.dumps(pass_json, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        "icon.png": _PNG_1X1,
        "icon@2x.png": _PNG_1X1,
        "logo.png": _PNG_1X1,
        "logo@2x.png": _PNG_1X1,
    }
    manifest = {
        name: hashlib.sha1(content).hexdigest()
        for name, content in sorted(files.items())
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")

    cert = x509.load_pem_x509_certificate(_pem_bytes(settings.APPLE_WALLET_CERT_PEM))
    key = serialization.load_pem_private_key(
        _pem_bytes(settings.APPLE_WALLET_KEY_PEM),
        password=None,
    )
    wwdr = x509.load_pem_x509_certificate(_pem_bytes(settings.APPLE_WALLET_WWDR_PEM))
    builder = pkcs7.PKCS7SignatureBuilder().set_data(manifest_bytes)
    builder = builder.add_signer(cert, key, hashes.SHA256()).add_certificate(wwdr)
    signature = builder.sign(
        serialization.Encoding.DER,
        [pkcs7.PKCS7Options.DetachedSignature],
    )

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
        zf.writestr("manifest.json", manifest_bytes)
        zf.writestr("signature", signature)
    return out.getvalue()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _wallet_service_account() -> dict:
    raw = settings.GOOGLE_WALLET_SERVICE_ACCOUNT_JSON or settings.FIREBASE_SERVICE_ACCOUNT_JSON
    return json.loads(raw)


def _google_class_id() -> str:
    issuer = settings.GOOGLE_WALLET_ISSUER_ID.strip()
    class_id = settings.GOOGLE_WALLET_CLASS_ID.strip()
    if "." in class_id:
        return class_id
    return f"{issuer}.{class_id}"


def generar_google_wallet_url(db: Session, cliente: Cliente) -> str:
    """Genera el Save to Google Wallet URL sin llamar APIs externas."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    service_account = _wallet_service_account()
    config = obtener_configuracion(db)
    recompensa = progreso_recompensa(cliente, config)
    public_url = _url_tarjeta_cliente(cliente.tarjeta_qr)
    issuer = settings.GOOGLE_WALLET_ISSUER_ID.strip()
    object_id = issuer + ".jacaranda_" + re.sub(r"[^A-Za-z0-9_]", "_", cliente.tarjeta_qr)
    payload = {
        "iss": service_account["client_email"],
        "aud": "google",
        "origins": [settings.FRONTEND_URL.rstrip("/")],
        "typ": "savetowallet",
        "payload": {
            "genericObjects": [
                {
                    "id": object_id,
                    "classId": _google_class_id(),
                    "genericType": "GENERIC_TYPE_UNSPECIFIED",
                    "hexBackgroundColor": "#c4988a",
                    "cardTitle": {
                        "defaultValue": {
                            "language": "es-MX",
                            "value": "Jacaranda cliente frecuente",
                        }
                    },
                    "header": {
                        "defaultValue": {"language": "es-MX", "value": cliente.nombre}
                    },
                    "subheader": {
                        "defaultValue": {"language": "es-MX", "value": "sharing flavors"}
                    },
                    "barcode": {
                        "type": "QR_CODE",
                        "value": public_url,
                        "alternateText": "Jacaranda",
                    },
                    "textModulesData": [
                        {
                            "id": "reward",
                            "header": "Recompensa",
                            "body": recompensa["nombre"],
                        },
                        {
                            "id": "progress",
                            "header": "Acumulado",
                            "body": f"${Decimal(str(cliente.monto_lealtad_acumulado or 0)):,.2f}",
                        },
                    ],
                }
            ]
        },
    }
    header = {"alg": "RS256", "typ": "JWT"}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    )
    key = serialization.load_pem_private_key(
        _pem_bytes(service_account["private_key"]),
        password=None,
    )
    signature = key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    token = signing_input + "." + _b64url(signature)
    return "https://pay.google.com/gp/v/save/" + quote(token, safe="")


# ── Cupones ──────────────────────────────────────────────────────────

def crear_cupon(db: Session, data: dict) -> Cupon:
    """Crea un nuevo cupon/promocion."""
    cupon = Cupon(**data)
    db.add(cupon)
    db.flush()
    db.refresh(cupon)
    return cupon


def listar_cupones(db: Session, activos_only: bool = True) -> list[Cupon]:
    """Lista cupones, opcionalmente solo los activos."""
    query = db.query(Cupon)
    if activos_only:
        hoy = operation_today()
        query = query.filter(
            Cupon.activo.is_(True),
            Cupon.estado == EstadoCupon.ACTIVO,
            Cupon.fecha_inicio <= hoy,
            Cupon.fecha_fin >= hoy,
        )
    return query.order_by(Cupon.fecha_fin.desc()).all()


def validar_cupon(
    db: Session,
    codigo: str,
    cliente_id: int | None = None,
    monto_compra: Decimal = Decimal("0"),
) -> dict:
    """
    Valida un cupon. Verifica fechas, usos, nivel requerido y compra minima.
    Retorna dict con valid=True/False y reason.
    """
    cupon = db.query(Cupon).filter(Cupon.codigo == codigo).first()
    if not cupon:
        return {"valid": False, "reason": "Cupon no encontrado"}

    if not cupon.activo or cupon.estado != EstadoCupon.ACTIVO:
        return {"valid": False, "reason": "Cupon inactivo o cancelado"}

    hoy = operation_today()
    if hoy < cupon.fecha_inicio:
        return {"valid": False, "reason": "Cupon aun no vigente"}
    if hoy > cupon.fecha_fin:
        return {"valid": False, "reason": "Cupon expirado"}

    if cupon.usos_actuales >= cupon.max_usos:
        return {"valid": False, "reason": "Cupon agotado (maximo de usos alcanzado)"}

    if cupon.compra_minima and monto_compra < cupon.compra_minima:
        return {
            "valid": False,
            "reason": f"Compra minima requerida: ${cupon.compra_minima}",
        }

    if cupon.nivel_requerido and cliente_id:
        cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
        if cliente:
            nivel_cliente = calcular_nivel(cliente.puntos_totales_historicos)
            niveles_orden = [NivelLealtad.BRONCE, NivelLealtad.PLATA, NivelLealtad.ORO]
            if niveles_orden.index(nivel_cliente) < niveles_orden.index(cupon.nivel_requerido):
                return {
                    "valid": False,
                    "reason": f"Requiere nivel {cupon.nivel_requerido.value} o superior",
                }

    return {
        "valid": True,
        "reason": "Cupon valido",
        "cupon": {
            "id": cupon.id,
            "codigo": cupon.codigo,
            "nombre": cupon.nombre,
            "tipo": cupon.tipo.value,
            "valor": float(cupon.valor),
        },
    }


def canjear_cupon(
    db: Session,
    codigo: str,
    cliente_id: int,
    venta_id: int,
) -> CuponCliente:
    """Marca un cupon como usado por un cliente en una venta."""
    cupon = db.query(Cupon).filter(Cupon.codigo == codigo).first()
    if not cupon:
        raise ValueError("Cupon no encontrado")

    cupon.usos_actuales += 1
    if cupon.usos_actuales >= cupon.max_usos:
        cupon.estado = EstadoCupon.USADO

    registro = CuponCliente(
        cupon_id=cupon.id,
        cliente_id=cliente_id,
        usado=True,
        fecha_uso=datetime.now(timezone.utc),
        venta_id=venta_id,
    )
    db.add(registro)
    db.flush()
    return registro


def asignar_cupon_cliente(db: Session, cupon_id: int, cliente_id: int) -> CuponCliente:
    """Asigna un cupon personal a un cliente."""
    asignacion = CuponCliente(
        cupon_id=cupon_id,
        cliente_id=cliente_id,
    )
    db.add(asignacion)
    db.flush()
    db.refresh(asignacion)
    return asignacion


# ── Cumpleanos ───────────────────────────────────────────────────────

def cumpleanos_del_mes(db: Session) -> list[Cliente]:
    """Lista clientes que cumplen anos este mes."""
    mes_actual = operation_today().month
    return (
        db.query(Cliente)
        .filter(
            Cliente.activo.is_(True),
            Cliente.fecha_cumpleanos.isnot(None),
            extract("month", Cliente.fecha_cumpleanos) == mes_actual,
        )
        .order_by(extract("day", Cliente.fecha_cumpleanos))
        .all()
    )


def enviar_ofertas_cumpleanos(db: Session) -> list[dict]:
    """
    Genera cupones de cumpleanos para clientes que
    cumplen anos este mes y aun no tienen cupon de cumpleanos vigente.
    """
    hoy = operation_today()
    config = obtener_configuracion(db)
    if not config.cumpleanos_promo_activa:
        return []
    descuento = _decimal_config(
        config.cumpleanos_descuento_porcentaje,
        CUMPLEANOS_DESCUENTO_DEFAULT,
    )
    clientes = cumpleanos_del_mes(db)
    resultados = []

    for cliente in clientes:
        # Verificar si ya tiene cupon de cumpleanos este mes
        codigo_cumple = f"CUMPLE-{cliente.id}-{hoy.year}-{hoy.month:02d}"
        existente = db.query(Cupon).filter(Cupon.codigo == codigo_cumple).first()
        if existente:
            continue

        # Crear cupon de cumpleanos, valido todo el mes
        primer_dia = hoy.replace(day=1)
        if hoy.month == 12:
            ultimo_dia = hoy.replace(month=12, day=31)
        else:
            ultimo_dia = hoy.replace(month=hoy.month + 1, day=1) - timedelta(days=1)

        cupon = Cupon(
            codigo=codigo_cumple,
            nombre=f"Feliz cumpleanos {cliente.nombre}",
            descripcion=f"Cupon de cumpleanos - {descuento}% de descuento",
            tipo=TipoCupon.PORCENTAJE,
            valor=descuento,
            compra_minima=Decimal("0"),
            nivel_requerido=None,
            max_usos=1,
            fecha_inicio=primer_dia,
            fecha_fin=ultimo_dia,
            estado=EstadoCupon.ACTIVO,
            activo=True,
        )
        db.add(cupon)
        db.flush()

        # Asignar al cliente
        asignacion = CuponCliente(
            cupon_id=cupon.id,
            cliente_id=cliente.id,
        )
        db.add(asignacion)

        resultados.append({
            "cliente_id": cliente.id,
            "nombre": cliente.nombre,
            "cupon_codigo": codigo_cumple,
        })

    db.flush()
    return resultados


# ── Dashboard ────────────────────────────────────────────────────────

def dashboard_lealtad(db: Session) -> dict:
    """Estadisticas del programa de lealtad."""
    config = obtener_configuracion(db)
    # Clientes por nivel
    niveles = (
        db.query(Cliente.nivel_lealtad, func.count(Cliente.id))
        .filter(Cliente.activo.is_(True))
        .group_by(Cliente.nivel_lealtad)
        .all()
    )
    clientes_por_nivel = {nivel: count for nivel, count in niveles}

    # Total puntos en circulacion
    total_puntos = (
        db.query(func.sum(Cliente.puntos_acumulados))
        .filter(Cliente.activo.is_(True))
        .scalar()
    ) or 0

    # Top clientes por puntos historicos
    top_clientes = (
        db.query(Cliente)
        .filter(Cliente.activo.is_(True))
        .order_by(Cliente.puntos_totales_historicos.desc())
        .limit(10)
        .all()
    )

    # Cupones activos
    hoy = operation_today()
    cupones_activos = (
        db.query(func.count(Cupon.id))
        .filter(
            Cupon.activo.is_(True),
            Cupon.estado == EstadoCupon.ACTIVO,
            Cupon.fecha_fin >= hoy,
        )
        .scalar()
    ) or 0

    return {
        "clientes_por_nivel": clientes_por_nivel,
        "total_puntos_circulacion": total_puntos,
        "top_clientes": [
            {
                "id": c.id,
                "nombre": c.nombre,
                "nivel": c.nivel_lealtad,
                "puntos_acumulados": c.puntos_acumulados,
                "puntos_totales_historicos": c.puntos_totales_historicos,
            }
            for c in top_clientes
        ],
        "cupones_activos": cupones_activos,
        "configuracion": configuracion_dict(config),
    }
