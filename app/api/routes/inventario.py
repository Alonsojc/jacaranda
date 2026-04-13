"""Rutas de gestión de inventario."""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.usuario import Usuario
from app.schemas.inventario import (
    CategoriaCreate, CategoriaResponse,
    ProveedorCreate, ProveedorResponse,
    IngredienteCreate, IngredienteUpdate, IngredienteResponse,
    ProductoCreate, ProductoUpdate, ProductoResponse,
    MovimientoCreate, MovimientoResponse,
    LoteCreate, LoteResponse,
)
from app.services import inventario_service as svc

router = APIRouter()


# --- Categorías ---

@router.post("/categorias", response_model=CategoriaResponse, status_code=201)
def crear_categoria(data: CategoriaCreate, db: Session = Depends(get_db)):
    return svc.crear_categoria(db, data)


@router.get("/categorias", response_model=list[CategoriaResponse])
def listar_categorias(db: Session = Depends(get_db)):
    return svc.listar_categorias(db)


# --- Proveedores ---

@router.post("/proveedores", response_model=ProveedorResponse, status_code=201)
def crear_proveedor(data: ProveedorCreate, db: Session = Depends(get_db)):
    return svc.crear_proveedor(db, data)


@router.get("/proveedores", response_model=list[ProveedorResponse])
def listar_proveedores(db: Session = Depends(get_db)):
    return svc.listar_proveedores(db)


# --- Ingredientes ---

@router.post("/ingredientes", response_model=IngredienteResponse, status_code=201)
def crear_ingrediente(
    data: IngredienteCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    return svc.crear_ingrediente(db, data)


@router.get("/ingredientes", response_model=list[IngredienteResponse])
def listar_ingredientes(db: Session = Depends(get_db)):
    return svc.listar_ingredientes(db)


@router.get("/ingredientes/{id}", response_model=IngredienteResponse)
def obtener_ingrediente(id: int, db: Session = Depends(get_db)):
    try:
        return svc.obtener_ingrediente(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/ingredientes/{id}", response_model=IngredienteResponse)
def actualizar_ingrediente(id: int, data: IngredienteUpdate, db: Session = Depends(get_db)):
    try:
        return svc.actualizar_ingrediente(db, id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Productos ---

@router.post("/productos", response_model=ProductoResponse, status_code=201)
def crear_producto(
    data: ProductoCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    try:
        return svc.crear_producto(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/productos", response_model=list[ProductoResponse])
def listar_productos(db: Session = Depends(get_db)):
    return svc.listar_productos(db)


@router.get("/productos/{id}", response_model=ProductoResponse)
def obtener_producto(id: int, db: Session = Depends(get_db)):
    try:
        return svc.obtener_producto(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/productos/{id}", response_model=ProductoResponse)
def actualizar_producto(id: int, data: ProductoUpdate, db: Session = Depends(get_db)):
    try:
        return svc.actualizar_producto(db, id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/productos/{id}/imagen")
async def subir_imagen_producto(
    id: int,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Sube una foto de producto y la guarda como base64 en la BD."""
    import base64
    from app.models.inventario import Producto

    producto = db.query(Producto).filter(Producto.id == id).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    if not archivo.content_type or not archivo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen")

    image_bytes = await archivo.read()
    if len(image_bytes) > 5_000_000:
        raise HTTPException(status_code=400, detail="Imagen muy grande (máximo 5MB)")

    data_url = f"data:{archivo.content_type};base64,{base64.b64encode(image_bytes).decode()}"
    producto.imagen = data_url
    db.commit()

    return {"mensaje": "Imagen guardada", "producto_id": id}


# --- Movimientos ---

@router.post("/movimientos", response_model=MovimientoResponse, status_code=201)
def registrar_movimiento(
    data: MovimientoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    try:
        return svc.registrar_movimiento(db, data, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/movimientos", response_model=list[MovimientoResponse])
def listar_movimientos(
    ingrediente_id: int | None = None,
    producto_id: int | None = None,
    db: Session = Depends(get_db),
):
    return svc.listar_movimientos(db, ingrediente_id, producto_id)


# --- Lotes ---

@router.post("/lotes", response_model=LoteResponse, status_code=201)
def registrar_lote(data: LoteCreate, db: Session = Depends(get_db)):
    try:
        return svc.registrar_lote(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Alertas ---

@router.get("/alertas/stock-bajo")
def alertas_stock_bajo(db: Session = Depends(get_db)):
    return svc.alertas_stock_bajo(db)


@router.get("/alertas/por-caducar")
def alertas_caducidad(dias: int = Query(default=7), db: Session = Depends(get_db)):
    lotes = svc.ingredientes_por_caducar(db, dias)
    return [
        {
            "lote_id": l.id,
            "ingrediente_id": l.ingrediente_id,
            "numero_lote": l.numero_lote,
            "fecha_caducidad": l.fecha_caducidad.isoformat() if l.fecha_caducidad else None,
            "cantidad_disponible": float(l.cantidad_disponible),
        }
        for l in lotes
    ]


@router.post("/ingredientes/{ingrediente_id}/compra")
def registrar_compra_ingrediente(
    ingrediente_id: int,
    cantidad: float = Query(...),
    costo: float = Query(0),
    proveedor: str = Query(""),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Registrar entrada de ingrediente (compra a proveedor)."""
    from app.models.inventario import Ingrediente, MovimientoInventario, TipoMovimiento, LoteIngrediente
    from datetime import datetime, timezone, timedelta, date
    from decimal import Decimal

    ingrediente = db.query(Ingrediente).filter(Ingrediente.id == ingrediente_id).first()
    if not ingrediente:
        raise HTTPException(status_code=404, detail="Ingrediente no encontrado")

    ingrediente.stock_actual += Decimal(str(cantidad))

    # Registrar movimiento
    mov = MovimientoInventario(
        ingrediente_id=ingrediente_id,
        tipo=TipoMovimiento.ENTRADA_COMPRA,
        cantidad=Decimal(str(cantidad)),
        referencia=f"Compra - {proveedor}" if proveedor else "Compra",
        usuario_id=user.id,
    )
    db.add(mov)

    # Crear lote
    hoy = date.today()
    lote = LoteIngrediente(
        ingrediente_id=ingrediente_id,
        numero_lote=f"L-{datetime.now().strftime('%Y%m%d%H%M')}",
        fecha_recepcion=hoy,
        fecha_caducidad=hoy + timedelta(days=30),
        cantidad=Decimal(str(cantidad)),
        cantidad_disponible=Decimal(str(cantidad)),
        costo_unitario=Decimal(str(costo)) if costo else Decimal("0"),
        proveedor_id=None,
    )
    db.add(lote)
    db.commit()
    db.refresh(ingrediente)

    return {
        "mensaje": f"Compra registrada: {cantidad} de {ingrediente.nombre}",
        "stock_actual": float(ingrediente.stock_actual),
    }


@router.post("/productos/{producto_id}/ajuste-stock")
def ajustar_stock_producto(
    producto_id: int,
    cantidad: int = Query(..., description="Nueva cantidad en stock"),
    motivo: str = Query("Conteo nocturno"),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Ajustar stock de producto terminado (conteo nocturno del pizarrón)."""
    from app.models.inventario import Producto
    from decimal import Decimal

    producto = db.query(Producto).filter(Producto.id == producto_id).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    anterior = producto.stock_actual
    producto.stock_actual = Decimal(str(cantidad))
    db.commit()

    return {
        "producto": producto.nombre,
        "stock_anterior": float(anterior),
        "stock_nuevo": cantidad,
        "diferencia": float(Decimal(str(cantidad)) - anterior),
        "motivo": motivo,
    }


# --- OCR de tickets ---

@router.post("/ocr-ticket")
async def ocr_ticket(
    archivo: UploadFile = File(...),
    _user: Usuario = Depends(get_current_user),
):
    """Extrae datos de una foto de ticket/factura de compra usando IA."""
    from app.services.ocr_service import extraer_datos_ticket

    if not archivo.content_type or not archivo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen (JPG, PNG)")

    image_bytes = await archivo.read()
    if len(image_bytes) > 20_000_000:  # 20MB limit
        raise HTTPException(status_code=400, detail="La imagen es muy grande (máximo 20MB)")

    resultado = extraer_datos_ticket(image_bytes, archivo.content_type)
    return resultado
