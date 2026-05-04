"""
Servicio de auditoría y seguridad.
Registro de eventos, detección de anomalías y respaldo de base de datos.
"""

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from sqlalchemy import func, and_, extract
from sqlalchemy.orm import Session

from app.models.auditoria import LogAuditoria
from app.core.config import settings


# ---------------------------------------------------------------------------
# Registro de eventos
# ---------------------------------------------------------------------------

def registrar_evento(
    db: Session,
    usuario_id: int | None,
    usuario_nombre: str | None,
    accion: str,
    modulo: str,
    entidad: str | None = None,
    entidad_id: int | None = None,
    datos_anteriores: dict | None = None,
    datos_nuevos: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    commit: bool = True,
) -> LogAuditoria:
    """Crea una entrada en el log de auditoría."""
    if usuario_id is not None and not usuario_nombre:
        try:
            from app.models.usuario import Usuario

            usuario = db.get(Usuario, usuario_id)
            if usuario:
                usuario_nombre = usuario.nombre
        except Exception:
            usuario_nombre = None

    evento = LogAuditoria(
        usuario_id=usuario_id,
        usuario_nombre=usuario_nombre,
        accion=accion,
        modulo=modulo,
        entidad=entidad,
        entidad_id=entidad_id,
        datos_anteriores=json.dumps(datos_anteriores, default=str) if datos_anteriores else None,
        datos_nuevos=json.dumps(datos_nuevos, default=str) if datos_nuevos else None,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(evento)
    if commit:
        db.commit()
        db.refresh(evento)
    else:
        db.flush()
    return evento


# ---------------------------------------------------------------------------
# Consulta de eventos
# ---------------------------------------------------------------------------

def listar_eventos(
    db: Session,
    usuario_id: int | None = None,
    modulo: str | None = None,
    accion: str | None = None,
    fecha_inicio: datetime | None = None,
    fecha_fin: datetime | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[LogAuditoria]:
    """Lista eventos de auditoría con filtros opcionales, ordenados por más reciente."""
    query = db.query(LogAuditoria)

    if usuario_id is not None:
        query = query.filter(LogAuditoria.usuario_id == usuario_id)
    if modulo:
        query = query.filter(LogAuditoria.modulo == modulo)
    if accion:
        query = query.filter(LogAuditoria.accion == accion)
    if fecha_inicio:
        query = query.filter(LogAuditoria.creado_en >= fecha_inicio)
    if fecha_fin:
        query = query.filter(LogAuditoria.creado_en <= fecha_fin)

    return (
        query.order_by(LogAuditoria.creado_en.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def obtener_evento(db: Session, evento_id: int) -> LogAuditoria | None:
    """Retorna un evento de auditoría por su ID."""
    return db.query(LogAuditoria).filter(LogAuditoria.id == evento_id).first()


# ---------------------------------------------------------------------------
# Actividad de usuario
# ---------------------------------------------------------------------------

def actividad_usuario(db: Session, usuario_id: int, dias: int = 30) -> dict:
    """Resumen de actividad de un usuario en los últimos N días."""
    fecha_limite = datetime.now(timezone.utc) - timedelta(days=dias)

    eventos = (
        db.query(LogAuditoria)
        .filter(
            and_(
                LogAuditoria.usuario_id == usuario_id,
                LogAuditoria.creado_en >= fecha_limite,
            )
        )
        .all()
    )

    por_modulo: dict[str, int] = defaultdict(int)
    por_accion: dict[str, int] = defaultdict(int)
    por_dia: dict[str, int] = defaultdict(int)

    for ev in eventos:
        por_modulo[ev.modulo] += 1
        por_accion[ev.accion] += 1
        dia = ev.creado_en.strftime("%Y-%m-%d") if ev.creado_en else "desconocido"
        por_dia[dia] += 1

    return {
        "usuario_id": usuario_id,
        "dias": dias,
        "total_acciones": len(eventos),
        "por_modulo": dict(por_modulo),
        "por_accion": dict(por_accion),
        "linea_tiempo": dict(sorted(por_dia.items())),
    }


# ---------------------------------------------------------------------------
# Detección de anomalías
# ---------------------------------------------------------------------------

def detectar_anomalias(db: Session, dias: int = 7) -> list[dict]:
    """
    Detecta patrones inusuales en los últimos N días:
    - Ventas fuera de horario (antes de 6 AM o después de 11 PM)
    - Múltiples intentos de login fallido
    - Ajustes de inventario con cantidades altas
    - Cancelaciones de venta por encima de lo normal
    """
    fecha_limite = datetime.now(timezone.utc) - timedelta(days=dias)
    anomalias: list[dict] = []

    eventos = (
        db.query(LogAuditoria)
        .filter(LogAuditoria.creado_en >= fecha_limite)
        .all()
    )

    # 1. Ventas fuera de horario
    for ev in eventos:
        if ev.modulo == "ventas" and ev.accion == "crear" and ev.creado_en:
            hora = ev.creado_en.hour
            if hora < 6 or hora >= 23:
                anomalias.append({
                    "tipo": "venta_fuera_horario",
                    "descripcion": f"Venta registrada a las {ev.creado_en.strftime('%H:%M')} por {ev.usuario_nombre}",
                    "severidad": "media",
                    "fecha": ev.creado_en.isoformat(),
                    "usuario": ev.usuario_nombre,
                })

    # 2. Múltiples intentos de login fallido por usuario
    intentos_fallidos: dict[str, list] = defaultdict(list)
    for ev in eventos:
        if ev.accion == "login_fallido":
            clave = ev.ip_address or ev.usuario_nombre or "desconocido"
            intentos_fallidos[clave].append(ev)

    for clave, evs in intentos_fallidos.items():
        if len(evs) >= 5:
            anomalias.append({
                "tipo": "login_fallido_multiple",
                "descripcion": f"{len(evs)} intentos de login fallido desde {clave} en {dias} días",
                "severidad": "alta",
                "fecha": evs[-1].creado_en.isoformat() if evs[-1].creado_en else None,
                "usuario": evs[-1].usuario_nombre,
            })

    # 3. Ajustes de inventario con cantidades altas
    for ev in eventos:
        if ev.modulo == "inventario" and ev.accion in ("actualizar", "crear") and ev.datos_nuevos:
            try:
                datos = json.loads(ev.datos_nuevos)
                cantidad = datos.get("cantidad")
                if cantidad is not None and float(cantidad) > 1000:
                    anomalias.append({
                        "tipo": "ajuste_inventario_inusual",
                        "descripcion": (
                            f"Ajuste de inventario con cantidad {cantidad} "
                            f"por {ev.usuario_nombre}"
                        ),
                        "severidad": "media",
                        "fecha": ev.creado_en.isoformat() if ev.creado_en else None,
                        "usuario": ev.usuario_nombre,
                    })
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

    # 4. Cancelaciones por encima de lo normal
    cancelaciones_por_usuario: dict[str, int] = defaultdict(int)
    for ev in eventos:
        if ev.modulo == "ventas" and ev.accion == "eliminar":
            nombre = ev.usuario_nombre or "desconocido"
            cancelaciones_por_usuario[nombre] += 1

    for nombre, total in cancelaciones_por_usuario.items():
        if total >= 10:
            anomalias.append({
                "tipo": "cancelaciones_excesivas",
                "descripcion": f"{total} cancelaciones de venta por {nombre} en {dias} días",
                "severidad": "alta",
                "fecha": datetime.now(timezone.utc).isoformat(),
                "usuario": nombre,
            })

    return anomalias


# ---------------------------------------------------------------------------
# Reporte de actividad
# ---------------------------------------------------------------------------

def reporte_actividad(
    db: Session,
    fecha_inicio: datetime,
    fecha_fin: datetime,
) -> dict:
    """Reporte de actividad en un rango de fechas."""
    eventos = (
        db.query(LogAuditoria)
        .filter(
            and_(
                LogAuditoria.creado_en >= fecha_inicio,
                LogAuditoria.creado_en <= fecha_fin,
            )
        )
        .all()
    )

    por_usuario: dict[str, int] = defaultdict(int)
    por_modulo: dict[str, int] = defaultdict(int)
    por_hora: dict[int, int] = defaultdict(int)

    for ev in eventos:
        nombre = ev.usuario_nombre or "sistema"
        por_usuario[nombre] += 1
        por_modulo[ev.modulo] += 1
        if ev.creado_en:
            por_hora[ev.creado_en.hour] += 1

    # Horas pico: las 5 horas con más actividad
    horas_pico = sorted(por_hora.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "fecha_inicio": fecha_inicio.isoformat(),
        "fecha_fin": fecha_fin.isoformat(),
        "total_eventos": len(eventos),
        "eventos_por_usuario": dict(por_usuario),
        "eventos_por_modulo": dict(por_modulo),
        "horas_pico": [{"hora": h, "cantidad": c} for h, c in horas_pico],
        "anomalias": detectar_anomalias(db, dias=max(1, (fecha_fin - fecha_inicio).days)),
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def dashboard_auditoria(db: Session) -> dict:
    """Resumen del tablero de auditoría."""
    ahora = datetime.now(timezone.utc)
    inicio_hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    inicio_semana = inicio_hoy - timedelta(days=inicio_hoy.weekday())

    total_hoy = (
        db.query(func.count(LogAuditoria.id))
        .filter(LogAuditoria.creado_en >= inicio_hoy)
        .scalar()
    ) or 0

    total_semana = (
        db.query(func.count(LogAuditoria.id))
        .filter(LogAuditoria.creado_en >= inicio_semana)
        .scalar()
    ) or 0

    usuarios_activos_hoy = (
        db.query(func.count(func.distinct(LogAuditoria.usuario_id)))
        .filter(LogAuditoria.creado_en >= inicio_hoy)
        .scalar()
    ) or 0

    ultimos_eventos = (
        db.query(LogAuditoria)
        .order_by(LogAuditoria.creado_en.desc())
        .limit(20)
        .all()
    )

    anomalias_recientes = detectar_anomalias(db, dias=7)

    return {
        "total_eventos_hoy": total_hoy,
        "eventos_semana": total_semana,
        "usuarios_activos_hoy": usuarios_activos_hoy,
        "anomalias_recientes": anomalias_recientes,
        "ultimos_eventos": [
            {
                "id": ev.id,
                "usuario_nombre": ev.usuario_nombre,
                "accion": ev.accion,
                "modulo": ev.modulo,
                "entidad": ev.entidad,
                "entidad_id": ev.entidad_id,
                "creado_en": ev.creado_en.isoformat() if ev.creado_en else None,
            }
            for ev in ultimos_eventos
        ],
    }


# ---------------------------------------------------------------------------
# Respaldo de base de datos
# ---------------------------------------------------------------------------

def respaldar_base_datos(db: Session) -> dict:
    """
    Crea una copia de respaldo del archivo SQLite con marca de tiempo.
    Retorna información del archivo generado.
    """
    # Extraer la ruta del archivo SQLite desde la URL de configuración
    db_url = settings.DATABASE_URL
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
    else:
        raise ValueError("El respaldo solo está disponible para bases de datos SQLite")

    # Resolver ruta relativa
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.getcwd(), db_path)

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Archivo de base de datos no encontrado: {db_path}")

    # Crear directorio de respaldos
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(backup_dir, exist_ok=True)

    # Nombre del respaldo con timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"jacaranda_backup_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)

    # Copiar el archivo
    shutil.copy2(db_path, backup_path)

    # Calcular tamaño en MB
    tamano_bytes = os.path.getsize(backup_path)
    tamano_mb = round(tamano_bytes / (1024 * 1024), 2)

    # Registrar evento de respaldo
    registrar_evento(
        db=db,
        usuario_id=None,
        usuario_nombre="sistema",
        accion="crear",
        modulo="auditoria",
        entidad="respaldo",
        datos_nuevos={"archivo": backup_filename, "tamano_mb": tamano_mb},
    )

    return {
        "archivo": backup_filename,
        "tamano_mb": tamano_mb,
        "fecha": datetime.now(timezone.utc).isoformat(),
    }
