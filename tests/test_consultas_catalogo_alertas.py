"""El catálogo y las alertas se leen por conjunto, incluso con relaciones opcionales."""

from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import event

from app.core.time_utils import operation_today
from app.models.inventario import FamiliaProducto, Ingrediente, LoteIngrediente, Producto, UnidadMedida
from app.models.receta import Receta, RecetaIngrediente
from app.schemas.inventario import ProductoResponse
from app.services.alertas_service import alertas_consolidadas
from app.services.inventario_service import listar_productos


@contextmanager
def consultas_select(db):
    consultas = []

    def registrar(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            consultas.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", registrar)
    try:
        yield consultas
    finally:
        event.remove(engine, "before_cursor_execute", registrar)


def test_catalogo_serializa_familias_en_una_consulta(db):
    for codigo, familia in [("A", "Brownies"), ("B", "Galletas"), ("C", None)]:
        db.add(Producto(
            codigo=codigo, nombre=codigo, precio_unitario=10,
            familia=FamiliaProducto(nombre=familia) if familia else None,
        ))
    db.commit()
    db.expunge_all()

    with consultas_select(db) as consultas:
        productos = [ProductoResponse.model_validate(p) for p in listar_productos(db)]

    assert [p.familia_nombre for p in productos] == ["Brownies", "Galletas", None]
    assert len(consultas) == 1


def test_alertas_no_consultan_ingredientes_por_receta_ni_por_lote(db):
    hoy = operation_today()
    harina = Ingrediente(nombre="Harina", unidad_medida=UnidadMedida.KILOGRAMO)
    for codigo in ("completa", "vacia", "inactiva"):
        producto = Producto(codigo=codigo, nombre=codigo, precio_unitario=10)
        receta = Receta(producto=producto, nombre=codigo, rendimiento=1, activo=codigo != "inactiva")
        if codigo == "completa":
            receta.ingredientes.append(RecetaIngrediente(ingrediente=harina, cantidad=1))
        db.add(receta)
    for dia in (-1, 1, 4):
        db.add(LoteIngrediente(
            ingrediente=harina, numero_lote=f"L{dia}", fecha_recepcion=hoy - timedelta(days=2),
            fecha_caducidad=hoy + timedelta(days=dia), cantidad=1, cantidad_disponible=1,
            costo_unitario=10,
        ))
    db.commit()
    db.expunge_all()

    with consultas_select(db) as consultas:
        alertas = alertas_consolidadas(db)

    assert [r["nombre"] for r in alertas["recetas_sin_ingredientes"]] == ["vacia"]
    assert [(a["lote"], a["ingrediente"]) for a in alertas["caducidades"]] == [
        ("L-1", "Harina"), ("L1", "Harina"),
    ]
    assert len(consultas) <= 10
