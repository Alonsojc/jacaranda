"""Rutas de gestión multi-sucursal."""

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission, require_role
from app.models.usuario import Usuario, RolUsuario
from app.services import sucursal_service as svc

router = APIRouter()


# --- Pydantic schemas ---

class SucursalCreate(BaseModel):
    codigo: str
    nombre: str
    direccion: str | None = None
    telefono: str | None = None
    email: str | None = None
    codigo_postal: str | None = None
    lugar_expedicion: str | None = None
    es_matriz: bool = False


class SucursalUpdate(BaseModel):
    nombre: str | None = None
    direccion: str | None = None
    telefono: str | None = None
    email: str | None = None
    codigo_postal: str | None = None
    lugar_expedicion: str | None = None
    activo: bool | None = None


class SucursalResponse(BaseModel):
    id: int
    codigo: str
    nombre: str
    direccion: str | None = None
    telefono: str | None = None
    email: str | None = None
    codigo_postal: str | None = None
    lugar_expedicion: str | None = None
    es_matriz: bool
    activo: bool

    model_config = {"from_attributes": True}


class StockAjusteRequest(BaseModel):
    producto_id: int
    cantidad: Decimal
    operacion: str  # "sumar" or "restar"


class DetalleTraspasoCreate(BaseModel):
    producto_id: int
    cantidad_enviada: Decimal


class TraspasoCreate(BaseModel):
    sucursal_origen_id: int
    sucursal_destino_id: int
    notas: str | None = None
    detalles: list[DetalleTraspasoCreate]


class ItemRecibido(BaseModel):
    producto_id: int
    cantidad_recibida: Decimal


class TraspasoRecibirRequest(BaseModel):
    items_recibidos: list[ItemRecibido]


# --- Specific routes BEFORE /{id} to avoid route collision ---


# --- Traspasos ---

@router.post("/traspasos", status_code=201)
def crear_traspaso(
    data: TraspasoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE)),
):
    try:
        traspaso_data = data.model_dump()
        traspaso_data["usuario_id"] = user.id
        # Convert detalles from Pydantic models to dicts
        traspaso_data["detalles"] = [d.model_dump() for d in data.detalles]
        traspaso = svc.crear_traspaso(db, traspaso_data)
        return _traspaso_to_dict(traspaso)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/traspasos")
def listar_traspasos(
    sucursal_id: int | None = Query(None),
    estado: str | None = Query(None),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("sucursales", "ver")),
):
    traspasos = svc.listar_traspasos(db, sucursal_id=sucursal_id, estado=estado)
    return [_traspaso_to_dict(t) for t in traspasos]


@router.post("/traspasos/{traspaso_id}/enviar")
def enviar_traspaso(
    traspaso_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE)),
):
    try:
        traspaso = svc.enviar_traspaso(db, traspaso_id)
        return _traspaso_to_dict(traspaso)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/traspasos/{traspaso_id}/recibir")
def recibir_traspaso(
    traspaso_id: int,
    data: TraspasoRecibirRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE)),
):
    try:
        items = [item.model_dump() for item in data.items_recibidos]
        traspaso = svc.recibir_traspaso(db, traspaso_id, items)
        return _traspaso_to_dict(traspaso)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/traspasos/{traspaso_id}/cancelar")
def cancelar_traspaso(
    traspaso_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE)),
):
    try:
        traspaso = svc.cancelar_traspaso(db, traspaso_id)
        return _traspaso_to_dict(traspaso)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Reportes (before /{id}) ---

@router.get("/comparativo")
def reporte_comparativo(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("sucursales", "ver")),
):
    return svc.reporte_comparativo(db)


@router.get("/dashboard")
def dashboard_sucursales(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("sucursales", "ver")),
):
    return svc.dashboard_sucursales(db)


@router.get("/financiero")
def reporte_financiero_consolidado(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE)),
):
    """Reporte financiero consolidado de todas las sucursales."""
    return svc.reporte_financiero_consolidado(db)


# --- CRUD Sucursales ---

@router.post("/", response_model=SucursalResponse, status_code=201)
def crear_sucursal(
    data: SucursalCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    try:
        return svc.crear_sucursal(db, data.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=list[SucursalResponse])
def listar_sucursales(
    solo_activas: bool = Query(True),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("sucursales", "ver")),
):
    return svc.listar_sucursales(db, solo_activas=solo_activas)


# --- /{id} routes AFTER specific routes ---

@router.get("/{id}")
def obtener_sucursal(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("sucursales", "ver")),
):
    try:
        return svc.obtener_sucursal(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{id}", response_model=SucursalResponse)
def actualizar_sucursal(
    id: int,
    data: SucursalUpdate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    try:
        return svc.actualizar_sucursal(db, id, data.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{id}/inventario/inicializar", status_code=201)
def inicializar_inventario(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE)),
):
    try:
        nuevos = svc.inicializar_inventario_sucursal(db, id)
        return {"mensaje": f"Se inicializaron {len(nuevos)} productos", "registros_creados": len(nuevos)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{id}/inventario")
def obtener_inventario_sucursal(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("sucursales", "ver")),
):
    try:
        return svc.obtener_inventario_sucursal(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{id}/inventario/ajuste")
def ajustar_stock_sucursal(
    id: int,
    data: StockAjusteRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE)),
):
    try:
        inv = svc.actualizar_stock_sucursal(db, id, data.producto_id, data.cantidad, data.operacion)
        return {
            "sucursal_id": inv.sucursal_id,
            "producto_id": inv.producto_id,
            "stock_actual": float(inv.stock_actual),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Helpers ---

def _traspaso_to_dict(traspaso) -> dict:
    """Serializa un traspaso a dict para respuesta JSON."""
    return {
        "id": traspaso.id,
        "folio": traspaso.folio,
        "sucursal_origen_id": traspaso.sucursal_origen_id,
        "sucursal_destino_id": traspaso.sucursal_destino_id,
        "sucursal_origen_nombre": (
            traspaso.sucursal_origen.nombre if traspaso.sucursal_origen else None
        ),
        "sucursal_destino_nombre": (
            traspaso.sucursal_destino.nombre if traspaso.sucursal_destino else None
        ),
        "estado": traspaso.estado.value,
        "notas": traspaso.notas,
        "usuario_id": traspaso.usuario_id,
        "creado_en": traspaso.creado_en.isoformat() if traspaso.creado_en else None,
        "recibido_en": traspaso.recibido_en.isoformat() if traspaso.recibido_en else None,
        "detalles": [
            {
                "id": d.id,
                "producto_id": d.producto_id,
                "cantidad_enviada": float(d.cantidad_enviada),
                "cantidad_recibida": float(d.cantidad_recibida),
            }
            for d in traspaso.detalles
        ],
    }
