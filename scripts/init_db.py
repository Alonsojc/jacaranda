"""
Script de inicialización de la base de datos.
Crea todas las tablas y datos semilla iniciales.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine, Base, SessionLocal
from app.core.security import get_password_hash
from app.models.usuario import Usuario, RolUsuario
from app.models.inventario import (
    CategoriaProducto, CategoriaProductoEnum, Ingrediente, Producto,
    UnidadMedida, TasaIVA,
)

# Importar todos los modelos
import app.models  # noqa: F401


def crear_tablas():
    print("Creando tablas...")
    Base.metadata.create_all(bind=engine)
    print("Tablas creadas exitosamente.")


def crear_datos_semilla():
    db = SessionLocal()
    try:
        # Verificar si ya hay datos
        if db.query(Usuario).first():
            print("La base de datos ya tiene datos. Saltando semilla.")
            return

        print("Insertando datos semilla...")

        # --- Usuario administrador ---
        admin = Usuario(
            nombre="Administrador",
            email="admin@jacaranda.mx",
            hashed_password=get_password_hash("admin1234"),
            rol=RolUsuario.ADMINISTRADOR,
        )
        db.add(admin)

        cajero = Usuario(
            nombre="Cajero Principal",
            email="cajero@jacaranda.mx",
            hashed_password=get_password_hash("cajero1234"),
            rol=RolUsuario.CAJERO,
        )
        db.add(cajero)

        # --- Categorías ---
        categorias = [
            CategoriaProducto(nombre="Pan Blanco", tipo=CategoriaProductoEnum.PAN_BLANCO,
                              descripcion="Bolillo"),
            CategoriaProducto(nombre="Pan Dulce", tipo=CategoriaProductoEnum.PAN_DULCE,
                              descripcion="Conchas, cuernos, polvorones"),
            CategoriaProducto(nombre="Pastelería", tipo=CategoriaProductoEnum.PASTELERIA,
                              descripcion="Pasteles personalizados, tres leches"),
            CategoriaProducto(nombre="Galletas", tipo=CategoriaProductoEnum.GALLETAS,
                              descripcion="Galletas en bolsa"),
            CategoriaProducto(nombre="Pan Salado", tipo=CategoriaProductoEnum.PAN_SALADO,
                              descripcion="Pan de caja, focaccia"),
            CategoriaProducto(nombre="Repostería", tipo=CategoriaProductoEnum.REPOSTERIA,
                              descripcion="Postres individuales: Nutella, manzana, brownies, velas"),
            CategoriaProducto(nombre="Bebidas", tipo=CategoriaProductoEnum.BEBIDAS,
                              descripcion="Café, chocolate, jugos"),
        ]
        db.add_all(categorias)
        db.flush()

        # --- Ingredientes ---
        ingredientes = [
            Ingrediente(nombre="Harina de trigo", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_minimo=50, costo_unitario=18.50,
                        es_alergeno=True, tipo_alergeno="gluten"),
            Ingrediente(nombre="Azúcar estándar", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_minimo=30, costo_unitario=28.00),
            Ingrediente(nombre="Mantequilla", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_minimo=10, costo_unitario=120.00,
                        es_alergeno=True, tipo_alergeno="lácteos",
                        requiere_refrigeracion=True, temperatura_almacenamiento="2-4°C"),
            Ingrediente(nombre="Huevo", unidad_medida=UnidadMedida.PIEZA,
                        stock_minimo=100, costo_unitario=3.50,
                        es_alergeno=True, tipo_alergeno="huevo",
                        requiere_refrigeracion=True),
            Ingrediente(nombre="Levadura fresca", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_minimo=5, costo_unitario=65.00,
                        requiere_refrigeracion=True, temperatura_almacenamiento="2-4°C"),
            Ingrediente(nombre="Sal", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_minimo=5, costo_unitario=12.00),
            Ingrediente(nombre="Leche entera", unidad_medida=UnidadMedida.LITRO,
                        stock_minimo=20, costo_unitario=26.00,
                        es_alergeno=True, tipo_alergeno="lácteos",
                        requiere_refrigeracion=True, temperatura_almacenamiento="2-4°C"),
            Ingrediente(nombre="Manteca vegetal", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_minimo=10, costo_unitario=45.00),
            Ingrediente(nombre="Chocolate en barra", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_minimo=5, costo_unitario=95.00),
            Ingrediente(nombre="Vainilla", unidad_medida=UnidadMedida.LITRO,
                        stock_minimo=2, costo_unitario=180.00),
        ]
        db.add_all(ingredientes)
        db.flush()

        # --- Productos ---
        cat_blanco = categorias[0]   # Pan Blanco
        cat_dulce = categorias[1]    # Pan Dulce
        cat_pastel = categorias[2]   # Pastelería
        cat_galletas = categorias[3] # Galletas
        cat_reposteria = categorias[5]  # Repostería

        productos = [
            # ── Pan básico - IVA 0% ──
            Producto(
                codigo="PB-001", nombre="Bolillo",
                categoria_id=cat_blanco.id, precio_unitario=2.50,
                costo_produccion=1.20, unidad_medida=UnidadMedida.PIEZA,
                stock_minimo=100, clave_prod_serv_sat="50181901",
                tasa_iva=TasaIVA.TASA_0, objeto_impuesto="02",
                vida_util_dias=2, alergenos="gluten",
            ),
            # ── Pan dulce básico - IVA 0% ──
            Producto(
                codigo="PD-001", nombre="Concha chocolate",
                categoria_id=cat_dulce.id, precio_unitario=15.00,
                costo_produccion=5.50, unidad_medida=UnidadMedida.PIEZA,
                stock_minimo=50, clave_prod_serv_sat="50181902",
                tasa_iva=TasaIVA.TASA_0, objeto_impuesto="02",
                vida_util_dias=3, alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PD-002", nombre="Concha vainilla",
                categoria_id=cat_dulce.id, precio_unitario=15.00,
                costo_produccion=5.20, unidad_medida=UnidadMedida.PIEZA,
                stock_minimo=50, clave_prod_serv_sat="50181902",
                tasa_iva=TasaIVA.TASA_0, objeto_impuesto="02",
                vida_util_dias=3, alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PD-003", nombre="Cuerno",
                categoria_id=cat_dulce.id, precio_unitario=15.00,
                costo_produccion=6.00, unidad_medida=UnidadMedida.PIEZA,
                stock_minimo=40, clave_prod_serv_sat="50181902",
                tasa_iva=TasaIVA.TASA_0, objeto_impuesto="02",
                vida_util_dias=2, alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PD-004", nombre="Polvorón",
                categoria_id=cat_dulce.id, precio_unitario=12.00,
                costo_produccion=4.00, unidad_medida=UnidadMedida.PIEZA,
                stock_minimo=30, clave_prod_serv_sat="50181902",
                tasa_iva=TasaIVA.TASA_0, objeto_impuesto="02",
                vida_util_dias=5, alergenos="gluten, lácteos",
            ),
            # ── Postres individuales - IVA 16% (alimento preparado) ──
            Producto(
                codigo="RE-001", nombre="Nutella (postre individual)",
                categoria_id=cat_reposteria.id, precio_unitario=85.00,
                costo_produccion=30.00, unidad_medida=UnidadMedida.PIEZA,
                stock_minimo=10, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo, frutos secos",
            ),
            Producto(
                codigo="RE-002", nombre="Manzana (postre individual)",
                categoria_id=cat_reposteria.id, precio_unitario=75.00,
                costo_produccion=25.00, unidad_medida=UnidadMedida.PIEZA,
                stock_minimo=10, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="RE-003", nombre="Brownies",
                categoria_id=cat_reposteria.id, precio_unitario=45.00,
                costo_produccion=15.00, unidad_medida=UnidadMedida.PIEZA,
                stock_minimo=15, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=5, alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="RE-004", nombre="Velas (postre)",
                categoria_id=cat_reposteria.id, precio_unitario=35.00,
                costo_produccion=12.00, unidad_medida=UnidadMedida.PIEZA,
                stock_minimo=15, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=5, alergenos="gluten, lácteos, huevo",
            ),
            # ── Galletas - IVA 16% (alimento preparado) ──
            Producto(
                codigo="GA-001", nombre="Galletas (bolsa de 6 piezas)",
                categoria_id=cat_galletas.id, precio_unitario=85.00,
                costo_produccion=28.00, unidad_medida=UnidadMedida.PIEZA,
                stock_minimo=10, clave_prod_serv_sat="50181903",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=10, alergenos="gluten, lácteos, huevo",
            ),
            # ── Pastelería - IVA 16% (alimento preparado) ──
            Producto(
                codigo="PA-001", nombre="Pastel personalizado 1kg",
                categoria_id=cat_pastel.id, precio_unitario=350.00,
                costo_produccion=120.00, unidad_medida=UnidadMedida.PIEZA,
                stock_minimo=3, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=5, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PA-002", nombre="Pastel personalizado 1.5kg",
                categoria_id=cat_pastel.id, precio_unitario=520.00,
                costo_produccion=180.00, unidad_medida=UnidadMedida.PIEZA,
                stock_minimo=2, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=5, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PA-003", nombre="Pastel Tres Leches 1kg",
                categoria_id=cat_pastel.id, precio_unitario=380.00,
                costo_produccion=130.00, unidad_medida=UnidadMedida.PIEZA,
                stock_minimo=3, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo",
            ),
        ]
        db.add_all(productos)

        db.commit()
        print("Datos semilla insertados exitosamente.")
        print(f"  - {len([admin, cajero])} usuarios creados")
        print(f"  - {len(categorias)} categorías")
        print(f"  - {len(ingredientes)} ingredientes")
        print(f"  - {len(productos)} productos")
        print("")
        print("Credenciales del administrador:")
        print("  Email: admin@jacaranda.mx")
        print("  Password: admin1234")

    finally:
        db.close()


if __name__ == "__main__":
    crear_tablas()
    crear_datos_semilla()
