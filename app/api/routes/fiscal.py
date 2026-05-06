"""Rutas de reportes fiscales SAT: DIOT, IVA, ISR, contabilidad electronica."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.usuario import Usuario
from app.services import fiscal_service as svc
from app.services import excel_service
from app.services import pdf_service

router = APIRouter()


# ─── DIOT ────────────────────────────────────────────────────────

@router.get("/diot")
def diot(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2000),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "ver")),
):
    """Declaracion Informativa de Operaciones con Terceros."""
    try:
        return svc.generar_diot(db, mes, anio)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Declaracion IVA mensual ─────────────────────────────────────

@router.get("/iva-mensual")
def iva_mensual(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2000),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "ver")),
):
    """Declaracion mensual de IVA: causado, acreditable, a pagar o saldo a favor."""
    try:
        return svc.declaracion_iva_mensual(db, mes, anio)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Declaracion ISR provisional ────────────────────────────────

@router.get("/isr-provisional")
def isr_provisional(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2000),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "ver")),
):
    """Pago provisional de ISR con ingresos acumulados y coeficiente de utilidad."""
    try:
        return svc.declaracion_isr_provisional(db, mes, anio)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Contabilidad electronica: catalogo ─────────────────────────

@router.get("/contabilidad-electronica/catalogo")
def catalogo_contabilidad_electronica(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "ver")),
):
    """Catalogo de cuentas en formato SAT para contabilidad electronica."""
    return svc.contabilidad_electronica_catalogo(db)


# ─── Contabilidad electronica: balanza ───────────────────────────

@router.get("/contabilidad-electronica/balanza")
def balanza_contabilidad_electronica(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2000),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "ver")),
):
    """Balanza de comprobacion mensual en formato SAT."""
    try:
        return svc.contabilidad_electronica_balanza(db, mes, anio)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Reporte fiscal completo ─────────────────────────────────────

@router.get("/reporte-completo")
def reporte_fiscal_completo(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2000),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "ver")),
):
    """Reporte fiscal integral: DIOT + IVA + ISR + contabilidad electronica."""
    try:
        return svc.generar_reporte_fiscal_completo(db, mes, anio)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Exportaciones ──────────────────────────────────────────────

@router.get("/exportar-iva-excel")
def exportar_iva_excel(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2000),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "ver")),
):
    """Descarga declaración mensual de IVA en Excel."""
    try:
        buf = excel_service.exportar_iva_mensual(db, mes, anio)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=iva_mensual_{anio}_{mes:02d}.xlsx"
        },
    )


@router.get("/exportar-iva-pdf")
def exportar_iva_pdf(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2000),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "ver")),
):
    """Descarga declaración mensual de IVA en PDF."""
    try:
        data = svc.declaracion_iva_mensual(db, mes, anio)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    nombres_mes = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
        5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
        9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
    }
    data["periodo"] = f"{nombres_mes.get(mes, str(mes))} {anio}"

    # Map fiscal service fields to PDF service expected fields
    iva_pdf_data = {
        "periodo": data["periodo"],
        "iva_trasladado": {
            "tasa_16": {
                "base": data["ventas_gravadas_16"],
                "iva": data["iva_causado"],
            },
            "tasa_0": {
                "base": data["ventas_tasa_0"],
                "iva": 0,
            },
            "total_trasladado": data["iva_causado"],
        },
        "total_compras_periodo": 0,
        "iva_acreditable": data["iva_acreditable"],
        "iva_por_pagar": data["iva_a_pagar"],
        "iva_a_favor": data["saldo_a_favor"],
    }

    buf = pdf_service.generar_reporte_iva_pdf(iva_pdf_data)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=iva_mensual_{anio}_{mes:02d}.pdf"
        },
    )
