"""Rutas de gestión de clientes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.cliente import Cliente
from app.schemas.cliente import ClienteCreate, ClienteUpdate, ClienteResponse

router = APIRouter()


@router.post("/", response_model=ClienteResponse, status_code=201)
def crear_cliente(data: ClienteCreate, db: Session = Depends(get_db)):
    cliente = Cliente(**data.model_dump())
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    return cliente


@router.get("/", response_model=list[ClienteResponse])
def listar_clientes(db: Session = Depends(get_db)):
    return db.query(Cliente).filter(Cliente.activo.is_(True)).all()


@router.get("/{id}", response_model=ClienteResponse)
def obtener_cliente(id: int, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return cliente


@router.put("/{id}", response_model=ClienteResponse)
def actualizar_cliente(id: int, data: ClienteUpdate, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(cliente, key, value)
    db.commit()
    db.refresh(cliente)
    return cliente


@router.get("/{id}/facturas")
def facturas_cliente(id: int, db: Session = Depends(get_db)):
    from app.models.facturacion import CFDIComprobante
    return db.query(CFDIComprobante).filter(CFDIComprobante.cliente_id == id).all()


@router.get("/{id}/historial")
def historial_cliente(id: int, db: Session = Depends(get_db)):
    from app.services.reportes_service import historial_compras_cliente
    return historial_compras_cliente(db, id)
