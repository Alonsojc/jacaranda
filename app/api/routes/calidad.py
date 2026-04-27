"""Rutas de control de calidad y trazabilidad."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.usuario import Usuario
from app.schemas.calidad import (
    ChecklistCalidadCreate, ChecklistCalidadResponse,
    TrazabilidadLoteCreate, TrazabilidadLoteResponse,
    AlertaRecallCreate, AlertaRecallResponse,
    ResolverRecallRequest,
)
from app.services import calidad_service as svc

router = APIRouter()


# --- Checklists de calidad ---

@router.post("/checklists", response_model=ChecklistCalidadResponse, status_code=201)
def crear_checklist(
    data: ChecklistCalidadCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("calidad", "editar")),
):
    """Crea un nuevo checklist de inspeccion de calidad."""
    return svc.crear_checklist(db, data)


@router.get("/checklists", response_model=list[ChecklistCalidadResponse])
def listar_checklists(
    producto_id: int | None = Query(default=None),
    estado: str | None = Query(default=None),
    fecha_inicio: str | None = Query(default=None),
    fecha_fin: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("calidad", "ver")),
):
    """Lista checklists de calidad con filtros opcionales."""
    return svc.listar_checklists(db, producto_id, estado, fecha_inicio, fecha_fin)


@router.get("/checklists/{checklist_id}", response_model=ChecklistCalidadResponse)
def obtener_checklist(
    checklist_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("calidad", "ver")),
):
    """Obtiene el detalle de un checklist de calidad."""
    try:
        return svc.obtener_checklist(db, checklist_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Trazabilidad ---

@router.post("/trazabilidad", response_model=TrazabilidadLoteResponse, status_code=201)
def registrar_trazabilidad(
    data: TrazabilidadLoteCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("calidad", "editar")),
):
    """Registra el uso de un lote de ingrediente en produccion."""
    try:
        return svc.registrar_trazabilidad(db, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/trazabilidad/producto/{producto_id}")
def trazabilidad_producto(
    producto_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("calidad", "ver")),
):
    """Trazabilidad hacia adelante: que lotes se usaron para hacer este producto."""
    return svc.trazabilidad_producto(db, producto_id)


@router.get("/trazabilidad/lote/{lote_id}")
def trazabilidad_lote(
    lote_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("calidad", "ver")),
):
    """Trazabilidad inversa: que productos se hicieron con este lote."""
    return svc.trazabilidad_lote(db, lote_id)


# --- Alertas de recall ---

@router.post("/recalls", response_model=AlertaRecallResponse, status_code=201)
def crear_alerta_recall(
    data: AlertaRecallCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("calidad", "editar")),
):
    """Crea una alerta de recall. Auto-detecta productos afectados via trazabilidad."""
    return svc.crear_alerta_recall(db, data, usuario_id=user.id)


@router.get("/recalls", response_model=list[AlertaRecallResponse])
def listar_alertas_recall(
    estado: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("calidad", "ver")),
):
    """Lista alertas de recall con filtro opcional de estado."""
    return svc.listar_alertas_recall(db, estado)


@router.post("/recalls/{recall_id}/resolver", response_model=AlertaRecallResponse)
def resolver_recall(
    recall_id: int,
    data: ResolverRecallRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("calidad", "editar")),
):
    """Marca una alerta de recall como resuelta."""
    try:
        return svc.resolver_recall(db, recall_id, data.acciones_tomadas)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Indicadores y dashboard ---

@router.get("/indicadores")
def indicadores_calidad(
    dias: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("calidad", "ver")),
):
    """KPIs de calidad para los ultimos N dias."""
    return svc.indicadores_calidad(db, dias)


@router.get("/dashboard")
def dashboard_calidad(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("calidad", "ver")),
):
    """Dashboard resumen de calidad."""
    return svc.dashboard_calidad(db)
