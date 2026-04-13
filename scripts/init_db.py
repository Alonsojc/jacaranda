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
        tiene_usuarios = db.query(Usuario).first()
        if tiene_usuarios:
            # Revisar si los productos tienen stock
            prods = db.query(Producto).all()
            sin_stock = all(float(p.stock_actual) == 0 for p in prods) if prods else True
            if not sin_stock:
                print("La base de datos ya tiene datos con stock. Saltando semilla.")
                return
            # Productos sin stock - re-sembrar categorías, ingredientes y productos
            print("Productos sin stock. Re-sembrando inventario...")
            from app.models.inventario import CategoriaProducto as CP, Ingrediente as Ing
            db.query(Producto).delete()
            db.query(Ing).delete()
            db.query(CP).delete()
            db.commit()
            # Continuar abajo para re-crear categorías, ingredientes y productos
            # pero saltar usuarios

        print("Insertando datos semilla...")

        # --- Usuario administrador (solo si no existen) ---
        if not tiene_usuarios:
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
            CategoriaProducto(nombre="Postres Individuales", tipo=CategoriaProductoEnum.REPOSTERIA,
                              descripcion="Brownie, galletas x4, pies individuales"),
            CategoriaProducto(nombre="Pies y Postres", tipo=CategoriaProductoEnum.PASTELERIA,
                              descripcion="Nutella Pie, Apple Crumble, Lemon Pie, roscas, panqués"),
            CategoriaProducto(nombre="Cajas de Regalo", tipo=CategoriaProductoEnum.GALLETAS,
                              descripcion="Brownies x16, Blondies, Polvorones, Linzer, Avena"),
            CategoriaProducto(nombre="Pasteles por Pedido", tipo=CategoriaProductoEnum.PAN_DULCE,
                              descripcion="Birthday, Cookies&Cream, Carrot, Banana Nutella"),
        ]
        db.add_all(categorias)
        db.flush()

        # --- Ingredientes ---
        ingredientes = [
            Ingrediente(nombre="Harina de trigo", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=25, stock_minimo=10, costo_unitario=18.50,
                        es_alergeno=True, tipo_alergeno="gluten"),
            Ingrediente(nombre="Azúcar estándar", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=15, stock_minimo=8, costo_unitario=28.00),
            Ingrediente(nombre="Mantequilla", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=8, stock_minimo=5, costo_unitario=120.00,
                        es_alergeno=True, tipo_alergeno="lácteos",
                        requiere_refrigeracion=True, temperatura_almacenamiento="2-4°C"),
            Ingrediente(nombre="Huevo", unidad_medida=UnidadMedida.PIEZA,
                        stock_actual=180, stock_minimo=60, costo_unitario=3.50,
                        es_alergeno=True, tipo_alergeno="huevo",
                        requiere_refrigeracion=True),
            Ingrediente(nombre="Nutella", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=4, stock_minimo=3, costo_unitario=180.00,
                        es_alergeno=True, tipo_alergeno="frutos secos"),
            Ingrediente(nombre="Chocolate semi amargo", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=5, stock_minimo=3, costo_unitario=95.00),
            Ingrediente(nombre="Leche entera", unidad_medida=UnidadMedida.LITRO,
                        stock_actual=12, stock_minimo=8, costo_unitario=26.00,
                        es_alergeno=True, tipo_alergeno="lácteos",
                        requiere_refrigeracion=True, temperatura_almacenamiento="2-4°C"),
            Ingrediente(nombre="Crema para batir", unidad_medida=UnidadMedida.LITRO,
                        stock_actual=6, stock_minimo=4, costo_unitario=65.00,
                        requiere_refrigeracion=True, temperatura_almacenamiento="2-4°C"),
            Ingrediente(nombre="Galletas Oreo", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=3, stock_minimo=2, costo_unitario=85.00),
            Ingrediente(nombre="Galletas Ritz", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=2, stock_minimo=2, costo_unitario=75.00),
            Ingrediente(nombre="Manzana", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=6, stock_minimo=4, costo_unitario=45.00),
            Ingrediente(nombre="Limón", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=4, stock_minimo=3, costo_unitario=35.00),
            Ingrediente(nombre="Dulce de leche", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=3, stock_minimo=2, costo_unitario=120.00),
            Ingrediente(nombre="Nuez", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=2, stock_minimo=1, costo_unitario=350.00,
                        es_alergeno=True, tipo_alergeno="frutos secos"),
            Ingrediente(nombre="Plátano", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=5, stock_minimo=3, costo_unitario=25.00),
            Ingrediente(nombre="Zanahoria", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=4, stock_minimo=3, costo_unitario=20.00),
            Ingrediente(nombre="Speculoos", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=2, stock_minimo=1, costo_unitario=150.00),
            Ingrediente(nombre="Avena", unidad_medida=UnidadMedida.KILOGRAMO,
                        stock_actual=5, stock_minimo=3, costo_unitario=30.00),
        ]
        db.add_all(ingredientes)
        db.flush()

        # --- Productos ---
        cat_ind = categorias[0]      # Postres Individuales
        cat_pies = categorias[1]     # Pies y Postres
        cat_cajas = categorias[2]    # Cajas de Regalo
        cat_pasteles = categorias[3] # Pasteles por Pedido

        productos = [
            # ── Individuales ──
            Producto(
                codigo="IN-001", nombre="Nutella Cookie Pie ind.",
                categoria_id=cat_ind.id, precio_unitario=100.00,
                costo_produccion=35.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=12, stock_minimo=8, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo, frutos secos",
            ),
            Producto(
                codigo="IN-002", nombre="Apple Crumble ind.",
                categoria_id=cat_ind.id, precio_unitario=100.00,
                costo_produccion=30.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=10, stock_minimo=8, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="IN-003", nombre="Lemon Pie ind.",
                categoria_id=cat_ind.id, precio_unitario=100.00,
                costo_produccion=30.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=10, stock_minimo=8, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="IN-004", nombre="Rosca Enjambre ind.",
                categoria_id=cat_ind.id, precio_unitario=100.00,
                costo_produccion=35.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=8, stock_minimo=6, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="IN-005", nombre="Brownie",
                categoria_id=cat_ind.id, precio_unitario=70.00,
                costo_produccion=20.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=15, stock_minimo=10, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=5, alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="IN-006", nombre="Galletas x4",
                categoria_id=cat_ind.id, precio_unitario=55.00,
                costo_produccion=18.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=12, stock_minimo=10, clave_prod_serv_sat="50181903",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=10, alergenos="gluten, lácteos, huevo",
            ),
            # ── Pies y Postres (chico / grande) ──
            Producto(
                codigo="PI-001", nombre="Nutella Cookie Pie chico",
                categoria_id=cat_pies.id, precio_unitario=275.00,
                costo_produccion=90.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=4, stock_minimo=3, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo, frutos secos",
            ),
            Producto(
                codigo="PI-002", nombre="Nutella Cookie Pie grande",
                categoria_id=cat_pies.id, precio_unitario=400.00,
                costo_produccion=130.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=3, stock_minimo=2, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo, frutos secos",
            ),
            Producto(
                codigo="PI-003", nombre="Apple Crumble chico",
                categoria_id=cat_pies.id, precio_unitario=275.00,
                costo_produccion=85.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=4, stock_minimo=3, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PI-004", nombre="Apple Crumble grande",
                categoria_id=cat_pies.id, precio_unitario=400.00,
                costo_produccion=120.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=2, stock_minimo=2, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PI-005", nombre="Lemon Pie chico",
                categoria_id=cat_pies.id, precio_unitario=275.00,
                costo_produccion=85.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=4, stock_minimo=3, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PI-006", nombre="Lemon Pie grande",
                categoria_id=cat_pies.id, precio_unitario=400.00,
                costo_produccion=120.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=2, stock_minimo=2, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PI-007", nombre="Pastel de Dátil",
                categoria_id=cat_pies.id, precio_unitario=480.00,
                costo_produccion=150.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=3, stock_minimo=2, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=5, alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PI-008", nombre="Rosca de Enjambre grande",
                categoria_id=cat_pies.id, precio_unitario=500.00,
                costo_produccion=160.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=3, stock_minimo=2, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PI-009", nombre="Rosca de Cazares",
                categoria_id=cat_pies.id, precio_unitario=400.00,
                costo_produccion=130.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=2, stock_minimo=2, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, alergenos="gluten, cacahuate",
            ),
            Producto(
                codigo="PI-010", nombre="Rosca de Chocolate",
                categoria_id=cat_pies.id, precio_unitario=450.00,
                costo_produccion=140.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=3, stock_minimo=2, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PI-011", nombre="Panqué de Zanahoria",
                categoria_id=cat_pies.id, precio_unitario=370.00,
                costo_produccion=120.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=3, stock_minimo=2, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=5, alergenos="gluten, lácteos, huevo, nuez",
            ),
            Producto(
                codigo="PI-012", nombre="Panqué de Plátano",
                categoria_id=cat_pies.id, precio_unitario=350.00,
                costo_produccion=110.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=3, stock_minimo=2, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=5, alergenos="gluten, lácteos, huevo",
            ),
            # ── Cajas de Regalo ──
            Producto(
                codigo="CJ-001", nombre="Caja Brownies x16",
                categoria_id=cat_cajas.id, precio_unitario=370.00,
                costo_produccion=120.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=5, stock_minimo=3, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=5, alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="CJ-002", nombre="Caja Speculoos Blondies x16",
                categoria_id=cat_cajas.id, precio_unitario=370.00,
                costo_produccion=120.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=4, stock_minimo=3, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=5, alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="CJ-003", nombre="Polvorones de Nuez x25",
                categoria_id=cat_cajas.id, precio_unitario=260.00,
                costo_produccion=80.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=4, stock_minimo=3, clave_prod_serv_sat="50181903",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=10, alergenos="gluten, lácteos, nuez",
            ),
            Producto(
                codigo="CJ-004", nombre="Linzer x7",
                categoria_id=cat_cajas.id, precio_unitario=250.00,
                costo_produccion=85.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=3, stock_minimo=3, clave_prod_serv_sat="50181903",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=8, alergenos="gluten, lácteos",
            ),
            Producto(
                codigo="CJ-005", nombre="Galletas de Avena x20",
                categoria_id=cat_cajas.id, precio_unitario=300.00,
                costo_produccion=95.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=3, stock_minimo=3, clave_prod_serv_sat="50181903",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=10, alergenos="gluten, lácteos",
            ),
            # ── Pasteles por Pedido (2 días anticipación) ──
            Producto(
                codigo="PA-001", nombre="Birthday Cake chico",
                categoria_id=cat_pasteles.id, precio_unitario=470.00,
                costo_produccion=150.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=0, stock_minimo=0, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PA-002", nombre="Birthday Cake grande",
                categoria_id=cat_pasteles.id, precio_unitario=860.00,
                costo_produccion=280.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=0, stock_minimo=0, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PA-003", nombre="Cookies & Cream Cake chico",
                categoria_id=cat_pasteles.id, precio_unitario=480.00,
                costo_produccion=160.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=0, stock_minimo=0, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PA-004", nombre="Cookies & Cream Cake grande",
                categoria_id=cat_pasteles.id, precio_unitario=880.00,
                costo_produccion=290.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=0, stock_minimo=0, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo",
            ),
            Producto(
                codigo="PA-005", nombre="Carrot Cake chico",
                categoria_id=cat_pasteles.id, precio_unitario=470.00,
                costo_produccion=150.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=0, stock_minimo=0, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo, nuez",
            ),
            Producto(
                codigo="PA-006", nombre="Carrot Cake grande",
                categoria_id=cat_pasteles.id, precio_unitario=860.00,
                costo_produccion=280.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=0, stock_minimo=0, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo, nuez",
            ),
            Producto(
                codigo="PA-007", nombre="Banana Nutella Cake chico",
                categoria_id=cat_pasteles.id, precio_unitario=500.00,
                costo_produccion=170.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=0, stock_minimo=0, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo, frutos secos",
            ),
            Producto(
                codigo="PA-008", nombre="Banana Nutella Cake grande",
                categoria_id=cat_pasteles.id, precio_unitario=880.00,
                costo_produccion=290.00, unidad_medida=UnidadMedida.PIEZA,
                stock_actual=0, stock_minimo=0, clave_prod_serv_sat="50181904",
                tasa_iva=TasaIVA.TASA_16, objeto_impuesto="02",
                vida_util_dias=4, requiere_refrigeracion=True,
                alergenos="gluten, lácteos, huevo, frutos secos",
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
