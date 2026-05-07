"""Rutas de egresos operativos."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin_or_override, require_permission
from app.models.egreso import Egreso
from app.models.usuario import Usuario
from app.services.auditoria_service import registrar_evento

router = APIRouter()


class EgresoBase(BaseModel):
    concepto: str = Field(..., min_length=2, max_length=200)
    monto: Decimal = Field(..., gt=0)
    categoria: str = Field(default="operativo", max_length=60)
    metodo_pago: str = Field(default="efectivo", max_length=30)
    fecha: date | None = None
    proveedor: str | None = Field(default=None, max_length=150)
    notas: str | None = None


class EgresoCreate(EgresoBase):
    pass


class EgresoUpdate(BaseModel):
    concepto: str | None = Field(default=None, min_length=2, max_length=200)
    monto: Decimal | None = Field(default=None, gt=0)
    categoria: str | None = Field(default=None, max_length=60)
    metodo_pago: str | None = Field(default=None, max_length=30)
    fecha: date | None = None
    proveedor: str | None = Field(default=None, max_length=150)
    notas: str | None = None


class EgresoResponse(EgresoBase):
    id: int
    fecha: date
    activo: bool
    creado_por_id: int | None = None

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[EgresoResponse])
def listar_egresos(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    activo: bool = Query(default=True),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("egresos", "ver")),
):
    query = db.query(Egreso).filter(Egreso.activo.is_(activo))
    if fecha_inicio:
        query = query.filter(Egreso.fecha >= fecha_inicio)
    if fecha_fin:
        query = query.filter(Egreso.fecha <= fecha_fin)
    return query.order_by(Egreso.fecha.desc(), Egreso.id.desc()).offset(skip).limit(limit).all()


@router.post("/", response_model=EgresoResponse, status_code=201)
def crear_egreso(
    data: EgresoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("egresos", "editar")),
):
    egreso = Egreso(
        concepto=data.concepto.strip(),
        monto=data.monto,
        categoria=(data.categoria or "operativo").strip().lower(),
        metodo_pago=(data.metodo_pago or "efectivo").strip().lower(),
        fecha=data.fecha or date.today(),
        proveedor=(data.proveedor or "").strip() or None,
        notas=(data.notas or "").strip() or None,
        creado_por_id=user.id,
    )
    db.add(egreso)
    db.flush()
    registrar_evento(
        db,
        usuario_id=user.id,
        usuario_nombre=user.nombre,
        accion="crear",
        modulo="egresos",
        entidad="egreso",
        entidad_id=egreso.id,
        datos_nuevos={
            "concepto": egreso.concepto,
            "monto": float(egreso.monto),
            "categoria": egreso.categoria,
            "metodo_pago": egreso.metodo_pago,
            "fecha": egreso.fecha.isoformat(),
        },
        commit=False,
    )
    db.commit()
    db.refresh(egreso)
    return egreso


@router.put("/{id}", response_model=EgresoResponse)
def actualizar_egreso(
    id: int,
    data: EgresoUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("egresos", "editar egreso")),
):
    egreso = db.query(Egreso).filter(Egreso.id == id).first()
    if not egreso:
        raise HTTPException(status_code=404, detail="Egreso no encontrado")
    anterior = {
        "concepto": egreso.concepto,
        "monto": float(egreso.monto),
        "categoria": egreso.categoria,
        "metodo_pago": egreso.metodo_pago,
        "fecha": egreso.fecha.isoformat(),
        "proveedor": egreso.proveedor,
        "notas": egreso.notas,
    }
    valores = data.model_dump(exclude_unset=True)
    for campo, valor in valores.items():
        if isinstance(valor, str):
            valor = valor.strip()
        if campo in {"categoria", "metodo_pago"} and isinstance(valor, str):
            valor = valor.lower()
        if campo in {"proveedor", "notas"} and valor == "":
            valor = None
        setattr(egreso, campo, valor)
    registrar_evento(
        db,
        usuario_id=user.id,
        usuario_nombre=user.nombre,
        accion="actualizar",
        modulo="egresos",
        entidad="egreso",
        entidad_id=id,
        datos_anteriores=anterior,
        datos_nuevos=valores,
        commit=False,
    )
    db.commit()
    db.refresh(egreso)
    return egreso


@router.delete("/{id}")
def desactivar_egreso(
    id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("egresos", "borrar egreso")),
):
    egreso = db.query(Egreso).filter(Egreso.id == id).first()
    if not egreso:
        raise HTTPException(status_code=404, detail="Egreso no encontrado")
    egreso.activo = False
    registrar_evento(
        db,
        usuario_id=user.id,
        usuario_nombre=user.nombre,
        accion="desactivar",
        modulo="egresos",
        entidad="egreso",
        entidad_id=id,
        datos_anteriores={"activo": True},
        datos_nuevos={"activo": False},
        commit=False,
    )
    db.commit()
    return {"ok": True}
