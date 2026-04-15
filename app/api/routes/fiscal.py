"""Rutas de reportes fiscales SAT: DIOT, IVA, ISR, contabilidad electronica."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.usuario import Usuario, RolUsuario
from app.services import fiscal_service as svc

router = APIRouter()


# ─── DIOT ────────────────────────────────────────────────────────

@router.get("/diot")
def diot(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2000),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
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
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
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
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
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
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    """Catalogo de cuentas en formato SAT para contabilidad electronica."""
    return svc.contabilidad_electronica_catalogo(db)


# ─── Contabilidad electronica: balanza ───────────────────────────

@router.get("/contabilidad-electronica/balanza")
def balanza_contabilidad_electronica(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2000),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
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
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    """Reporte fiscal integral: DIOT + IVA + ISR + contabilidad electronica."""
    try:
        return svc.generar_reporte_fiscal_completo(db, mes, anio)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
