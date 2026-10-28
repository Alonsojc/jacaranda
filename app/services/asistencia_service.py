"""Attendance evidence queries and atomic, retry-safe imports."""

from collections import OrderedDict
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.time_utils import operation_datetime, operation_timezone
from app.models.asistencia import ChecadaAsistencia, SincronizacionAsistencia, VinculoAsistencia
from app.models.empleado import Empleado
from app.services.auditoria_service import registrar_evento
from app.services.crosschex_service import record_identity

MAX_QUERY_ROWS = 10000


def period_bounds(start: date, end: date, max_days: int = 31):
    if end < start or end == date.max or (end - start).days >= max_days:
        raise HTTPException(422, f"Selecciona un periodo de 1 a {max_days} días.")
    zone = operation_timezone()
    begin = datetime.combine(start, time.min, zone).astimezone(timezone.utc)
    finish = datetime.combine(end + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    return begin, finish


def employee_name(employee):
    return " ".join(v for v in (employee.nombre, employee.apellido_paterno, employee.apellido_materno) if v)


def import_records(db: Session, records, account, begin, end, omitted, user):
    # Uniqueness lives in the database, including concurrent requests/retries.
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    new = 0
    now = datetime.now(timezone.utc)
    for record in records:
        result = db.execute(insert(ChecadaAsistencia).values(
            identidad=record_identity(account, record), cuenta=account,
            numero_reloj=record.employee.workno,
            nombre_reloj=" ".join(v for v in (record.employee.first_name, record.employee.last_name) if v),
            fecha=record.checktime.astimezone(timezone.utc), tipo_original=record.checktype,
            dispositivo=record.device.serial_number, dispositivo_nombre=record.device.name,
            importado_en=now,
        ).on_conflict_do_nothing(index_elements=["identidad"]))
        new += result.rowcount
    repeated = len(records) - new
    sync = SincronizacionAsistencia(
        cuenta=account, desde=begin, hasta=end, nuevas=new, repetidas=repeated,
        omitidas_otro_equipo=omitted, usuario_id=user.id,
    )
    db.add(sync)
    registrar_evento(
        db, user.id, user.nombre, "sincronizar", "asistencia",
        datos_nuevos={"desde": begin, "hasta": end, "nuevas": new,
                      "repetidas": repeated, "omitidas_otro_equipo": omitted}, commit=False,
    )
    db.commit()
    return {"nuevas": new, "repetidas": repeated, "omitidas_otro_equipo": omitted}


def query_records(db, account, begin, end, search=""):
    stmt = select(ChecadaAsistencia).where(
        ChecadaAsistencia.cuenta == account,
        ChecadaAsistencia.fecha >= begin, ChecadaAsistencia.fecha < end,
    )
    if search:
        stmt = stmt.where(
            ChecadaAsistencia.numero_reloj.contains(search, autoescape=True)
            | ChecadaAsistencia.nombre_reloj.icontains(search, autoescape=True)
        )
    rows = db.scalars(stmt.order_by(ChecadaAsistencia.fecha.desc(), ChecadaAsistencia.id.desc())
                      .limit(MAX_QUERY_ROWS + 1)).all()
    if len(rows) > MAX_QUERY_ROWS:
        raise HTTPException(422, "Demasiadas checadas. Reduce el periodo o filtra una persona.")
    links = dict(db.execute(select(VinculoAsistencia.numero_reloj, VinculoAsistencia.empleado_id)
                            .where(VinculoAsistencia.cuenta == account)).all())
    ids = set(links.values())
    employees = {e.id: e for e in db.scalars(select(Empleado).where(Empleado.id.in_(ids))).all()} if ids else {}
    result = []
    for row in rows:
        employee_id = links.get(row.numero_reloj)
        employee = employees.get(employee_id)
        result.append({
            "id": row.id, "numero_reloj": row.numero_reloj, "nombre_reloj": row.nombre_reloj,
            "empleado_id": employee_id, "empleado_nombre": employee_name(employee) if employee else None,
            "fecha": operation_datetime(row.fecha).isoformat(), "tipo_original": row.tipo_original,
            "dispositivo": row.dispositivo, "dispositivo_nombre": row.dispositivo_nombre,
        })
    return result


def daily_summary(records):
    days = OrderedDict()
    for record in records:
        key = (record["fecha"][:10], record["numero_reloj"])
        if key not in days:
            days[key] = {
                "dia": key[0], "numero_reloj": key[1], "nombre_reloj": record["nombre_reloj"],
                "empleado_id": record["empleado_id"], "empleado_nombre": record["empleado_nombre"],
                "primera": record["fecha"], "ultima": record["fecha"], "marcas": 0,
            }
        group = days[key]
        group["marcas"] += 1
        group["primera"] = min(group["primera"], record["fecha"])
        group["ultima"] = max(group["ultima"], record["fecha"])
    for group in days.values():
        if group["marcas"] == 1:
            group["ultima"] = None
    return list(days.values())
