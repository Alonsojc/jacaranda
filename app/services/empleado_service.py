"""
Servicio de gestión de empleados y nómina.
Cumple con LFT, IMSS, ISR nómina.
"""

from decimal import Decimal
from datetime import date, datetime, timezone
from sqlalchemy.orm import Session

from app.models.empleado import Empleado, RegistroNomina, RegistroAsistencia, TipoJornada
from app.schemas.empleado import EmpleadoCreate, EmpleadoUpdate, AsistenciaCreate, NominaCalculoRequest
from app.utils.tax_calculator import (
    calcular_sdi, calcular_isr_retencion_neta, calcular_cuota_imss_trabajador,
    calcular_cuota_imss_patron, calcular_horas_extra, calcular_dias_vacaciones,
    calcular_aguinaldo, calcular_prima_vacacional,
)
from app.core.config import settings


def crear_empleado(db: Session, data: EmpleadoCreate) -> Empleado:
    # Calcular SDI
    antiguedad = 0  # Nuevo ingreso
    sdi = calcular_sdi(data.salario_diario, antiguedad)

    empleado = Empleado(
        **data.model_dump(),
        salario_diario_integrado=sdi,
        dias_vacaciones_pendientes=calcular_dias_vacaciones(0),
    )
    db.add(empleado)
    db.commit()
    db.refresh(empleado)
    return empleado


def actualizar_empleado(db: Session, id: int, data: EmpleadoUpdate) -> Empleado:
    empleado = db.query(Empleado).filter(Empleado.id == id).first()
    if not empleado:
        raise ValueError("Empleado no encontrado")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(empleado, key, value)

    # Recalcular SDI si cambió el salario
    if data.salario_diario is not None:
        antiguedad = _calcular_antiguedad(empleado.fecha_ingreso)
        empleado.salario_diario_integrado = calcular_sdi(
            empleado.salario_diario, antiguedad
        )

    db.commit()
    db.refresh(empleado)
    return empleado


def obtener_empleado(db: Session, id: int) -> Empleado:
    empleado = db.query(Empleado).filter(Empleado.id == id).first()
    if not empleado:
        raise ValueError("Empleado no encontrado")
    return empleado


def listar_empleados(db: Session, solo_activos: bool = True):
    query = db.query(Empleado)
    if solo_activos:
        query = query.filter(Empleado.activo.is_(True))
    return query.all()


def _calcular_antiguedad(fecha_ingreso: date) -> int:
    hoy = date.today()
    return (hoy - fecha_ingreso).days // 365


def _horas_jornada(tipo: TipoJornada) -> int:
    return {
        TipoJornada.DIURNA: 8,
        TipoJornada.NOCTURNA: 7,
        TipoJornada.MIXTA: 7,  # 7.5 redondeado
    }[tipo]


# --- Asistencia ---

def registrar_asistencia(db: Session, data: AsistenciaCreate) -> RegistroAsistencia:
    empleado = obtener_empleado(db, data.empleado_id)
    horas_jornada = _horas_jornada(empleado.tipo_jornada)

    horas_trabajadas = Decimal("0")
    horas_extra = Decimal("0")

    if data.hora_entrada and data.hora_salida:
        diff = (data.hora_salida - data.hora_entrada).total_seconds() / 3600
        horas_trabajadas = Decimal(str(round(diff, 2)))
        if horas_trabajadas > horas_jornada:
            horas_extra = horas_trabajadas - Decimal(str(horas_jornada))

    registro = RegistroAsistencia(
        empleado_id=data.empleado_id,
        fecha=data.fecha,
        hora_entrada=data.hora_entrada,
        hora_salida=data.hora_salida,
        horas_trabajadas=horas_trabajadas,
        horas_extra=horas_extra,
        es_dia_festivo=data.es_dia_festivo,
        es_dia_descanso=data.es_dia_descanso,
        notas=data.notas,
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


# --- Nómina ---

def calcular_nomina(db: Session, data: NominaCalculoRequest) -> RegistroNomina:
    """
    Calcula nómina de un empleado para un periodo.
    Aplica ISR Art. 96, cuotas IMSS, y prestaciones LFT.
    """
    empleado = obtener_empleado(db, data.empleado_id)
    antiguedad = _calcular_antiguedad(empleado.fecha_ingreso)
    horas_jornada = _horas_jornada(empleado.tipo_jornada)

    dias_periodo = (data.periodo_fin - data.periodo_inicio).days + 1

    # Salario base del periodo
    salario_base = empleado.salario_diario * Decimal(str(dias_periodo))

    # Horas extra del periodo
    asistencias = db.query(RegistroAsistencia).filter(
        RegistroAsistencia.empleado_id == data.empleado_id,
        RegistroAsistencia.fecha >= data.periodo_inicio,
        RegistroAsistencia.fecha <= data.periodo_fin,
    ).all()

    total_horas_extra = sum(a.horas_extra for a in asistencias)
    horas_dobles = min(total_horas_extra, Decimal("9"))
    horas_triples = max(total_horas_extra - Decimal("9"), Decimal("0"))
    monto_horas_extra = calcular_horas_extra(
        empleado.salario_diario, horas_jornada, total_horas_extra
    )

    # Prestaciones opcionales
    monto_aguinaldo = Decimal("0")
    monto_prima_vac = Decimal("0")
    monto_ptu = Decimal("0")

    if data.incluir_aguinaldo:
        monto_aguinaldo = calcular_aguinaldo(
            empleado.salario_diario,
            min(dias_periodo, 365),
            settings.AGUINALDO_DIAS_MINIMO,
        )

    if data.incluir_prima_vacacional:
        dias_vac = calcular_dias_vacaciones(antiguedad)
        monto_prima_vac = calcular_prima_vacacional(
            empleado.salario_diario, dias_vac
        )

    # Total percepciones
    total_percepciones = (
        salario_base + monto_horas_extra + monto_aguinaldo + monto_prima_vac + monto_ptu
    )

    # Calcular ISR (mensualizar para aplicar tabla)
    factor_mensual = Decimal("30") / Decimal(str(dias_periodo))
    ingreso_mensual = total_percepciones * factor_mensual
    isr_mensual = calcular_isr_retencion_neta(ingreso_mensual)
    isr_periodo = (isr_mensual / factor_mensual).quantize(Decimal("0.01"))

    # Calcular IMSS trabajador
    sdi = empleado.salario_diario_integrado
    imss_trabajador = calcular_cuota_imss_trabajador(
        sdi, dias_periodo, settings.UMA_DIARIO
    )

    # Calcular IMSS patronal
    imss_patron = calcular_cuota_imss_patron(
        sdi, dias_periodo, settings.UMA_DIARIO
    )

    # INFONAVIT patronal
    infonavit_patron = (sdi * Decimal(str(dias_periodo)) * Decimal("0.05")).quantize(
        Decimal("0.01")
    )

    total_deducciones = isr_periodo + imss_trabajador
    neto = total_percepciones - total_deducciones

    registro = RegistroNomina(
        empleado_id=empleado.id,
        periodo_inicio=data.periodo_inicio,
        periodo_fin=data.periodo_fin,
        salario_base=salario_base,
        horas_extra_dobles=horas_dobles,
        horas_extra_triples=horas_triples,
        monto_horas_extra=monto_horas_extra,
        aguinaldo=monto_aguinaldo,
        prima_vacacional=monto_prima_vac,
        ptu=monto_ptu,
        total_percepciones=total_percepciones,
        isr_retenido=isr_periodo,
        imss_trabajador=imss_trabajador,
        imss_patron=imss_patron,
        infonavit_patron=infonavit_patron,
        total_deducciones=total_deducciones,
        neto_a_pagar=neto,
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


def listar_nominas(db: Session, empleado_id: int | None = None):
    query = db.query(RegistroNomina)
    if empleado_id:
        query = query.filter(RegistroNomina.empleado_id == empleado_id)
    return query.order_by(RegistroNomina.periodo_inicio.desc()).all()
