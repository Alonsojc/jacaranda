"""Rutas de gestión de clientes."""

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.cliente import Cliente
from app.models.usuario import Usuario
from app.schemas.cliente import ClienteCreate, ClienteUpdate, ClienteResponse
from app.services.venta_service import VALOR_PUNTO

router = APIRouter()


@router.post("/", response_model=ClienteResponse, status_code=201)
def crear_cliente(
    data: ClienteCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("listas", "editar")),
):
    cliente = Cliente(**data.model_dump())
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    return cliente


@router.get("/", response_model=list[ClienteResponse])
def listar_clientes(
    q: str | None = Query(None, description="Buscar por nombre o teléfono"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("listas", "ver")),
):
    query = db.query(Cliente).filter(Cliente.activo.is_(True))
    if q:
        query = query.filter(
            Cliente.nombre.ilike(f"%{q}%") | Cliente.telefono.ilike(f"%{q}%")
        )
    return query.order_by(Cliente.nombre).offset(skip).limit(limit).all()


@router.get("/{id}", response_model=ClienteResponse)
def obtener_cliente(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("listas", "ver")),
):
    cliente = db.query(Cliente).filter(Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return cliente


@router.put("/{id}", response_model=ClienteResponse)
def actualizar_cliente(
    id: int,
    data: ClienteUpdate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("listas", "editar")),
):
    cliente = db.query(Cliente).filter(Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    _ALLOWED_FIELDS = {"nombre", "telefono", "email", "rfc", "razon_social",
                        "regimen_fiscal", "domicilio_fiscal_cp", "uso_cfdi", "activo"}
    for key, value in data.model_dump(exclude_unset=True).items():
        if key not in _ALLOWED_FIELDS:
            continue
        setattr(cliente, key, value)
    db.commit()
    db.refresh(cliente)
    return cliente


@router.get("/{id}/facturas")
def facturas_cliente(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("listas", "ver")),
):
    from app.models.facturacion import CFDIComprobante
    return db.query(CFDIComprobante).filter(CFDIComprobante.cliente_id == id).all()


@router.get("/{id}/historial")
def historial_cliente(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("listas", "ver")),
):
    from app.services.reportes_service import historial_compras_cliente
    return historial_compras_cliente(db, id)


@router.get("/{id}/puntos")
def consultar_puntos(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("listas", "ver")),
):
    """Consulta puntos acumulados y su valor en pesos."""
    cliente = db.query(Cliente).filter(Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return {
        "puntos": cliente.puntos_acumulados,
        "valor_punto": float(VALOR_PUNTO),
        "descuento_disponible": float(Decimal(str(cliente.puntos_acumulados)) * VALOR_PUNTO),
    }


@router.post("/{id}/canjear-puntos")
def canjear_puntos(
    id: int,
    puntos: int = Query(..., gt=0),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("listas", "editar")),
):
    """Cotiza un canje; el descuento real se aplica al crear la venta."""
    cliente = db.query(Cliente).filter(Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    if puntos > cliente.puntos_acumulados:
        raise HTTPException(
            status_code=400,
            detail=f"Puntos insuficientes: tiene {cliente.puntos_acumulados}, pidió {puntos}",
        )
    descuento = float(Decimal(str(puntos)) * VALOR_PUNTO)
    return {
        "puntos_canjeados": puntos,
        "descuento": descuento,
        "puntos_restantes": cliente.puntos_acumulados - puntos,
        "requiere_venta": True,
        "mensaje": "El canje se descuenta al registrar la venta con puntos_canjeados",
    }
