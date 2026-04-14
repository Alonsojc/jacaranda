"""
Servicio de generación de PDFs con ReportLab.
Tickets, reportes de ventas, corte de caja, reportes fiscales.
"""

import io
from datetime import date, datetime
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

from app.core.config import settings


def _header(story, styles, titulo: str, subtitulo: str = ""):
    """Agrega header estándar de Jacaranda."""
    story.append(Paragraph(
        f"<b>{settings.RAZON_SOCIAL}</b>",
        styles["Title"],
    ))
    story.append(Paragraph(
        f"RFC: {settings.RFC} | C.P. {settings.DOMICILIO_FISCAL_CP}",
        styles["Normal"],
    ))
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#c4988a")))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(f"<b>{titulo}</b>", styles["Heading2"]))
    if subtitulo:
        story.append(Paragraph(subtitulo, styles["Normal"]))
    story.append(Spacer(1, 4 * mm))


def _tabla(data, col_widths=None):
    """Crea una tabla estilizada."""
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#c4988a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#faf5f2")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def generar_ticket_pdf(ticket_data: dict) -> io.BytesIO:
    """Genera PDF de ticket de venta."""
    buf = io.BytesIO()
    # Ticket width ~80mm
    page_w = 80 * mm
    page_h = 297 * mm
    doc = SimpleDocTemplate(buf, pagesize=(page_w, page_h),
                            leftMargin=5*mm, rightMargin=5*mm,
                            topMargin=5*mm, bottomMargin=5*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("Center", parent=styles["Normal"], alignment=1, fontSize=8))
    styles.add(ParagraphStyle("Small", parent=styles["Normal"], fontSize=7))
    styles.add(ParagraphStyle("SmallBold", parent=styles["Normal"], fontSize=7, fontName="Helvetica-Bold"))

    story = []
    # Header
    story.append(Paragraph(f"<b>{settings.RAZON_SOCIAL}</b>", ParagraphStyle(
        "TktTitle", parent=styles["Normal"], alignment=1, fontSize=10, fontName="Helvetica-Bold")))
    story.append(Paragraph(f"RFC: {settings.RFC}", styles["Center"]))
    story.append(Paragraph(f"C.P. {settings.DOMICILIO_FISCAL_CP}", styles["Center"]))
    story.append(Spacer(1, 3*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 2*mm))

    # Folio y fecha
    story.append(Paragraph(f"<b>Folio: {ticket_data.get('folio', '')}</b>", styles["SmallBold"]))
    story.append(Paragraph(f"Fecha: {ticket_data.get('fecha', '')}", styles["Small"]))
    story.append(Paragraph(f"Cajero: {ticket_data.get('cajero', '')}", styles["Small"]))
    story.append(Spacer(1, 2*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 2*mm))

    # Productos
    for prod in ticket_data.get("productos", []):
        nombre = prod.get("nombre", "")
        cant = prod.get("cantidad", 1)
        precio = prod.get("precio_unitario", 0)
        subtotal = prod.get("subtotal", 0)
        story.append(Paragraph(
            f"{cant}x {nombre} <br/>"
            f"  @ ${precio:,.2f}  = ${subtotal:,.2f}",
            styles["Small"]))

    story.append(Spacer(1, 2*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 2*mm))

    # Totales
    story.append(Paragraph(f"Subtotal: {ticket_data.get('subtotal', '$0')}", styles["Small"]))
    story.append(Paragraph(f"IVA: {ticket_data.get('iva', '$0')}", styles["Small"]))
    story.append(Paragraph(
        f"<b>TOTAL: {ticket_data.get('total', '$0')}</b>",
        ParagraphStyle("TktTotal", parent=styles["Normal"], fontSize=10, fontName="Helvetica-Bold")))
    story.append(Spacer(1, 1*mm))
    story.append(Paragraph(f"Pago: {ticket_data.get('metodo_pago', '')}", styles["Small"]))
    story.append(Paragraph(f"Recibido: {ticket_data.get('monto_recibido', '$0')}", styles["Small"]))
    story.append(Paragraph(f"Cambio: {ticket_data.get('cambio', '$0')}", styles["Small"]))

    story.append(Spacer(1, 3*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(ticket_data.get("leyenda_fiscal", ""), styles["Center"]))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph("¡Gracias por su compra!", styles["Center"]))

    doc.build(story)
    buf.seek(0)
    return buf


def generar_reporte_ventas_pdf(reporte: dict) -> io.BytesIO:
    """Genera PDF de reporte de ventas por periodo."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    periodo = reporte.get("periodo", {})
    resumen = reporte.get("resumen", {})

    _header(story, styles, "Reporte de Ventas",
            f"Periodo: {periodo.get('inicio', '')} a {periodo.get('fin', '')}")

    # KPIs
    kpi_data = [
        ["Total Ventas", "Tickets", "Ticket Promedio"],
        [f"${resumen.get('total', 0):,.2f}",
         str(resumen.get("numero_ventas", 0)),
         f"${resumen.get('ticket_promedio', 0):,.2f}"],
    ]
    story.append(_tabla(kpi_data, col_widths=[6*cm, 4*cm, 5*cm]))
    story.append(Spacer(1, 6*mm))

    # Desglose fiscal
    story.append(Paragraph("<b>Desglose fiscal</b>", styles["Heading3"]))
    fiscal_data = [
        ["Concepto", "Monto"],
        ["Subtotal", f"${resumen.get('subtotal', 0):,.2f}"],
        ["IVA 0% (base)", f"${resumen.get('iva_tasa_0_base', 0):,.2f}"],
        ["IVA 16%", f"${resumen.get('iva_tasa_16', 0):,.2f}"],
        ["Descuentos", f"${resumen.get('descuentos', 0):,.2f}"],
        ["Total", f"${resumen.get('total', 0):,.2f}"],
    ]
    story.append(_tabla(fiscal_data, col_widths=[10*cm, 5*cm]))
    story.append(Spacer(1, 6*mm))

    # Por método de pago
    por_metodo = reporte.get("por_metodo_pago", {})
    if por_metodo:
        metodo_nombres = {"01": "Efectivo", "04": "Tarjeta crédito", "28": "Tarjeta débito", "03": "Transferencia"}
        story.append(Paragraph("<b>Por método de pago</b>", styles["Heading3"]))
        met_data = [["Método", "Cantidad", "Total"]]
        for k, v in por_metodo.items():
            met_data.append([metodo_nombres.get(k, k), str(v["cantidad"]), f"${v['total']:,.2f}"])
        story.append(_tabla(met_data, col_widths=[6*cm, 4*cm, 5*cm]))
        story.append(Spacer(1, 6*mm))

    # Por día
    por_dia = reporte.get("por_dia", {})
    if por_dia:
        story.append(Paragraph("<b>Ventas por día</b>", styles["Heading3"]))
        dia_data = [["Fecha", "Tickets", "Total"]]
        for k, v in sorted(por_dia.items()):
            dia_data.append([k, str(v["cantidad"]), f"${v['total']:,.2f}"])
        story.append(_tabla(dia_data, col_widths=[6*cm, 4*cm, 5*cm]))

    # Footer
    story.append(Spacer(1, 10*mm))
    story.append(Paragraph(
        f"<i>Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')} — {settings.RAZON_SOCIAL}</i>",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7, textColor=colors.grey),
    ))

    doc.build(story)
    buf.seek(0)
    return buf


def generar_corte_caja_pdf(corte: dict) -> io.BytesIO:
    """Genera PDF de corte de caja."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    _header(story, styles, "Corte de Caja",
            f"Fecha: {corte.get('fecha', '')}")

    data = [
        ["Concepto", "Monto"],
        ["Fondo inicial", f"${corte.get('fondo_inicial', 0):,.2f}"],
        ["Ventas efectivo", f"${corte.get('total_ventas_efectivo', 0):,.2f}"],
        ["Ventas tarjeta", f"${corte.get('total_ventas_tarjeta', 0):,.2f}"],
        ["Ventas transferencia", f"${corte.get('total_ventas_transferencia', 0):,.2f}"],
        ["Total ventas", f"${corte.get('total_ventas', 0):,.2f}"],
        ["Efectivo esperado", f"${corte.get('efectivo_esperado', 0):,.2f}"],
        ["Efectivo real", f"${corte.get('efectivo_real', 0):,.2f}"],
        ["Diferencia", f"${corte.get('diferencia', 0):,.2f}"],
    ]
    story.append(_tabla(data, col_widths=[10*cm, 5*cm]))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph(
        f"Número de ventas: {corte.get('numero_ventas', 0)} | "
        f"Cancelaciones: {corte.get('numero_cancelaciones', 0)}",
        styles["Normal"],
    ))

    if corte.get("notas"):
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph(f"<b>Notas:</b> {corte['notas']}", styles["Normal"]))

    story.append(Spacer(1, 10*mm))
    story.append(Paragraph(
        f"<i>Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')} — {settings.RAZON_SOCIAL}</i>",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7, textColor=colors.grey),
    ))

    doc.build(story)
    buf.seek(0)
    return buf


def generar_reporte_iva_pdf(iva: dict) -> io.BytesIO:
    """Genera PDF de reporte mensual de IVA."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    _header(story, styles, "Reporte de IVA Mensual",
            f"Periodo: {iva.get('periodo', '')}")

    # IVA Trasladado
    story.append(Paragraph("<b>IVA Trasladado (cobrado a clientes)</b>", styles["Heading3"]))
    trasl = iva.get("iva_trasladado", {})
    t16 = trasl.get("tasa_16", {})
    t0 = trasl.get("tasa_0", {})
    data = [
        ["Concepto", "Base gravable", "IVA"],
        ["Tasa 16%", f"${t16.get('base', 0):,.2f}", f"${t16.get('iva', 0):,.2f}"],
        ["Tasa 0%", f"${t0.get('base', 0):,.2f}", f"${t0.get('iva', 0):,.2f}"],
        ["Total trasladado", "", f"${trasl.get('total_trasladado', 0):,.2f}"],
    ]
    story.append(_tabla(data, col_widths=[5*cm, 5*cm, 5*cm]))
    story.append(Spacer(1, 6*mm))

    # IVA Acreditable
    story.append(Paragraph("<b>IVA Acreditable (pagado en compras)</b>", styles["Heading3"]))
    story.append(Paragraph(
        f"Total compras del periodo: ${iva.get('total_compras_periodo', 0):,.2f}",
        styles["Normal"],
    ))
    story.append(Paragraph(
        f"IVA Acreditable (estimado 16%): ${iva.get('iva_acreditable', 0):,.2f}",
        styles["Normal"],
    ))
    story.append(Spacer(1, 6*mm))

    # Resultado
    story.append(Paragraph("<b>Resultado</b>", styles["Heading3"]))
    result_data = [
        ["Concepto", "Monto"],
        ["IVA por pagar", f"${iva.get('iva_por_pagar', 0):,.2f}"],
        ["IVA a favor", f"${iva.get('iva_a_favor', 0):,.2f}"],
    ]
    story.append(_tabla(result_data, col_widths=[10*cm, 5*cm]))

    story.append(Spacer(1, 10*mm))
    story.append(Paragraph(
        f"<i>Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')} — {settings.RAZON_SOCIAL}</i>",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7, textColor=colors.grey),
    ))

    doc.build(story)
    buf.seek(0)
    return buf


def generar_reporte_isr_pdf(isr: dict) -> io.BytesIO:
    """Genera PDF de reporte ISR provisional."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    _header(story, styles, "ISR Provisional",
            f"Periodo: {isr.get('periodo', '')}")

    ded = isr.get("deducciones_acumuladas", {})
    data = [
        ["Concepto", "Monto"],
        ["Ingresos acumulados", f"${isr.get('ingresos_acumulados', 0):,.2f}"],
        ["Deducciones — Compras", f"${ded.get('compras', 0):,.2f}"],
        ["Deducciones — Nómina", f"${ded.get('nomina', 0):,.2f}"],
        ["Total deducciones", f"${ded.get('total', 0):,.2f}"],
        ["Utilidad fiscal", f"${isr.get('utilidad_fiscal', 0):,.2f}"],
        [f"Tasa provisional ({float(isr.get('tasa_provisional', 0))*100:.2f}%)", ""],
        ["ISR Provisional", f"${isr.get('isr_provisional', 0):,.2f}"],
    ]
    story.append(_tabla(data, col_widths=[10*cm, 5*cm]))

    story.append(Spacer(1, 10*mm))
    story.append(Paragraph(
        "<i>Nota: Este es un cálculo estimado. Consulte a su contador para la declaración oficial.</i>",
        ParagraphStyle("Nota", parent=styles["Normal"], fontSize=8, textColor=colors.grey),
    ))

    story.append(Spacer(1, 6*mm))
    story.append(Paragraph(
        f"<i>Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')} — {settings.RAZON_SOCIAL}</i>",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7, textColor=colors.grey),
    ))

    doc.build(story)
    buf.seek(0)
    return buf
