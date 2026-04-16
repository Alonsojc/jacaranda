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


def listar_empleados(db: Session, solo_activos: bool = True, skip: int = 0, limit: int = 100):
    query = db.query(Empleado)
    if solo_activos:
        query = query.filter(Empleado.activo.is_(True))
    return query.offset(skip).limit(limit).all()


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


def listar_nominas(db: Session, empleado_id: int | None = None, skip: int = 0, limit: int = 100):
    query = db.query(RegistroNomina)
    if empleado_id:
        query = query.filter(RegistroNomina.empleado_id == empleado_id)
    return query.order_by(RegistroNomina.periodo_inicio.desc()).offset(skip).limit(limit).all()


def calcular_nomina_batch(
    db: Session, periodo_inicio: date, periodo_fin: date
) -> list[RegistroNomina]:
    """Calcula nómina para TODOS los empleados activos en un periodo."""
    empleados_activos = listar_empleados(db, solo_activos=True)
    if not empleados_activos:
        raise ValueError("No hay empleados activos para calcular nómina")

    resultados: list[RegistroNomina] = []
    errores: list[dict] = []

    for empleado in empleados_activos:
        try:
            req = NominaCalculoRequest(
                empleado_id=empleado.id,
                periodo_inicio=periodo_inicio,
                periodo_fin=periodo_fin,
                incluir_aguinaldo=False,
                incluir_prima_vacacional=False,
                incluir_ptu=False,
            )
            registro = calcular_nomina(db, req)
            resultados.append(registro)
        except Exception as e:
            errores.append({
                "empleado_id": empleado.id,
                "nombre": f"{empleado.nombre} {empleado.apellido_paterno}",
                "error": str(e),
            })

    if not resultados and errores:
        raise ValueError(
            f"No se pudo calcular nómina para ningún empleado. "
            f"Errores: {errores}"
        )

    return resultados


def generar_recibo_nomina_pdf(db: Session, nomina_id: int):
    """Genera un PDF de recibo de nómina para un registro específico."""
    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm, cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    )
    from app.services.pdf_service import _header, _tabla

    registro = db.query(RegistroNomina).filter(RegistroNomina.id == nomina_id).first()
    if not registro:
        raise ValueError("Registro de nómina no encontrado")

    empleado = db.query(Empleado).filter(Empleado.id == registro.empleado_id).first()
    if not empleado:
        raise ValueError("Empleado no encontrado")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    story = []

    # Header
    _header(
        story, styles,
        "Recibo de Nómina",
        f"Periodo: {registro.periodo_inicio.isoformat()} al {registro.periodo_fin.isoformat()}",
    )

    # Datos del empleado
    nombre_completo = (
        f"{empleado.nombre} {empleado.apellido_paterno}"
        f"{' ' + empleado.apellido_materno if empleado.apellido_materno else ''}"
    )
    emp_data = [
        ["Empleado", nombre_completo],
        ["No. Empleado", empleado.numero_empleado],
        ["RFC", empleado.rfc],
        ["CURP", empleado.curp],
        ["NSS", empleado.nss],
        ["Departamento", empleado.departamento.value.capitalize()],
        ["Puesto", empleado.puesto],
    ]
    emp_table = Table(emp_data, colWidths=[5 * cm, 11 * cm])
    emp_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(emp_table)
    story.append(Spacer(1, 6 * mm))

    # Percepciones
    story.append(Paragraph("<b>PERCEPCIONES</b>", styles["Heading3"]))
    perc_data = [["Concepto", "Monto"]]
    perc_data.append(["Salario base", f"${float(registro.salario_base):,.2f}"])
    if registro.monto_horas_extra > 0:
        perc_data.append([
            f"Horas extra (dobles: {float(registro.horas_extra_dobles)}, "
            f"triples: {float(registro.horas_extra_triples)})",
            f"${float(registro.monto_horas_extra):,.2f}",
        ])
    if registro.premio_puntualidad > 0:
        perc_data.append(["Premio puntualidad", f"${float(registro.premio_puntualidad):,.2f}"])
    if registro.premio_asistencia > 0:
        perc_data.append(["Premio asistencia", f"${float(registro.premio_asistencia):,.2f}"])
    if registro.bono_productividad > 0:
        perc_data.append(["Bono productividad", f"${float(registro.bono_productividad):,.2f}"])
    if registro.aguinaldo > 0:
        perc_data.append(["Aguinaldo", f"${float(registro.aguinaldo):,.2f}"])
    if registro.prima_vacacional > 0:
        perc_data.append(["Prima vacacional", f"${float(registro.prima_vacacional):,.2f}"])
    if registro.ptu > 0:
        perc_data.append(["PTU", f"${float(registro.ptu):,.2f}"])
    perc_data.append(["TOTAL PERCEPCIONES", f"${float(registro.total_percepciones):,.2f}"])
    story.append(_tabla(perc_data, col_widths=[10 * cm, 5 * cm]))
    story.append(Spacer(1, 6 * mm))

    # Deducciones
    story.append(Paragraph("<b>DEDUCCIONES</b>", styles["Heading3"]))
    ded_data = [["Concepto", "Monto"]]
    ded_data.append(["ISR retenido", f"${float(registro.isr_retenido):,.2f}"])
    ded_data.append(["IMSS trabajador", f"${float(registro.imss_trabajador):,.2f}"])
    if registro.infonavit > 0:
        ded_data.append(["INFONAVIT", f"${float(registro.infonavit):,.2f}"])
    if registro.fonacot > 0:
        ded_data.append(["FONACOT", f"${float(registro.fonacot):,.2f}"])
    if registro.otras_deducciones > 0:
        ded_data.append(["Otras deducciones", f"${float(registro.otras_deducciones):,.2f}"])
    ded_data.append(["TOTAL DEDUCCIONES", f"${float(registro.total_deducciones):,.2f}"])
    story.append(_tabla(ded_data, col_widths=[10 * cm, 5 * cm]))
    story.append(Spacer(1, 6 * mm))

    # Neto a pagar
    neto_style = ParagraphStyle(
        "Neto", parent=styles["Normal"],
        fontSize=14, fontName="Helvetica-Bold",
    )
    story.append(Paragraph(
        f"NETO A PAGAR: ${float(registro.neto_a_pagar):,.2f}", neto_style
    ))
    story.append(Spacer(1, 4 * mm))

    # Cuotas patronales (informativo)
    story.append(Paragraph("<b>Cuotas patronales (informativo)</b>", styles["Heading3"]))
    patron_data = [
        ["Concepto", "Monto"],
        ["IMSS patronal", f"${float(registro.imss_patron):,.2f}"],
        ["INFONAVIT patronal", f"${float(registro.infonavit_patron):,.2f}"],
        ["Impuesto nómina estatal", f"${float(registro.impuesto_nomina_estatal):,.2f}"],
    ]
    story.append(_tabla(patron_data, col_widths=[10 * cm, 5 * cm]))

    # Footer
    story.append(Spacer(1, 10 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 4 * mm))

    footer_style = ParagraphStyle(
        "Footer", parent=styles["Normal"], fontSize=7, textColor=colors.grey,
    )
    story.append(Paragraph(
        f"<i>Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')} — {settings.RAZON_SOCIAL}</i>",
        footer_style,
    ))

    # Líneas de firma
    story.append(Spacer(1, 20 * mm))
    firma_data = [
        ["_________________________", "_________________________"],
        ["Firma del trabajador", "Firma del patrón"],
    ]
    firma_table = Table(firma_data, colWidths=[8 * cm, 8 * cm])
    firma_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(firma_table)

    doc.build(story)
    buf.seek(0)
    return buf
