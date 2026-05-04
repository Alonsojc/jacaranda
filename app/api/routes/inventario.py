"""Rutas de gestión de inventario."""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin_or_override, require_permission
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
def crear_categoria(data: CategoriaCreate, db: Session = Depends(get_db), _user: Usuario = Depends(require_permission("inv", "editar"))):
    return svc.crear_categoria(db, data)


@router.get("/categorias", response_model=list[CategoriaResponse])
def listar_categorias(skip: int = Query(default=0, ge=0), limit: int = Query(default=100, le=500), db: Session = Depends(get_db), _user: Usuario = Depends(require_permission("inv", "ver"))):
    return svc.listar_categorias(db, skip=skip, limit=limit)


# --- Proveedores ---

@router.post("/proveedores", response_model=ProveedorResponse, status_code=201)
def crear_proveedor(data: ProveedorCreate, db: Session = Depends(get_db), _user: Usuario = Depends(require_permission("inv", "editar"))):
    return svc.crear_proveedor(db, data)


@router.get("/proveedores", response_model=list[ProveedorResponse])
def listar_proveedores(skip: int = Query(default=0, ge=0), limit: int = Query(default=100, le=500), db: Session = Depends(get_db), _user: Usuario = Depends(require_permission("inv", "ver"))):
    return svc.listar_proveedores(db, skip=skip, limit=limit)


# --- Ingredientes ---

@router.post("/ingredientes", response_model=IngredienteResponse, status_code=201)
def crear_ingrediente(
    data: IngredienteCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("inv", "editar")),
):
    return svc.crear_ingrediente(db, data)


@router.get("/ingredientes", response_model=list[IngredienteResponse])
def listar_ingredientes(skip: int = Query(default=0, ge=0), limit: int = Query(default=100, le=500), db: Session = Depends(get_db), _user: Usuario = Depends(require_permission("inv", "ver"))):
    return svc.listar_ingredientes(db, skip=skip, limit=limit)


@router.get("/ingredientes/{id}", response_model=IngredienteResponse)
def obtener_ingrediente(id: int, db: Session = Depends(get_db), _user: Usuario = Depends(require_permission("inv", "ver"))):
    try:
        return svc.obtener_ingrediente(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/ingredientes/{id}", response_model=IngredienteResponse)
def actualizar_ingrediente(
    id: int,
    data: IngredienteUpdate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_admin_or_override("inv", "editar ingrediente")),
):
    try:
        return svc.actualizar_ingrediente(db, id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/ingredientes/{id}")
def desactivar_ingrediente(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_admin_or_override("inv", "desactivar ingrediente")),
):
    from app.models.inventario import Ingrediente
    from app.models.receta import Receta, RecetaIngrediente

    ingrediente = db.query(Ingrediente).filter(Ingrediente.id == id).first()
    if not ingrediente:
        raise HTTPException(status_code=404, detail="Ingrediente no encontrado")
    receta_activa = (
        db.query(Receta)
        .join(RecetaIngrediente, RecetaIngrediente.receta_id == Receta.id)
        .filter(
            RecetaIngrediente.ingrediente_id == id,
            Receta.activo.is_(True),
        )
        .first()
    )
    if receta_activa:
        raise HTTPException(
            status_code=400,
            detail="No se puede desactivar: está usado en una receta activa",
        )
    if ingrediente.stock_actual and ingrediente.stock_actual > 0:
        raise HTTPException(
            status_code=400,
            detail="No se puede desactivar: todavía tiene stock",
        )
    ingrediente.activo = False
    db.commit()
    return {"ok": True}


# --- Productos ---

@router.post("/productos", response_model=ProductoResponse, status_code=201)
def crear_producto(
    data: ProductoCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("inv", "editar")),
):
    try:
        return svc.crear_producto(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/productos", response_model=list[ProductoResponse])
def listar_productos(
    q: str | None = Query(None, description="Buscar por nombre o código"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, le=500),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("inv", "ver")),
):
    return svc.listar_productos(db, q=q, skip=skip, limit=limit)


@router.get("/productos/{id}", response_model=ProductoResponse)
def obtener_producto(id: int, db: Session = Depends(get_db), _user: Usuario = Depends(require_permission("inv", "ver"))):
    try:
        return svc.obtener_producto(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/productos/{id}", response_model=ProductoResponse)
def actualizar_producto(
    id: int,
    data: ProductoUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("inv", "editar producto")),
):
    try:
        return svc.actualizar_producto(db, id, data, usuario_id=user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/productos/{id}/imagen")
async def subir_imagen_producto(
    id: int,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_admin_or_override("inv", "editar imagen de producto")),
):
    """Sube una foto de producto y la guarda como base64 en la BD."""
    import base64
    from app.models.inventario import Producto

    producto = db.query(Producto).filter(Producto.id == id).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    from app.core.security_validation import detect_mime

    if not archivo.content_type or not archivo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen")

    image_bytes = await archivo.read()
    if len(image_bytes) > 5_000_000:
        raise HTTPException(status_code=400, detail="Imagen muy grande (máximo 5MB)")

    real_mime = detect_mime(image_bytes)
    if not real_mime or not real_mime.startswith("image/"):
        raise HTTPException(status_code=400, detail="Contenido no corresponde a una imagen válida")

    data_url = f"data:{real_mime};base64,{base64.b64encode(image_bytes).decode()}"
    producto.imagen = data_url
    db.commit()

    return {"mensaje": "Imagen guardada", "producto_id": id}


@router.delete("/productos/{id}")
def desactivar_producto(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_admin_or_override("inv", "desactivar producto")),
):
    from app.models.inventario import Producto
    from app.models.receta import Receta

    producto = db.query(Producto).filter(Producto.id == id).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    receta_activa = db.query(Receta).filter(
        Receta.producto_id == id,
        Receta.activo.is_(True),
    ).first()
    if receta_activa:
        raise HTTPException(
            status_code=400,
            detail="No se puede desactivar: primero desactiva su receta",
        )
    producto.activo = False
    db.commit()
    return {"ok": True}


# --- Movimientos ---

@router.post("/movimientos", response_model=MovimientoResponse, status_code=201)
def registrar_movimiento(
    data: MovimientoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("inv", "editar")),
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
    _user: Usuario = Depends(require_permission("inv", "ver")),
):
    return svc.listar_movimientos(db, ingrediente_id, producto_id)


# --- Lotes ---

@router.post("/lotes", response_model=LoteResponse, status_code=201)
def registrar_lote(data: LoteCreate, db: Session = Depends(get_db), _user: Usuario = Depends(require_permission("inv", "editar"))):
    try:
        return svc.registrar_lote(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Alertas ---

@router.get("/alertas/stock-bajo")
def alertas_stock_bajo(db: Session = Depends(get_db), _user: Usuario = Depends(require_permission("inv", "ver"))):
    return svc.alertas_stock_bajo(db)


@router.get("/alertas/por-caducar")
def alertas_caducidad(dias: int = Query(default=7), db: Session = Depends(get_db), _user: Usuario = Depends(require_permission("inv", "ver"))):
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
    cantidad: float = Query(..., gt=0),
    costo: float = Query(0, ge=0),
    proveedor: str = Query(""),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("inv", "editar")),
):
    """Registrar entrada de ingrediente (compra a proveedor)."""
    from app.models.inventario import Ingrediente, TipoMovimiento, LoteIngrediente
    from datetime import datetime, timezone, timedelta, date
    from decimal import Decimal

    ingrediente = db.query(Ingrediente).filter(Ingrediente.id == ingrediente_id).first()
    if not ingrediente:
        raise HTTPException(status_code=404, detail="Ingrediente no encontrado")

    mov = MovimientoCreate(
        ingrediente_id=ingrediente_id,
        tipo=TipoMovimiento.ENTRADA_COMPRA,
        cantidad=Decimal(str(cantidad)),
        costo_unitario=Decimal(str(costo)) if costo else Decimal("0"),
        referencia=f"Compra - {proveedor}" if proveedor else "Compra",
    )
    try:
        svc.registrar_movimiento(db, mov, user.id, commit=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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
    cantidad: int = Query(..., ge=0, description="Nueva cantidad en stock"),
    motivo: str = Query("Conteo nocturno"),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("inv", "ajustar stock")),
):
    """Ajustar stock de producto terminado (conteo nocturno del pizarrón)."""
    from app.models.inventario import Producto, TipoMovimiento
    from decimal import Decimal

    producto = db.query(Producto).filter(
        Producto.id == producto_id
    ).with_for_update().first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    anterior = producto.stock_actual
    nuevo = Decimal(str(cantidad))
    diferencia = nuevo - anterior
    if diferencia:
        tipo = (
            TipoMovimiento.ENTRADA_AJUSTE
            if diferencia > 0
            else TipoMovimiento.SALIDA_AJUSTE
        )
        mov = MovimientoCreate(
            producto_id=producto_id,
            tipo=tipo,
            cantidad=abs(diferencia),
            referencia=motivo,
        )
        try:
            svc.registrar_movimiento(db, mov, user.id, commit=False)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    db.refresh(producto)

    return {
        "producto": producto.nombre,
        "stock_anterior": float(anterior),
        "stock_nuevo": cantidad,
        "diferencia": float(diferencia),
        "motivo": motivo,
    }


# --- Merma ---

@router.post("/productos/{producto_id}/merma")
def registrar_merma(
    producto_id: int,
    cantidad: int = Query(..., gt=0),
    motivo: str = Query("Merma"),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("inv", "editar")),
):
    """Registrar merma de producto (desperdicio, roto, caducado)."""
    from app.models.inventario import Producto, TipoMovimiento
    from decimal import Decimal

    producto = db.query(Producto).filter(Producto.id == producto_id).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    mov = MovimientoCreate(
        producto_id=producto_id,
        tipo=TipoMovimiento.SALIDA_MERMA,
        cantidad=Decimal(str(cantidad)),
        referencia=motivo,
    )
    try:
        svc.registrar_movimiento(db, mov, user.id, commit=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    db.refresh(producto)

    return {
        "mensaje": f"Merma registrada: {cantidad} de {producto.nombre}",
        "stock_actual": float(producto.stock_actual),
        "motivo": motivo,
    }


# --- Historial de precios ---

@router.get("/productos/{producto_id}/historial-precios")
def historial_precios(
    producto_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("inv", "ver")),
):
    """Obtener historial de cambios de precio de un producto."""
    from app.models.inventario import HistorialPrecio

    registros = (
        db.query(HistorialPrecio)
        .filter(HistorialPrecio.producto_id == producto_id)
        .order_by(HistorialPrecio.fecha.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "precio_anterior": float(r.precio_anterior),
            "precio_nuevo": float(r.precio_nuevo),
            "fecha": r.fecha.isoformat() if r.fecha else None,
        }
        for r in registros
    ]


# --- Subida masiva de fotos ---

@router.post("/productos/imagenes-masivo")
async def subir_imagenes_masivo(
    archivos: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("inv", "editar")),
):
    """Sube fotos masivamente. El nombre del archivo debe contener el nombre del producto."""
    import base64
    from app.core.security_validation import detect_mime
    from app.models.inventario import Producto

    productos = db.query(Producto).filter(Producto.activo.is_(True)).all()
    resultados = []

    for archivo in archivos:
        if not archivo.content_type or not archivo.content_type.startswith("image/"):
            continue
        image_bytes = await archivo.read()
        if len(image_bytes) > 5_000_000:
            continue
        real_mime = detect_mime(image_bytes)
        if not real_mime or not real_mime.startswith("image/"):
            continue

        # Match filename to product name
        fname = (archivo.filename or "").rsplit(".", 1)[0].lower().strip()
        match = None
        for p in productos:
            if p.nombre.lower().strip() == fname:
                match = p
                break
        if not match:
            for p in productos:
                if fname in p.nombre.lower() or p.nombre.lower() in fname:
                    match = p
                    break
        if match:
            data_url = f"data:{archivo.content_type};base64,{base64.b64encode(image_bytes).decode()}"
            match.imagen = data_url
            resultados.append({"archivo": archivo.filename, "producto": match.nombre, "ok": True})
        else:
            resultados.append({"archivo": archivo.filename, "producto": None, "ok": False})

    db.commit()
    ok_count = sum(1 for r in resultados if r["ok"])
    return {"mensaje": f"{ok_count} de {len(resultados)} fotos asignadas", "resultados": resultados}


# --- Conteo nocturno ---

@router.post("/conteo-nocturno")
def conteo_nocturno(
    conteos: list[dict],
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("inv", "editar")),
):
    """Registrar conteo nocturno de productos."""
    from app.models.conteo_inventario import ConteoInventario
    from app.models.inventario import Producto, TipoMovimiento
    from datetime import date
    from decimal import Decimal

    hoy = date.today()
    resultados = []
    for c in conteos:
        producto = db.query(Producto).filter(
            Producto.id == c["producto_id"]
        ).with_for_update().first()
        if not producto:
            continue
        contada = int(c.get("cantidad_contada", 0))
        if contada < 0:
            raise HTTPException(status_code=400, detail="El conteo no puede ser negativo")
        esperada = int(float(producto.stock_actual))
        diferencia = contada - esperada

        conteo = ConteoInventario(
            fecha=hoy,
            producto_id=producto.id,
            cantidad_contada=contada,
            cantidad_esperada=esperada,
            cantidad_inicio_dia=0,
            cantidad_producida=0,
            cantidad_vendida=0,
            diferencia=diferencia,
            usuario_id=user.id,
            notas=c.get("notas"),
        )
        db.add(conteo)

        if diferencia:
            tipo = (
                TipoMovimiento.ENTRADA_AJUSTE
                if diferencia > 0
                else TipoMovimiento.SALIDA_AJUSTE
            )
            mov = MovimientoCreate(
                producto_id=producto.id,
                tipo=tipo,
                cantidad=abs(Decimal(str(diferencia))),
                referencia="Conteo nocturno",
                notas=c.get("notas"),
            )
            try:
                svc.registrar_movimiento(db, mov, user.id, commit=False)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        resultados.append({
            "producto": producto.nombre,
            "esperado": esperada,
            "contado": contada,
            "diferencia": diferencia,
        })

    db.commit()
    return {"mensaje": f"Conteo guardado: {len(resultados)} productos", "resultados": resultados}


# --- OCR de tickets ---

@router.post("/ocr-ticket")
async def ocr_ticket(
    archivo: UploadFile = File(...),
    _user: Usuario = Depends(require_permission("inv", "editar")),
):
    """Extrae datos de una foto de ticket/factura de compra usando IA."""
    from app.services.ocr_service import extraer_datos_ticket

    from app.core.security_validation import detect_mime

    allowed = archivo.content_type and (
        archivo.content_type.startswith("image/") or archivo.content_type == "application/pdf"
    )
    if not allowed:
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen (JPG, PNG) o PDF")

    image_bytes = await archivo.read()
    if len(image_bytes) > 20_000_000:  # 20MB limit
        raise HTTPException(status_code=400, detail="El archivo es muy grande (máximo 20MB)")

    real_mime = detect_mime(image_bytes)
    if not real_mime or (not real_mime.startswith("image/") and real_mime != "application/pdf"):
        raise HTTPException(status_code=400, detail="Contenido no corresponde a imagen o PDF válido")

    resultado = extraer_datos_ticket(image_bytes, real_mime)
    return resultado
