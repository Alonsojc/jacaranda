"""Rutas de egresos operativos."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, StrictBool, ValidationError, field_validator, model_validator
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.dependencies import require_admin_or_override, require_permission
from app.core.ocr_upload import leer_archivo_ocr
from app.core.time_utils import operation_today
from app.models.egreso import Egreso
from app.models.resguardo import ResguardoControl
from app.models.venta import CorteCaja
from app.models.gasto_fijo import GastoFijo
from app.models.inventario import Proveedor
from app.models.usuario import Usuario
from app.services.auditoria_service import registrar_evento
from app.services.ocr_service import extraer_datos_ticket, extraer_tabla_gastos
from app.services import egresos_import_service as excel_import
from app.services.resguardo_service import (
    bloquear_resguardo, resumen_resguardo, validar_salida_resguardo,
)

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
    "resguardo",
}
ORIGENES_EGRESO = {"manual", "ocr", "recurrente", "excel"}
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
    monto: Decimal = Field(..., gt=0, le=MAX_MONTO, decimal_places=2)
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
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=80)
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
        if self.idempotency_key and not self.fecha:
            raise ValueError("Una captura con identificador requiere fecha explicita")
        if self.metodo_pago == "resguardo" and not self.idempotency_key:
            raise ValueError("El pago desde resguardo requiere identificador de captura")
        return self


class EgresoUpdate(BaseModel):
    concepto: str | None = Field(default=None, min_length=2, max_length=200)
    monto: Decimal | None = Field(default=None, gt=0, le=MAX_MONTO, decimal_places=2)
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

    @model_validator(mode="after")
    def validar_no_nulos(self):
        for campo in ("concepto", "monto", "categoria", "metodo_pago"):
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"{campo} no puede ser nulo")
        return self


class ResguardoInicio(BaseModel):
    saldo_inicial: Decimal = Field(..., ge=0, le=MAX_MONTO, decimal_places=2)


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


class ConfirmarImportacionEgresos(BaseModel):
    token: str = Field(min_length=64, max_length=4_000_000)
    filas: list[int] = Field(min_length=1, max_length=excel_import.MAX_ROWS)
    incluir_duplicados: list[int] = Field(default_factory=list, max_length=excel_import.MAX_ROWS)
    revision_confirmada: StrictBool = False

    @model_validator(mode="after")
    def validar_seleccion(self):
        if len(set(self.filas)) != len(self.filas) or any(f < 1 for f in self.filas):
            raise ValueError("Seleccion de filas invalida")
        if not set(self.incluir_duplicados).issubset(self.filas):
            raise ValueError("Los duplicados deben estar seleccionados")
        return self


class CorreccionFilaFoto(BaseModel):
    fila: int = Field(ge=1, le=excel_import.MAX_ROWS)
    fecha: str | None = Field(max_length=30)
    proveedor: str | None = Field(max_length=150)
    monto: str | None = Field(max_length=40)
    metodo_pago: str | None = Field(max_length=30)


class RevisarFotoEgresos(BaseModel):
    token: str = Field(min_length=64, max_length=4_000_000)
    correcciones: list[CorreccionFilaFoto] = Field(min_length=1, max_length=150)


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
        total = Decimal(str(data.get("total")))
        return total if total.is_finite() and 0 < total <= MAX_MONTO else Decimal("0")
    except (ValueError, ArithmeticError):
        return Decimal("0")


def _resumen_items_ocr(items: list[dict]) -> str:
    partes = []
    for item in (items or [])[:8]:
        nombre = _limpiar_texto(str(item.get("nombre") or "item")) or "item"
        cantidad = item.get("cantidad") if item.get("cantidad") is not None else "?"
        unidad = item.get("unidad") or "?"
        total = item.get("total") if item.get("total") is not None else "?"
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
    if data.get("moneda") not in (None, "MXN"):
        total = Decimal("0")
    concepto = f"Ticket {proveedor or 'escaneado'}"
    resumen = _resumen_items_ocr(data.get("items") or [])
    notas = f"{proveedor or 'Ticket'}: {resumen}" if resumen else proveedor or "Ticket escaneado"
    return {
        "concepto": concepto[:200],
        "monto": _money(total) if total else None,
        "categoria": _categoria_desde_ticket_ocr(data),
        "metodo_pago": data.get("metodo_pago") if data.get("metodo_pago") in METODOS_PAGO - {"resguardo"} else None,
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
    image_bytes, real_mime = await leer_archivo_ocr(archivo)
    ocr = await run_in_threadpool(extraer_datos_ticket, image_bytes, real_mime)
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


@router.get("/resguardo")
def obtener_resguardo(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("egresos", "ver")),
):
    return resumen_resguardo(db)


@router.post("/resguardo/iniciar")
def iniciar_resguardo(
    data: ResguardoInicio,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("egresos", "iniciar resguardo")),
):
    control = bloquear_resguardo(db)
    if control:
        if control.saldo_inicial != data.saldo_inicial:
            raise HTTPException(status_code=409, detail="El resguardo ya esta iniciado; no se puede reemplazar")
        return resumen_resguardo(db)
    control = ResguardoControl(
        id=1, saldo_inicial=data.saldo_inicial, creado_por_id=user.id,
        ultimo_corte_id=db.query(func.coalesce(func.max(CorteCaja.id), 0)).scalar(),
        ultimo_egreso_id=db.query(func.coalesce(func.max(Egreso.id), 0)).scalar(),
    )
    db.add(control)
    db.flush()
    registrar_evento(
        db, usuario_id=user.id, usuario_nombre=user.nombre, accion="crear", modulo="egresos",
        entidad="resguardo_control", entidad_id=1, commit=False,
        datos_nuevos={"saldo_inicial": str(control.saldo_inicial),
                      "ultimo_corte_id": control.ultimo_corte_id,
                      "ultimo_egreso_id": control.ultimo_egreso_id},
    )
    db.commit()
    return resumen_resguardo(db)


def _registrar_egreso(
    data: EgresoCreate,
    db: Session,
    user: Usuario,
    *,
    importacion: dict | None = None,
):
    control = bloquear_resguardo(db)
    fingerprint = hashlib.sha256(json.dumps(
        data.model_dump(mode="json", exclude={"idempotency_key"}),
        sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    ).encode()).hexdigest()
    if data.idempotency_key:
        anterior = db.query(Egreso).filter_by(idempotency_key=data.idempotency_key).first()
        if anterior:
            if anterior.request_fingerprint != fingerprint or anterior.creado_por_id != user.id:
                raise HTTPException(status_code=409, detail="Identificador de captura usado con otros datos")
            return anterior
    fecha = _validar_fecha_operativa(data.fecha)
    if data.metodo_pago == "resguardo":
        try:
            validar_salida_resguardo(db, control, data.monto, fecha)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    proveedor_id, proveedor_nombre = _resolver_proveedor(
        db,
        proveedor_id=data.proveedor_id,
        proveedor_nombre=data.proveedor,
        guardar=data.guardar_proveedor,
        user=user,
    )
    egreso = Egreso(
        idempotency_key=data.idempotency_key,
        request_fingerprint=fingerprint if data.idempotency_key else None,
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
        datos_nuevos={**_snapshot_egreso(egreso), **({
            "importacion_foto" if importacion.get("tipo") == "foto" else "importacion_excel": importacion,
        } if importacion else {})},
        commit=False,
    )
    return egreso


@router.post("/", response_model=EgresoResponse, status_code=201)
def crear_egreso(
    data: EgresoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("egresos", "editar")),
):
    if data.origen == "excel":
        raise HTTPException(status_code=400, detail="Usa la vista previa de Excel para importar gastos")
    egreso = _registrar_egreso(data, db, user)
    db.commit()
    db.refresh(egreso)
    return egreso


def _firma_duplicado(datos: dict) -> tuple:
    return (str(datos["fecha"]), Decimal(str(datos["monto"])),
            excel_import.normalizar(datos.get("proveedor")), datos["metodo_pago"])


def _coincidencias_excel(db: Session, filas: list[dict]) -> dict:
    fechas = {date.fromisoformat(f["datos"]["fecha"]) for f in filas if f.get("datos")}
    existentes = db.query(Egreso).filter(Egreso.activo.is_(True), Egreso.fecha.in_(fechas)).all() if fechas else []
    return {_firma_duplicado({"fecha": e.fecha.isoformat(), "monto": e.monto,
                              "proveedor": e.proveedor, "metodo_pago": e.metodo_pago}): e.id for e in existentes}


def _coincidencias_foto(db: Session, filas: list[dict]) -> dict:
    # A different amount/payment on the same provider/day may be a correction,
    # not another purchase. Photos require explicit review of that conflict.
    fechas = {date.fromisoformat(f["datos"]["fecha"]) for f in filas if f.get("datos")}
    existentes = db.query(Egreso).filter(Egreso.activo.is_(True), Egreso.fecha.in_(fechas)).all() if fechas else []
    resultado = {}
    for e in existentes:
        resultado[("proveedor", e.fecha.isoformat(), excel_import.normalizar(e.proveedor))] = e.id
        resultado[("monto", e.fecha.isoformat(), Decimal(str(e.monto)))] = e.id
    return resultado


def _conflicto_foto(datos: dict, existentes: dict):
    return (existentes.get(("proveedor", str(datos["fecha"]), excel_import.normalizar(datos.get("proveedor"))))
            or existentes.get(("monto", str(datos["fecha"]), Decimal(str(datos["monto"])))))


@router.post("/importacion/foto/previsualizar")
async def previsualizar_foto_egresos(
    archivo: UploadFile = File(...),
    opciones: str = Form(default="{}", max_length=10000),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("egresos", "editar")),
):
    try:
        config = excel_import.OpcionesImportacion.model_validate_json(opciones)
    except ValidationError:
        raise HTTPException(400, "Opciones de importacion invalidas") from None
    if excel_import.normalizar(config.categoria) not in CATEGORIAS_EGRESO:
        raise HTTPException(400, "Categoria predeterminada invalida")
    nombre = (archivo.filename or "foto").replace("\\", "/").rsplit("/", 1)[-1][:200]
    contenido, mime = await leer_archivo_ocr(archivo)
    resultado = await run_in_threadpool(extraer_tabla_gastos, contenido, mime)
    if resultado.get("error"):
        raise HTTPException(422, resultado["error"])
    huella = hashlib.sha256(contenido).hexdigest()
    return await run_in_threadpool(_construir_vista_excel, resultado, huella, nombre, config, db, user)


@router.post("/importacion/foto/revisar")
def revisar_foto_egresos(
    data: RevisarFotoEgresos,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("egresos", "editar")),
):
    from app.services.egresos_photo_service import validar_tabla_gastos

    try:
        vista = excel_import.leer_vista_previa(data.token, user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    if vista.get("tipo") != "foto":
        raise HTTPException(400, "Esta vista previa no corresponde a una foto")
    cambios = {c.fila: c for c in data.correcciones}
    filas = {f["fila"]: f for f in vista["filas"]}
    if len(cambios) != len(data.correcciones) or not set(cambios).issubset(filas):
        raise HTTPException(400, "Fila de correccion no disponible")
    resultado = {"tipo": "foto", "hoja": "Foto", "hojas": ["Foto"], "fila_encabezado": 0,
                 "faltantes": [], "columnas": {}, "opciones_columnas": [], "filas": []}
    for numero, fila in filas.items():
        original = fila.get("original", {})
        salida = {"fila": numero, "datos": {k: v for k, v in fila["datos"].items() if k in excel_import.CAMPOS}, "original": original,
                  "omitida": fila["estado"] == "omitida", "errores": fila.get("errores", []),
                  "corregida": fila.get("corregida", False)}
        if numero in cambios:
            if fila["estado"] in {"omitida", "registrada"}:
                raise HTTPException(409, "No se puede corregir una suma ni una fila ya importada")
            raw = cambios[numero].model_dump(exclude={"fila"})
            leida = validar_tabla_gastos({"moneda": "MXN", "filas": [
                {**raw, "legible": True, "es_total": False, "advertencias": []},
            ]})["filas"][0]
            salida.update(datos=leida["datos"], errores=leida["errores"], corregida=True)
        resultado["filas"].append(salida)
    config = excel_import.OpcionesImportacion(**vista["opciones"])
    return _construir_vista_excel(resultado, vista["huella"], vista["archivo"], config, db, user)


@router.post("/importacion/previsualizar")
async def previsualizar_excel_egresos(
    archivo: UploadFile = File(...),
    opciones: str = Form(default="{}", max_length=10000),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("egresos", "editar")),
):
    try:
        config = excel_import.OpcionesImportacion.model_validate_json(opciones)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Opciones de importacion invalidas") from None
    if excel_import.normalizar(config.categoria) not in CATEGORIAS_EGRESO:
        raise HTTPException(status_code=400, detail="Categoria predeterminada invalida")
    nombre = (archivo.filename or "").replace("\\", "/").rsplit("/", 1)[-1][:200]
    try:
        if not nombre.lower().endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="Selecciona un Excel .xlsx; no una foto ni un archivo .xls")
        contenido = bytearray()
        while len(contenido) <= excel_import.MAX_BYTES:
            parte = await archivo.read(min(1024 * 1024, excel_import.MAX_BYTES + 1 - len(contenido)))
            if not parte:
                break
            contenido.extend(parte)
        if len(contenido) > excel_import.MAX_BYTES:
            raise HTTPException(status_code=413, detail="El Excel supera 5 MB")
        try:
            resultado = await run_in_threadpool(excel_import.leer_excel, bytes(contenido), config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except Exception:
            raise HTTPException(status_code=400, detail="No se pudo leer el libro. Usa un Excel .xlsx valido, sin macros ni contrasena") from None
    finally:
        await archivo.close()
    huella = hashlib.sha256(contenido).hexdigest()
    return await run_in_threadpool(_construir_vista_excel, resultado, huella, nombre, config, db, user)


def _construir_vista_excel(resultado, huella, nombre, config, db, user):
    tipo = "foto" if resultado.get("tipo") == "foto" else "excel"
    validas = []
    for fila in resultado["filas"]:
        fila["estado"] = "omitida" if fila["omitida"] else "error"
        if fila["omitida"] or fila["errores"] or resultado["faltantes"]:
            continue
        try:
            _validar_fecha_operativa(date.fromisoformat(fila["datos"]["fecha"]))
            valores = {"categoria": config.categoria, **fila["datos"]}
            datos = EgresoCreate(**valores,
                                 origen="ocr" if tipo == "foto" else "excel", guardar_proveedor=config.guardar_proveedor,
                                 ocr_payload={"tipo": "tabla_gastos", "documento_id": huella,
                                              "fila": fila["fila"], "corregida": fila.get("corregida", False),
                                              "original": fila["original"]} if tipo == "foto" else None,
                                 idempotency_key=excel_import.clave_fila(huella, resultado["hoja"], fila["fila"], tipo))
            fila["datos"] = datos.model_dump(mode="json")
            fila["estado"] = "lista"
            validas.append(fila)
        except ValidationError as exc:
            fila["errores"] = [" / ".join(str(p) for p in e["loc"]) + ": " + e["msg"] for e in exc.errors()]
        except (ValueError, HTTPException) as exc:
            fila["errores"] = [str(exc.detail) if isinstance(exc, HTTPException) else str(exc)]
    coincidencias = _coincidencias_excel(db, validas)
    conflictos = _coincidencias_foto(db, validas) if tipo == "foto" else {}
    claves = [f["datos"]["idempotency_key"] for f in validas]
    registradas = {e.idempotency_key: e for e in db.query(Egreso).filter(Egreso.idempotency_key.in_(claves)).all()} if claves else {}
    vistas = {}
    vistas_foto = {}
    for fila in validas:
        datos, firma = fila["datos"], _firma_duplicado(fila["datos"])
        anterior = registradas.get(datos["idempotency_key"])
        if anterior:
            fila.update(estado="registrada", egreso_id=anterior.id)
            fila["errores"] = ["Fila ya importada" if anterior.activo else "Fila importada y posteriormente anulada"]
        elif firma in coincidencias or firma in vistas:
            fila["estado"] = "duplicado"
            fila["errores"] = ["Posible duplicado del egreso #" + str(coincidencias[firma]) if firma in coincidencias
                               else "Coincide con la fila " + str(vistas[firma])]
        elif (conflicto := _conflicto_foto(datos, conflictos)):
            fila["estado"] = "duplicado"
            fila["errores"] = ["Coincide proveedor o importe en la misma fecha que el egreso #" + str(conflicto)
                               + "; revisa los datos antes de crear otro"]
        elif tipo == "foto" and firma[:3] in vistas_foto:
            fila["estado"] = "duplicado"
            fila["errores"] = ["Misma fecha, proveedor e importe que la fila " + str(vistas_foto[firma[:3]])]
        vistas.setdefault(firma, fila["fila"])
        vistas_foto.setdefault(firma[:3], fila["fila"])
    token = excel_import.firmar_vista_previa({"archivo": nombre, "huella": huella, "hoja": resultado["hoja"], "tipo": tipo,
        "opciones": {"categoria": config.categoria, "guardar_proveedor": config.guardar_proveedor},
        "filas": [{"fila": f["fila"], "datos": f["datos"], "estado": f["estado"],
                   **({"original": f["original"], "errores": f["errores"] if f["estado"] == "error" else [],
                       "corregida": f.get("corregida", False)} if tipo == "foto" else {})}
                  for f in (resultado["filas"] if tipo == "foto" else validas)]}, user.id) if validas or tipo == "foto" else None
    return {**resultado, "archivo": nombre, "token": token, "limite": excel_import.MAX_ROWS,
            "total_listas": str(sum((Decimal(f["datos"]["monto"]) for f in validas if f["estado"] == "lista"), Decimal("0.00")))}


@router.post("/importacion/confirmar")
def confirmar_excel_egresos(
    data: ConfirmarImportacionEgresos,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("egresos", "editar")),
):
    try:
        vista = excel_import.leer_vista_previa(data.token, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if vista.get("tipo") == "foto" and not data.revision_confirmada:
        raise HTTPException(400, "Confirma la revision de fechas, proveedores, importes y pagos de la foto")
    filas = {f["fila"]: f for f in vista["filas"] if f["estado"] in {"lista", "duplicado"}}
    permitidos = {f for f in filas if filas[f]["estado"] == "duplicado"}
    if not set(data.filas).issubset(filas) or not set(data.incluir_duplicados).issubset(permitidos):
        raise HTTPException(status_code=400, detail="Seleccion no disponible en esta vista previa")
    if any(f in permitidos and f not in data.incluir_duplicados for f in data.filas):
        raise HTTPException(409, "Hay posibles duplicados sin aprobacion explicita; no se guardo ninguna fila nueva")
    seleccion = [filas[f] for f in sorted(data.filas)]
    try:
        bloquear_resguardo(db)
        coincidencias = _coincidencias_excel(db, seleccion)
        conflictos = _coincidencias_foto(db, seleccion) if vista.get("tipo") == "foto" else {}
        importados, repetidos, anulados, ids = 0, 0, 0, []
        total = Decimal("0.00")
        for fila in seleccion:
            captura = EgresoCreate(**fila["datos"])
            anterior = db.query(Egreso).filter_by(idempotency_key=captura.idempotency_key).first()
            if anterior:
                fingerprint = hashlib.sha256(json.dumps(captura.model_dump(mode="json", exclude={"idempotency_key"}),
                    sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
                if anterior.request_fingerprint != fingerprint:
                    raise HTTPException(status_code=409, detail=f"La fila {fila['fila']} ya fue importada con otros datos")
                repetidos += 1
                anulados += int(not anterior.activo)
                ids.append(anterior.id)
                continue
            firma = _firma_duplicado(fila["datos"])
            if firma in coincidencias and fila["fila"] not in data.incluir_duplicados:
                raise HTTPException(status_code=409, detail=f"La fila {fila['fila']} coincide con otro gasto. Actualiza la vista previa; no se guardo ninguna fila nueva")
            if _conflicto_foto(fila["datos"], conflictos) and fila["fila"] not in data.incluir_duplicados:
                raise HTTPException(409, f"La fila {fila['fila']} coincide con el proveedor o importe de otro gasto de la misma fecha. Actualiza la vista previa; no se guardo ninguna fila nueva")
            egreso = _registrar_egreso(captura, db, user, importacion={"archivo": vista["archivo"],
                "sha256": vista["huella"], "hoja": vista["hoja"], "fila": fila["fila"], "tipo": vista.get("tipo", "excel")})
            ids.append(egreso.id)
            importados += 1
            total += egreso.monto
            coincidencias[firma] = egreso.id
        db.commit()
        return {"importados": importados, "ya_registrados": repetidos, "anulados": anulados,
                "monto_importado": str(total), "ids": ids}
    except Exception:
        db.rollback()
        raise


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
    control = bloquear_resguardo(db)
    egreso = db.query(Egreso).filter(Egreso.id == id).populate_existing().with_for_update().first()
    if not egreso:
        raise HTTPException(status_code=404, detail="Egreso no encontrado")
    if not egreso.activo:
        raise HTTPException(status_code=400, detail="No se puede editar un egreso anulado")

    anterior = _snapshot_egreso(egreso)
    valores = data.model_dump(exclude_unset=True, exclude={"motivo", "guardar_proveedor"})
    if "fecha" in valores:
        valores["fecha"] = _validar_fecha_operativa(valores["fecha"])
    if valores.get("metodo_pago", egreso.metodo_pago) == "resguardo":
        try:
            validar_salida_resguardo(
                db, control, valores.get("monto", egreso.monto),
                valores.get("fecha", egreso.fecha), egreso,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    bloquear_resguardo(db)
    egreso = db.query(Egreso).filter(Egreso.id == id).populate_existing().with_for_update().first()
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
