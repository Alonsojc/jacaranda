"""Restricted attendance module. Never calculates wages or mutates the clock."""

import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission, require_role
from app.core.time_utils import operation_datetime
from app.models.asistencia import ChecadaAsistencia, SincronizacionAsistencia, VinculoAsistencia
from app.models.empleado import Empleado
from app.models.usuario import RolUsuario, Usuario
from app.services import asistencia_service as service
from app.services import crosschex_service as cloud
from app.services.auditoria_service import registrar_evento

router = APIRouter(dependencies=[Depends(require_role(
    RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE, RolUsuario.CONTADOR,
))])
read = require_permission("asistencia")
write = require_permission("asistencia", "editar")


class SyncRequest(BaseModel):
    desde: date
    hasta: date


class LinkRequest(BaseModel):
    numero_reloj: str = Field(min_length=1, max_length=80)
    empleado_id: int = Field(gt=0)
    motivo: str = Field(min_length=3, max_length=300)


@router.get("/estado")
def status(response: Response, db: Session = Depends(get_db), user: Usuario = Depends(read)):
    response.headers["Cache-Control"] = "no-store"
    config = cloud.configuration()
    last = db.scalar(select(SincronizacionAsistencia)
                     .where(SincronizacionAsistencia.cuenta == config["cuenta"])
                     .order_by(SincronizacionAsistencia.id.desc()).limit(1))
    return {
        "habilitada": config["habilitada"], "lista": config["lista"],
        "faltantes": config["faltantes"], "region": config["region"],
        "equipos": len(config["devices"]), "zona_horaria": str(service.operation_timezone()),
        "ultima_sincronizacion": operation_datetime(last.completada_en).isoformat() if last else None,
        "nuevas": last.nuevas if last else 0,
    }


@router.post("/sincronizar")
def sync(body: SyncRequest, db: Session = Depends(get_db), user: Usuario = Depends(write)):
    begin, end = service.period_bounds(body.desde, body.hasta, max_days=7)
    config = cloud.configuration()
    if not config["lista"]:
        raise HTTPException(409, "Conexión pendiente de configurar en el servidor.")
    try:
        records, omitted = cloud.fetch_records(begin, end - timedelta(microseconds=1), config)
    except cloud.CrossChexError as exc:
        raise HTTPException(502, str(exc)) from None
    try:
        return service.import_records(db, records, config["cuenta"], begin, end, omitted, user)
    except Exception:
        db.rollback()
        raise


@router.get("/checadas")
def records(response: Response, desde: date, hasta: date,
            buscar: str = Query("", max_length=80), vista: str = Query("diario", pattern="^(diario|marcas)$"),
            pagina: int = Query(1, ge=1), por_pagina: int = Query(25, ge=1, le=100),
            db: Session = Depends(get_db), user: Usuario = Depends(read)):
    response.headers["Cache-Control"] = "no-store"
    begin, end = service.period_bounds(desde, hasta)
    rows = service.query_records(db, cloud.configuration()["cuenta"], begin, end, buscar.strip())
    people = {r["numero_reloj"] for r in rows}
    pending = {r["numero_reloj"] for r in rows if not r["empleado_id"]}
    items = service.daily_summary(rows) if vista == "diario" else rows
    start = (pagina - 1) * por_pagina
    return {"items": items[start:start + por_pagina], "total": len(items), "pagina": pagina,
            "por_pagina": por_pagina, "resumen": {"marcas": len(rows), "personas": len(people), "sin_vincular": len(pending)}}


@router.get("/empleados")
def employees(response: Response, db: Session = Depends(get_db), user: Usuario = Depends(read)):
    response.headers["Cache-Control"] = "no-store"
    rows = db.scalars(select(Empleado).where(Empleado.activo.is_(True)).order_by(Empleado.nombre, Empleado.id)).all()
    return [{"id": e.id, "nombre": service.employee_name(e), "numero_empleado": e.numero_empleado} for e in rows]


@router.post("/vinculos")
def link(body: LinkRequest, db: Session = Depends(get_db), user: Usuario = Depends(write)):
    account = cloud.configuration()["cuenta"]
    if not body.motivo.strip() or len(body.motivo.strip()) < 3:
        raise HTTPException(422, "Indica el motivo de la vinculación.")
    exists = db.scalar(select(ChecadaAsistencia.id).where(
        ChecadaAsistencia.cuenta == account, ChecadaAsistencia.numero_reloj == body.numero_reloj,
    ).limit(1))
    employee = db.get(Empleado, body.empleado_id)
    if not exists or not employee or not employee.activo:
        raise HTTPException(422, "Selecciona una persona del reloj y un empleado activo.")
    old = db.scalar(select(VinculoAsistencia).where(
        VinculoAsistencia.cuenta == account, VinculoAsistencia.numero_reloj == body.numero_reloj,
    ))
    if old:
        if old.empleado_id != body.empleado_id:
            raise HTTPException(409, "Esta persona ya está vinculada. Requiere revisión administrativa.")
        return {"vinculado": True}
    try:
        db.add(VinculoAsistencia(cuenta=account, numero_reloj=body.numero_reloj,
                                empleado_id=body.empleado_id, creado_por_id=user.id))
        registrar_evento(db, user.id, user.nombre, "vincular", "asistencia", entidad="empleados",
                         entidad_id=body.empleado_id, motivo=body.motivo.strip(),
                         datos_nuevos={"numero_reloj": body.numero_reloj, "cuenta": account}, commit=False)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "El empleado o la persona del reloj ya tiene una vinculación.") from None
    return {"vinculado": True}


def csv_cell(value):
    text = str(value if value is not None else "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text


@router.get("/exportar")
def export(desde: date, hasta: date, buscar: str = Query("", max_length=80),
           db: Session = Depends(get_db), user: Usuario = Depends(read)):
    begin, end = service.period_bounds(desde, hasta)
    rows = service.query_records(db, cloud.configuration()["cuenta"], begin, end, buscar.strip())
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Fecha local con zona", "Numero reloj", "Nombre reloj", "Empleado vinculado", "Codigo original", "Equipo", "Serie"])
    for row in rows:
        writer.writerow([csv_cell(row[k]) for k in (
            "fecha", "numero_reloj", "nombre_reloj", "empleado_nombre", "tipo_original", "dispositivo_nombre", "dispositivo",
        )])
    return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "Cache-Control": "no-store", "Content-Disposition": f'attachment; filename="asistencia-{desde}-{hasta}.csv"',
    })
