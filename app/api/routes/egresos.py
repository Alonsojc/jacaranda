"""Rutas de egresos operativos."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin_or_override, require_permission
from app.core.security_validation import detect_mime
from app.core.time_utils import operation_today
from app.models.egreso import Egreso
from app.models.gasto_fijo import GastoFijo
from app.models.inventario import Proveedor
from app.models.usuario import Usuario
from app.services.auditoria_service import registrar_evento
from app.services.ocr_service import extraer_datos_ticket

router = APIRouter()

CATEGORIAS_EGRESO = {
    "operativo",
    "empaque",
    "servicio",
    "flete",
    "mantenimiento",
    "renta",
    "nomina",
    "impuestos",
    "publicidad",
    "insumos",
    "otro",
}
METODOS_PAGO = {
    "efectivo",
    "transferencia",
    "bbva",
    "clip",
    "tarjeta",
    "credito",
    "debito",
    "mixto",
}
ORIGENES_EGRESO = {"manual", "ocr", "recurrente"}
PERIODICIDADES = {"mensual", "quincenal", "semanal"}
MAX_MONTO = Decimal("10000000")


def _limpiar_texto(value: str | None) -> str | None:
    if value is None:
        return None
    limpio = re.sub(r"\s+", " ", value).strip()
    return limpio or None


def _normalizar_catalogo(value: str | None, default: str, permitidos: set[str], campo: str) -> str:
    limpio = (_limpiar_texto(value) or default).lower().replace(" ", "_")
    if limpio not in permitidos:
        permitidos_txt = ", ".join(sorted(permitidos))
        raise ValueError(f"{campo} inválido. Usa uno de: {permitidos_txt}")
    return limpio


def _validar_fecha_operativa(value: date | None) -> date:
    fecha = value or operation_today()
    if fecha > operation_today() + timedelta(days=30):
        raise HTTPException(status_code=400, detail="La fecha del egreso no puede estar más de 30 días en el futuro")
    return fecha


def _monto_mensual_gasto(gasto: GastoFijo) -> Decimal:
    monto = gasto.monto or Decimal("0")
    if gasto.periodicidad == "quincenal":
        return monto * Decimal("2")
    if gasto.periodicidad == "semanal":
        return monto * Decimal("4.33")
    return monto


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


class EgresoBase(BaseModel):
    concepto: str = Field(..., min_length=2, max_length=200)
    monto: Decimal = Field(..., gt=0, le=MAX_MONTO)
    categoria: str = Field(default="operativo", max_length=60)
    metodo_pago: str = Field(default="efectivo", max_length=30)
    fecha: date | None = None
    proveedor_id: int | None = Field(default=None, gt=0)
    proveedor: str | None = Field(default=None, max_length=150)
    notas: str | None = Field(default=None, max_length=1200)

    @field_validator("concepto", "proveedor", "notas", mode="before")
    @classmethod
    def limpiar_textos(cls, value: str | None) -> str | None:
        return _limpiar_texto(value)

    @field_validator("categoria", mode="before")
    @classmethod
    def validar_categoria(cls, value: str | None) -> str:
        return _normalizar_catalogo(value, "operativo", CATEGORIAS_EGRESO, "Categoría")

    @field_validator("metodo_pago", mode="before")
    @classmethod
    def validar_metodo_pago(cls, value: str | None) -> str:
        return _normalizar_catalogo(value, "efectivo", METODOS_PAGO, "Forma de pago")


class EgresoCreate(EgresoBase):
    guardar_proveedor: bool = True
    origen: str = Field(default="manual", max_length=30)
    ocr_payload: dict[str, Any] | None = None

    @field_validator("origen", mode="before")
    @classmethod
    def validar_origen(cls, value: str | None) -> str:
        return _normalizar_catalogo(value, "manual", ORIGENES_EGRESO, "Origen")

    @model_validator(mode="after")
    def validar_proveedor(self):
        if not self.proveedor_id and not self.proveedor:
            raise ValueError("Proveedor o persona es obligatorio")
        return self


class EgresoUpdate(BaseModel):
    concepto: str | None = Field(default=None, min_length=2, max_length=200)
    monto: Decimal | None = Field(default=None, gt=0, le=MAX_MONTO)
    categoria: str | None = Field(default=None, max_length=60)
    metodo_pago: str | None = Field(default=None, max_length=30)
    fecha: date | None = None
    proveedor_id: int | None = Field(default=None, gt=0)
    proveedor: str | None = Field(default=None, max_length=150)
    notas: str | None = Field(default=None, max_length=1200)
    guardar_proveedor: bool = True
    motivo: str = Field(..., min_length=5, max_length=300)

    @field_validator("concepto", "proveedor", "notas", "motivo", mode="before")
    @classmethod
    def limpiar_textos(cls, value: str | None) -> str | None:
        return _limpiar_texto(value)

    @field_validator("categoria", mode="before")
    @classmethod
    def validar_categoria(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalizar_catalogo(value, "operativo", CATEGORIAS_EGRESO, "Categoría")

    @field_validator("metodo_pago", mode="before")
    @classmethod
    def validar_metodo_pago(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalizar_catalogo(value, "efectivo", METODOS_PAGO, "Forma de pago")


class EgresoAnular(BaseModel):
    motivo: str = Field(..., min_length=5, max_length=300)

    @field_validator("motivo", mode="before")
    @classmethod
    def limpiar_motivo(cls, value: str | None) -> str | None:
        return _limpiar_texto(value)


class EgresoResponse(BaseModel):
    id: int
    concepto: str
    monto: Decimal
    categoria: str
    metodo_pago: str
    fecha: date
    proveedor_id: int | None = None
    proveedor: str | None = None
    notas: str | None = None
    origen: str
    activo: bool
    creado_por_id: int | None = None
    actualizado_por_id: int | None = None
    anulado_por_id: int | None = None
    anulado_motivo: str | None = None
    anulado_en: datetime | None = None

    model_config = {"from_attributes": True}


class ProveedorEgresoCreate(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=200)
    contacto: str | None = Field(default=None, max_length=150)
    telefono: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=150)

    @field_validator("nombre", "contacto", "telefono", "email", mode="before")
    @classmethod
    def limpiar_textos(cls, value: str | None) -> str | None:
        return _limpiar_texto(value)


class ProveedorEgresoResponse(BaseModel):
    id: int | None = None
    nombre: str
    contacto: str | None = None
    telefono: str | None = None
    email: str | None = None
    fuente: str = "catalogo"
    usos_egresos: int = 0


class GastoFijoBase(BaseModel):
    concepto: str = Field(..., min_length=2, max_length=200)
    monto: Decimal = Field(..., gt=0, le=MAX_MONTO)
    categoria: str = Field(default="servicio", max_length=60)
    metodo_pago: str = Field(default="transferencia", max_length=30)
    proveedor_id: int | None = Field(default=None, gt=0)
    proveedor: str | None = Field(default=None, max_length=150)
    periodicidad: str = Field(default="mensual", max_length=20)
    dia_pago: int | None = Field(default=None, ge=1, le=31)
    notas: str | None = Field(default=None, max_length=1200)

    @field_validator("concepto", "proveedor", "notas", mode="before")
    @classmethod
    def limpiar_textos(cls, value: str | None) -> str | None:
        return _limpiar_texto(value)

    @field_validator("categoria", mode="before")
    @classmethod
    def validar_categoria(cls, value: str | None) -> str:
        return _normalizar_catalogo(value, "servicio", CATEGORIAS_EGRESO, "Categoría")

    @field_validator("metodo_pago", mode="before")
    @classmethod
    def validar_metodo_pago(cls, value: str | None) -> str:
        return _normalizar_catalogo(value, "transferencia", METODOS_PAGO, "Forma de pago")

    @field_validator("periodicidad", mode="before")
    @classmethod
    def validar_periodicidad(cls, value: str | None) -> str:
        return _normalizar_catalogo(value, "mensual", PERIODICIDADES, "Periodicidad")


class GastoFijoCreate(GastoFijoBase):
    guardar_proveedor: bool = True

    @model_validator(mode="after")
    def validar_proveedor(self):
        if not self.proveedor_id and not self.proveedor:
            raise ValueError("Proveedor o persona es obligatorio")
        return self


class GastoFijoUpdate(GastoFijoBase):
    guardar_proveedor: bool = True
    motivo: str | None = Field(default=None, min_length=5, max_length=300)

    @field_validator("motivo", mode="before")
    @classmethod
    def limpiar_motivo(cls, value: str | None) -> str | None:
        return _limpiar_texto(value)


class GastoFijoResponse(GastoFijoBase):
    id: int
    activo: bool
    creado_por_id: int | None = None
    actualizado_por_id: int | None = None
    desactivado_por_id: int | None = None
    desactivado_motivo: str | None = None
    desactivado_en: datetime | None = None
    creado_en: datetime
    actualizado_en: datetime | None = None

    model_config = {"from_attributes": True}


def _buscar_proveedor_por_nombre(db: Session, nombre: str) -> Proveedor | None:
    return db.query(Proveedor).filter(func.lower(Proveedor.nombre) == nombre.lower()).first()


def _resolver_proveedor(
    db: Session,
    *,
    proveedor_id: int | None,
    proveedor_nombre: str | None,
    guardar: bool,
    user: Usuario,
) -> tuple[int | None, str | None]:
    nombre_limpio = _limpiar_texto(proveedor_nombre)
    if proveedor_id:
        proveedor = db.query(Proveedor).filter(Proveedor.id == proveedor_id).first()
        if not proveedor or not proveedor.activo:
            raise HTTPException(status_code=400, detail="Proveedor no encontrado o inactivo")
        return proveedor.id, proveedor.nombre

    if not nombre_limpio:
        return None, None

    existente = _buscar_proveedor_por_nombre(db, nombre_limpio)
    if existente:
        if guardar and not existente.activo:
            existente.activo = True
            registrar_evento(
                db,
                usuario_id=user.id,
                usuario_nombre=user.nombre,
                accion="reactivar",
                modulo="egresos",
                entidad="proveedor",
                entidad_id=existente.id,
                datos_nuevos={"nombre": existente.nombre, "activo": True},
                commit=False,
            )
        return existente.id if existente.activo or guardar else None, existente.nombre

    if not guardar:
        return None, nombre_limpio

    proveedor = Proveedor(nombre=nombre_limpio)
    db.add(proveedor)
    db.flush()
    registrar_evento(
        db,
        usuario_id=user.id,
        usuario_nombre=user.nombre,
        accion="crear",
        modulo="egresos",
        entidad="proveedor",
        entidad_id=proveedor.id,
        datos_nuevos={"nombre": proveedor.nombre, "origen": "egreso"},
        commit=False,
    )
    return proveedor.id, proveedor.nombre


def _snapshot_egreso(egreso: Egreso) -> dict:
    return {
        "concepto": egreso.concepto,
        "monto": float(egreso.monto),
        "categoria": egreso.categoria,
        "metodo_pago": egreso.metodo_pago,
        "fecha": egreso.fecha.isoformat() if egreso.fecha else None,
        "proveedor_id": egreso.proveedor_id,
        "proveedor": egreso.proveedor,
        "notas": egreso.notas,
        "origen": egreso.origen,
        "activo": egreso.activo,
    }


def _snapshot_gasto_fijo(gasto: GastoFijo) -> dict:
    return {
        "concepto": gasto.concepto,
        "monto": float(gasto.monto),
        "categoria": gasto.categoria,
        "metodo_pago": gasto.metodo_pago,
        "proveedor_id": gasto.proveedor_id,
        "proveedor": gasto.proveedor,
        "periodicidad": gasto.periodicidad,
        "dia_pago": gasto.dia_pago,
        "notas": gasto.notas,
        "activo": gasto.activo,
    }


def _resumen_recurrentes(db: Session) -> dict:
    gastos = db.query(GastoFijo).filter(GastoFijo.activo.is_(True)).order_by(GastoFijo.concepto).all()
    total_mensual = Decimal("0")
    desglose = []
    for gasto in gastos:
        mensual = _monto_mensual_gasto(gasto)
        total_mensual += mensual
        desglose.append(
            {
                "id": gasto.id,
                "concepto": gasto.concepto,
                "monto": _money(gasto.monto),
                "monto_mensual": _money(mensual),
                "periodicidad": gasto.periodicidad,
                "dia_pago": gasto.dia_pago,
                "categoria": gasto.categoria,
                "metodo_pago": gasto.metodo_pago,
                "proveedor": gasto.proveedor,
            }
        )
    return {
        "total_mensual": _money(total_mensual),
        "total_diario": _money(total_mensual / Decimal("30")) if total_mensual else 0,
        "cantidad": len(gastos),
        "gastos": desglose,
    }


def _total_ticket_ocr(data: dict) -> Decimal:
    try:
        total = Decimal(str(data.get("total") or "0"))
    except Exception:
        total = Decimal("0")
    if total > 0:
        return total
    acumulado = Decimal("0")
    for item in data.get("items") or []:
        try:
            acumulado += Decimal(str(item.get("total") or "0"))
        except Exception:
            continue
    return acumulado


def _resumen_items_ocr(items: list[dict]) -> str:
    partes = []
    for item in (items or [])[:8]:
        nombre = _limpiar_texto(str(item.get("nombre") or "item")) or "item"
        cantidad = item.get("cantidad") or 1
        unidad = item.get("unidad") or "pz"
        total = item.get("total") or 0
        partes.append(f"{cantidad} {unidad} {nombre} (${total})")
    return "; ".join(partes)


def _categoria_desde_ticket_ocr(data: dict) -> str:
    textos = [str(data.get("proveedor") or "")]
    textos.extend(str(item.get("nombre") or "") for item in data.get("items") or [])
    txt = " ".join(textos).lower()
    if re.search(r"caja|bolsa|empaque|charola|domo|etiqueta|kraft|list[oó]n|mo[nñ]o", txt):
        return "empaque"
    if re.search(r"gas|luz|agua|internet|renta|servicio", txt):
        return "servicio"
    if re.search(r"flete|env[ií]o|uber|didi|paqueter[ií]a|mensajer", txt):
        return "flete"
    if re.search(r"reparaci[oó]n|mantenimiento|herramienta", txt):
        return "mantenimiento"
    return "operativo"


def _sugerir_egreso_desde_ocr(data: dict) -> dict:
    proveedor = _limpiar_texto(data.get("proveedor"))
    fecha = None
    if data.get("fecha"):
        try:
            fecha = date.fromisoformat(str(data["fecha"])).isoformat()
        except ValueError:
            fecha = None
    total = _total_ticket_ocr(data)
    concepto = f"Ticket {proveedor or 'escaneado'}"
    resumen = _resumen_items_ocr(data.get("items") or [])
    notas = f"{proveedor or 'Ticket'}: {resumen}" if resumen else proveedor or "Ticket escaneado"
    return {
        "concepto": concepto[:200],
        "monto": _money(total) if total else None,
        "categoria": _categoria_desde_ticket_ocr(data),
        "metodo_pago": "efectivo",
        "fecha": fecha,
        "proveedor": proveedor,
        "notas": notas[:1200],
        "origen": "ocr",
        "guardar_proveedor": True,
    }


@router.get("/resumen")
def resumen_egresos(
    fecha: date | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("egresos", "ver")),
):
    dia = fecha or operation_today()
    mes_inicio = dia.replace(day=1)
    mes_fin = (mes_inicio.replace(year=mes_inicio.year + 1, month=1) if mes_inicio.month == 12 else mes_inicio.replace(month=mes_inicio.month + 1))
    egresos_mes = (
        db.query(Egreso)
        .filter(Egreso.activo.is_(True), Egreso.fecha >= mes_inicio, Egreso.fecha < mes_fin)
        .order_by(Egreso.fecha.desc(), Egreso.id.desc())
        .all()
    )

    total_hoy = Decimal("0")
    total_mes = Decimal("0")
    por_categoria: dict[str, Decimal] = {}
    por_metodo: dict[str, Decimal] = {}
    for egreso in egresos_mes:
        monto = egreso.monto or Decimal("0")
        total_mes += monto
        if egreso.fecha == dia:
            total_hoy += monto
        por_categoria[egreso.categoria] = por_categoria.get(egreso.categoria, Decimal("0")) + monto
        por_metodo[egreso.metodo_pago] = por_metodo.get(egreso.metodo_pago, Decimal("0")) + monto

    return {
        "hoy": {
            "fecha": dia.isoformat(),
            "total": _money(total_hoy),
            "cantidad": sum(1 for egreso in egresos_mes if egreso.fecha == dia),
        },
        "mes_actual": {
            "inicio": mes_inicio.isoformat(),
            "fin_exclusivo": mes_fin.isoformat(),
            "total": _money(total_mes),
            "cantidad": len(egresos_mes),
            "por_categoria": {k: _money(v) for k, v in sorted(por_categoria.items())},
            "por_metodo": {k: _money(v) for k, v in sorted(por_metodo.items())},
        },
        "recurrentes": _resumen_recurrentes(db),
    }


@router.get("/proveedores", response_model=list[ProveedorEgresoResponse])
def listar_proveedores_egresos(
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("egresos", "ver")),
):
    proveedores = db.query(Proveedor).filter(Proveedor.activo.is_(True)).order_by(Proveedor.nombre).limit(limit).all()
    usos = {
        nombre: count
        for nombre, count in (
            db.query(Egreso.proveedor, func.count(Egreso.id))
            .filter(Egreso.proveedor.isnot(None))
            .group_by(Egreso.proveedor)
            .all()
        )
        if nombre
    }
    vistos = set()
    resultado: list[ProveedorEgresoResponse] = []
    for proveedor in proveedores:
        vistos.add(proveedor.nombre.lower())
        resultado.append(
            ProveedorEgresoResponse(
                id=proveedor.id,
                nombre=proveedor.nombre,
                contacto=proveedor.contacto,
                telefono=proveedor.telefono,
                email=proveedor.email,
                fuente="catalogo",
                usos_egresos=int(usos.get(proveedor.nombre, 0)),
            )
        )
    for nombre, count in sorted(usos.items(), key=lambda item: item[0].lower()):
        if nombre.lower() in vistos or len(resultado) >= limit:
            continue
        resultado.append(ProveedorEgresoResponse(nombre=nombre, fuente="egresos", usos_egresos=int(count)))
    return resultado


@router.post("/proveedores", response_model=ProveedorEgresoResponse, status_code=201)
def crear_proveedor_egreso(
    data: ProveedorEgresoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("egresos", "editar")),
):
    existente = _buscar_proveedor_por_nombre(db, data.nombre)
    if existente:
        if not existente.activo:
            existente.activo = True
        proveedor = existente
    else:
        proveedor = Proveedor(
            nombre=data.nombre,
            contacto=data.contacto,
            telefono=data.telefono,
            email=data.email,
        )
        db.add(proveedor)
        db.flush()
    registrar_evento(
        db,
        usuario_id=user.id,
        usuario_nombre=user.nombre,
        accion="crear",
        modulo="egresos",
        entidad="proveedor",
        entidad_id=proveedor.id,
        datos_nuevos={"nombre": proveedor.nombre, "origen": "catalogo_egresos"},
        commit=False,
    )
    db.commit()
    db.refresh(proveedor)
    return ProveedorEgresoResponse(
        id=proveedor.id,
        nombre=proveedor.nombre,
        contacto=proveedor.contacto,
        telefono=proveedor.telefono,
        email=proveedor.email,
        fuente="catalogo",
    )


@router.post("/ocr-ticket")
async def ocr_ticket_egreso(
    archivo: UploadFile = File(...),
    _user: Usuario = Depends(require_permission("egresos", "editar")),
):
    allowed = archivo.content_type and (
        archivo.content_type.startswith("image/") or archivo.content_type == "application/pdf"
    )
    if not allowed:
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen (JPG, PNG) o PDF")

    image_bytes = await archivo.read()
    if len(image_bytes) > 20_000_000:
        raise HTTPException(status_code=400, detail="El archivo es muy grande (máximo 20MB)")

    real_mime = detect_mime(image_bytes)
    if not real_mime or (not real_mime.startswith("image/") and real_mime != "application/pdf"):
        raise HTTPException(status_code=400, detail="Contenido no corresponde a imagen o PDF válido")

    ocr = extraer_datos_ticket(image_bytes, real_mime)
    if ocr.get("error"):
        return {"ocr": ocr, "suggested_egreso": None}
    return {"ocr": ocr, "suggested_egreso": _sugerir_egreso_desde_ocr(ocr)}


@router.get("/gastos-fijos", response_model=list[GastoFijoResponse])
def listar_gastos_fijos_egresos(
    activo: bool = Query(default=True),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("egresos", "ver")),
):
    return (
        db.query(GastoFijo)
        .filter(GastoFijo.activo.is_(activo))
        .order_by(GastoFijo.concepto)
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.post("/gastos-fijos", response_model=GastoFijoResponse, status_code=201)
def crear_gasto_fijo_egresos(
    data: GastoFijoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("egresos", "editar")),
):
    proveedor_id, proveedor_nombre = _resolver_proveedor(
        db,
        proveedor_id=data.proveedor_id,
        proveedor_nombre=data.proveedor,
        guardar=data.guardar_proveedor,
        user=user,
    )
    gasto = GastoFijo(
        concepto=data.concepto,
        monto=data.monto,
        categoria=data.categoria,
        metodo_pago=data.metodo_pago,
        proveedor_id=proveedor_id,
        proveedor=proveedor_nombre,
        periodicidad=data.periodicidad,
        dia_pago=data.dia_pago,
        notas=data.notas,
        creado_por_id=user.id,
    )
    db.add(gasto)
    db.flush()
    registrar_evento(
        db,
        usuario_id=user.id,
        usuario_nombre=user.nombre,
        accion="crear",
        modulo="egresos",
        entidad="gasto_fijo",
        entidad_id=gasto.id,
        datos_nuevos=_snapshot_gasto_fijo(gasto),
        commit=False,
    )
    db.commit()
    db.refresh(gasto)
    return gasto


@router.put("/gastos-fijos/{id}", response_model=GastoFijoResponse)
def actualizar_gasto_fijo_egresos(
    id: int,
    data: GastoFijoUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("egresos", "editar gasto fijo")),
):
    gasto = db.query(GastoFijo).filter(GastoFijo.id == id).first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto fijo no encontrado")
    anterior = _snapshot_gasto_fijo(gasto)
    proveedor_id, proveedor_nombre = _resolver_proveedor(
        db,
        proveedor_id=data.proveedor_id,
        proveedor_nombre=data.proveedor,
        guardar=data.guardar_proveedor,
        user=user,
    )
    gasto.concepto = data.concepto
    gasto.monto = data.monto
    gasto.categoria = data.categoria
    gasto.metodo_pago = data.metodo_pago
    gasto.proveedor_id = proveedor_id
    gasto.proveedor = proveedor_nombre
    gasto.periodicidad = data.periodicidad
    gasto.dia_pago = data.dia_pago
    gasto.notas = data.notas
    gasto.actualizado_por_id = user.id
    registrar_evento(
        db,
        usuario_id=user.id,
        usuario_nombre=user.nombre,
        accion="actualizar",
        modulo="egresos",
        entidad="gasto_fijo",
        entidad_id=id,
        datos_anteriores=anterior,
        datos_nuevos={**_snapshot_gasto_fijo(gasto), "motivo": data.motivo},
        commit=False,
    )
    db.commit()
    db.refresh(gasto)
    return gasto


@router.post("/gastos-fijos/{id}/anular")
def anular_gasto_fijo_egresos(
    id: int,
    data: EgresoAnular,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("egresos", "anular gasto fijo")),
):
    gasto = db.query(GastoFijo).filter(GastoFijo.id == id).first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto fijo no encontrado")
    if not gasto.activo:
        raise HTTPException(status_code=400, detail="El gasto fijo ya está anulado")
    anterior = _snapshot_gasto_fijo(gasto)
    gasto.activo = False
    gasto.desactivado_motivo = data.motivo
    gasto.desactivado_por_id = user.id
    gasto.desactivado_en = datetime.now(timezone.utc)
    registrar_evento(
        db,
        usuario_id=user.id,
        usuario_nombre=user.nombre,
        accion="anular",
        modulo="egresos",
        entidad="gasto_fijo",
        entidad_id=id,
        datos_anteriores=anterior,
        datos_nuevos={"activo": False, "motivo": data.motivo},
        commit=False,
    )
    db.commit()
    return {"ok": True}


@router.get("/", response_model=list[EgresoResponse])
def listar_egresos(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    categoria: str | None = Query(default=None),
    metodo_pago: str | None = Query(default=None),
    proveedor_id: int | None = Query(default=None, gt=0),
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
    if categoria:
        try:
            categoria_normalizada = _normalizar_catalogo(categoria, "operativo", CATEGORIAS_EGRESO, "Categoría")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        query = query.filter(Egreso.categoria == categoria_normalizada)
    if metodo_pago:
        try:
            metodo_normalizado = _normalizar_catalogo(metodo_pago, "efectivo", METODOS_PAGO, "Forma de pago")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        query = query.filter(Egreso.metodo_pago == metodo_normalizado)
    if proveedor_id:
        query = query.filter(Egreso.proveedor_id == proveedor_id)
    return query.order_by(Egreso.fecha.desc(), Egreso.id.desc()).offset(skip).limit(limit).all()


@router.post("/", response_model=EgresoResponse, status_code=201)
def crear_egreso(
    data: EgresoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("egresos", "editar")),
):
    fecha = _validar_fecha_operativa(data.fecha)
    proveedor_id, proveedor_nombre = _resolver_proveedor(
        db,
        proveedor_id=data.proveedor_id,
        proveedor_nombre=data.proveedor,
        guardar=data.guardar_proveedor,
        user=user,
    )
    egreso = Egreso(
        concepto=data.concepto,
        monto=data.monto,
        categoria=data.categoria,
        metodo_pago=data.metodo_pago,
        fecha=fecha,
        proveedor_id=proveedor_id,
        proveedor=proveedor_nombre,
        notas=data.notas,
        origen=data.origen,
        ocr_payload=json.dumps(data.ocr_payload, ensure_ascii=False, default=str) if data.ocr_payload else None,
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
        datos_nuevos=_snapshot_egreso(egreso),
        commit=False,
    )
    db.commit()
    db.refresh(egreso)
    return egreso


@router.get("/{id}", response_model=EgresoResponse)
def obtener_egreso(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("egresos", "ver")),
):
    egreso = db.query(Egreso).filter(Egreso.id == id).first()
    if not egreso:
        raise HTTPException(status_code=404, detail="Egreso no encontrado")
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
    if not egreso.activo:
        raise HTTPException(status_code=400, detail="No se puede editar un egreso anulado")

    anterior = _snapshot_egreso(egreso)
    valores = data.model_dump(exclude_unset=True, exclude={"motivo", "guardar_proveedor"})
    if "fecha" in valores:
        valores["fecha"] = _validar_fecha_operativa(valores["fecha"])
    if "proveedor_id" in valores or "proveedor" in valores:
        proveedor_id, proveedor_nombre = _resolver_proveedor(
            db,
            proveedor_id=valores.get("proveedor_id"),
            proveedor_nombre=valores.get("proveedor"),
            guardar=data.guardar_proveedor,
            user=user,
        )
        valores["proveedor_id"] = proveedor_id
        valores["proveedor"] = proveedor_nombre

    campos_editables = {
        "concepto",
        "monto",
        "categoria",
        "metodo_pago",
        "fecha",
        "proveedor_id",
        "proveedor",
        "notas",
    }
    cambios = {campo: valor for campo, valor in valores.items() if campo in campos_editables}
    if not cambios:
        raise HTTPException(status_code=400, detail="No hay cambios para guardar")
    for campo, valor in cambios.items():
        setattr(egreso, campo, valor)
    egreso.actualizado_por_id = user.id
    registrar_evento(
        db,
        usuario_id=user.id,
        usuario_nombre=user.nombre,
        accion="actualizar",
        modulo="egresos",
        entidad="egreso",
        entidad_id=id,
        datos_anteriores=anterior,
        datos_nuevos={**_snapshot_egreso(egreso), "motivo": data.motivo},
        commit=False,
    )
    db.commit()
    db.refresh(egreso)
    return egreso


@router.post("/{id}/anular")
def anular_egreso(
    id: int,
    data: EgresoAnular,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("egresos", "anular egreso")),
):
    egreso = db.query(Egreso).filter(Egreso.id == id).first()
    if not egreso:
        raise HTTPException(status_code=404, detail="Egreso no encontrado")
    if not egreso.activo:
        raise HTTPException(status_code=400, detail="El egreso ya está anulado")
    anterior = _snapshot_egreso(egreso)
    egreso.activo = False
    egreso.anulado_motivo = data.motivo
    egreso.anulado_por_id = user.id
    egreso.anulado_en = datetime.now(timezone.utc)
    registrar_evento(
        db,
        usuario_id=user.id,
        usuario_nombre=user.nombre,
        accion="anular",
        modulo="egresos",
        entidad="egreso",
        entidad_id=id,
        datos_anteriores=anterior,
        datos_nuevos={"activo": False, "motivo": data.motivo},
        commit=False,
    )
    db.commit()
    return {"ok": True}


@router.delete("/{id}")
def desactivar_egreso(
    id: int,
    motivo: str = Query(..., min_length=5, max_length=300),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("egresos", "anular egreso")),
):
    return anular_egreso(id, EgresoAnular(motivo=motivo), db, user)
