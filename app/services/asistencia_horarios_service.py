"""Weekly schedules with dated changes. Clock marks are stored independently."""

from collections import defaultdict
from datetime import date, timedelta
from unicodedata import normalize

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from app.models.asistencia import HorarioSemanalAsistencia, PersonaHorarioAsistencia, TurnoFechaAsistencia
from app.services.asistencia_service import daily_summary, period_bounds, query_records
from app.services.auditoria_service import registrar_evento


def _insert(db, model):
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    return insert(model)


def personas(db, cuenta):
    rows = db.scalars(select(PersonaHorarioAsistencia).order_by(PersonaHorarioAsistencia.nombre_normalizado))
    return [{"id": row.id, "nombre": row.nombre,
             "numero_reloj": row.numero_reloj if row.cuenta_reloj == cuenta else None} for row in rows]


def alta_persona(db, nombre, numero_reloj, cuenta, user):
    nombre = " ".join(nombre.split())
    key = normalize("NFC", nombre).casefold()
    stmt = _insert(db, PersonaHorarioAsistencia).values(nombre=nombre, nombre_normalizado=key)
    new_id = db.scalar(stmt.on_conflict_do_nothing(index_elements=["nombre_normalizado"])
                       .returning(PersonaHorarioAsistencia.id))
    if new_id is not None:
        registrar_evento(db, user.id, user.nombre, "alta_persona_horario", "asistencia",
                         entidad="horarios", entidad_id=new_id, datos_nuevos={"nombre": nombre}, commit=False)
    persona = db.execute(select(PersonaHorarioAsistencia.id, PersonaHorarioAsistencia.nombre)
                         .where(PersonaHorarioAsistencia.nombre_normalizado == key)).one()
    if numero_reloj is not None:
        vincular_reloj(db, persona.id, numero_reloj, cuenta, user)
    db.commit()
    return {"id": persona.id, "nombre": persona.nombre}


def persona_existente(db, persona_id):
    persona = db.get(PersonaHorarioAsistencia, persona_id)
    if persona is None:
        raise HTTPException(404, "La persona no está en el calendario de asistencia.")
    return persona


def vincular_reloj(db, persona_id, numero, cuenta, user):
    if not cuenta:
        raise HTTPException(409, "Configura la cuenta de CrossChex antes de vincular el número del reloj.")
    try:
        new_link = db.scalar(update(PersonaHorarioAsistencia).where(
            PersonaHorarioAsistencia.id == persona_id, PersonaHorarioAsistencia.numero_reloj.is_(None),
        ).values(cuenta_reloj=cuenta, numero_reloj=numero).returning(PersonaHorarioAsistencia.id))
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ese número de reloj ya está vinculado a otra persona.") from None
    if new_link is not None:
        registrar_evento(db, user.id, user.nombre, "vincular_reloj_horario", "asistencia",
                         entidad="horarios", entidad_id=persona_id, datos_nuevos={"numero_reloj": numero}, commit=False)
        return
    persona = persona_existente(db, persona_id)
    if (persona.cuenta_reloj, persona.numero_reloj) != (cuenta, numero):
        raise HTTPException(409, "La persona ya tiene un vínculo con el reloj. Requiere revisión administrativa.")


def configuracion(db, persona_id, fecha):
    persona_existente(db, persona_id)
    semanal = db.scalar(select(HorarioSemanalAsistencia).where(
        HorarioSemanalAsistencia.persona_id == persona_id,
        HorarioSemanalAsistencia.vigente_desde <= fecha,
    ).order_by(HorarioSemanalAsistencia.vigente_desde.desc()).limit(1))
    puntual = db.get(TurnoFechaAsistencia, (persona_id, fecha))
    return {
        "semanal": {"vigente_desde": semanal.vigente_desde, "dias": semanal.dias,
                    "modalidad": semanal.modalidad, "nota": semanal.nota} if semanal else None,
        "fecha": {"tipo": puntual.tipo, "horas": puntual.horas,
                  "modalidad": puntual.modalidad, "nota": puntual.nota} if puntual else None,
    }


def _minutos(hora):
    return int(hora[:2]) * 60 + int(hora[3:])


def calendario(db, desde: date, hasta: date, cuenta: str):
    begin, end = period_bounds(desde, hasta)
    dias = (hasta - desde).days + 1
    semanal = HorarioSemanalAsistencia
    anterior = select(semanal.persona_id, func.max(semanal.vigente_desde)).where(
        semanal.vigente_desde < desde,
    ).group_by(semanal.persona_id)
    versiones = defaultdict(list)
    for row in db.scalars(select(semanal).where(
        semanal.vigente_desde <= hasta,
        or_(semanal.vigente_desde >= desde, tuple_(semanal.persona_id, semanal.vigente_desde).in_(anterior)),
    ).order_by(semanal.persona_id, semanal.vigente_desde)):
        versiones[row.persona_id].append(row)
    excepciones = {(row.persona_id, row.fecha): row for row in db.scalars(
        select(TurnoFechaAsistencia).where(TurnoFechaAsistencia.fecha.between(desde, hasta))
    )}

    personal = personas(db, cuenta)
    relojes = {p["numero_reloj"]: p["id"] for p in personal if p["numero_reloj"] is not None}
    pares = {}
    if relojes:
        marks = query_records(db, cuenta, begin, end, numbers=relojes.keys())
        pares = {(relojes[row["numero_reloj"]], date.fromisoformat(row["dia"])): row for row in daily_summary(marks)}

    turnos = defaultdict(list)
    resumen = []
    for persona in personal:
        persona_id = persona["id"]
        cambios = iter(versiones[persona_id])
        siguiente = next(cambios, None)
        vigente = None
        minutos, segundos, dias_revision = 0, None, 0
        for offset in range(dias):
            dia = desde + timedelta(days=offset)
            registros = pares.get((persona_id, dia), {})
            tiempo = registros.get("segundos_completos")
            revisar = registros.get("estado_calculo") == "revisar"
            while siguiente is not None and siguiente.vigente_desde <= dia:
                vigente, siguiente = siguiente, next(cambios, None)
            puntual = excepciones.get((persona_id, dia))
            if puntual is not None:
                tipo, horas, modalidad, nota = puntual.tipo, puntual.horas, puntual.modalidad, puntual.nota
            else:
                horas = vigente.dias.get(str(dia.weekday())) if vigente else None
                if horas is not None:
                    tipo, modalidad, nota = "semanal", vigente.modalidad, vigente.nota
                elif registros:
                    tipo, modalidad, nota = "sin_turno", "sucursal", ""
                else:
                    continue
            if horas:
                minutos += _minutos(horas["salida"]) - _minutos(horas["entrada"])
            if tiempo is not None:
                segundos = (segundos or 0) + tiempo
            dias_revision += int(revisar)
            turnos[dia].append({"fecha": dia, "persona_id": persona_id, "nombre": persona["nombre"],
                                "tipo": tipo, "horas": horas, "modalidad": modalidad, "nota": nota,
                                "segundos_registrados": tiempo, "revisar_marcas": revisar})
        resumen.append({**persona, "minutos_programados": minutos, "segundos_registrados": segundos,
                        "dias_por_revisar": dias_revision})
    return {"personas": personal, "resumen": resumen,
            "items": [item for dia in sorted(turnos) for item in turnos[dia]]}


def guardar(db, model, persona_id, llave, datos, user):
    persona_existente(db, persona_id)
    stmt = _insert(db, model).values(persona_id=persona_id, **llave, **datos)
    db.execute(stmt.on_conflict_do_update(
        index_elements=["persona_id", *llave], set_={campo: stmt.excluded[campo] for campo in datos},
    ))
    registrar_evento(db, user.id, user.nombre, "programar_turno", "asistencia",
                     entidad="horarios", entidad_id=persona_id, datos_nuevos={**llave, **datos}, commit=False)
    db.commit()


def restaurar_semanal(db, persona_id, fecha, user):
    persona_existente(db, persona_id)
    eliminado = db.execute(delete(TurnoFechaAsistencia).where(
        TurnoFechaAsistencia.persona_id == persona_id, TurnoFechaAsistencia.fecha == fecha,
    ).returning(TurnoFechaAsistencia)).scalar_one_or_none()
    if eliminado is not None:
        registrar_evento(db, user.id, user.nombre, "restaurar_horario_semanal", "asistencia",
                         entidad="horarios", entidad_id=persona_id,
                         datos_anteriores={"fecha": fecha, "tipo": eliminado.tipo, "horas": eliminado.horas,
                                           "modalidad": eliminado.modalidad, "nota": eliminado.nota}, commit=False)
    db.commit()
