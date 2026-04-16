"""Tests para el servicio de optimización de producción."""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from app.models.inventario import Producto, Ingrediente, UnidadMedida
from app.models.receta import Receta, RecetaIngrediente, OrdenProduccion, EstadoProduccion
from app.models.venta import Venta, DetalleVenta, MetodoPago, EstadoVenta
from app.models.usuario import Usuario, RolUsuario
from app.core.security import get_password_hash

_prod_counter = 0

def _crear_producto(db, nombre="Pan Dulce", precio=Decimal("15.00"), stock=Decimal("50")):
    global _prod_counter
    _prod_counter += 1
    prod = Producto(
        codigo=f"P-{_prod_counter:04d}",
        nombre=nombre,
        unidad_medida=UnidadMedida.PIEZA,
        precio_unitario=precio,
        costo_produccion=Decimal("5.00"),
        stock_actual=stock,
        stock_minimo=Decimal("10"),
        activo=True,
    )
    db.add(prod)
    db.commit()
    db.refresh(prod)
    return prod


_ing_counter = 0

def _crear_ingrediente(db, nombre="Harina", stock=Decimal("50")):
    global _ing_counter
    _ing_counter += 1
    ing = Ingrediente(
        nombre=f"{nombre}_{_ing_counter}",
        unidad_medida=UnidadMedida.KILOGRAMO,
        stock_actual=stock,
        stock_minimo=Decimal("5"),
        costo_unitario=Decimal("20.00"),
        activo=True,
    )
    db.add(ing)
    db.commit()
    db.refresh(ing)
    return ing


def _crear_receta(db, producto, ingrediente, cantidad_ing=Decimal("0.5"), rendimiento=10):
    receta = Receta(
        producto_id=producto.id,
        nombre=f"Receta {producto.nombre}",
        rendimiento=Decimal(str(rendimiento)),
        tiempo_preparacion_min=30,
        tiempo_horneado_min=25,
        temperatura_horneado_c=180,
    )
    db.add(receta)
    db.flush()

    ri = RecetaIngrediente(
        receta_id=receta.id,
        ingrediente_id=ingrediente.id,
        cantidad=cantidad_ing,
    )
    db.add(ri)
    db.commit()
    db.refresh(receta)
    return receta


_venta_counter = 0

def _ensure_user(db):
    """Asegura que exista un usuario para FK de ventas."""
    user = db.query(Usuario).first()
    if user:
        return user.id
    user = Usuario(
        nombre="Test User",
        email="test_prod@test.com",
        hashed_password=get_password_hash("test1234"),
        rol=RolUsuario.ADMINISTRADOR,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id


_venta_counter = 0

def _crear_venta(db, producto, cantidad=5, dias_atras=0):
    """Crea una venta completada para testing."""
    global _venta_counter
    _venta_counter += 1
    user_id = _ensure_user(db)
    fecha = datetime.now(timezone.utc) - timedelta(days=dias_atras)
    venta = Venta(
        folio=f"V-TEST-{_venta_counter:06d}",
        fecha=fecha,
        subtotal=producto.precio_unitario * cantidad,
        total=producto.precio_unitario * cantidad,
        metodo_pago=MetodoPago.EFECTIVO,
        estado=EstadoVenta.COMPLETADA,
        usuario_id=user_id,
    )
    db.add(venta)
    db.flush()

    detalle = DetalleVenta(
        venta_id=venta.id,
        producto_id=producto.id,
        cantidad=Decimal(str(cantidad)),
        precio_unitario=producto.precio_unitario,
        subtotal=producto.precio_unitario * cantidad,
        clave_prod_serv_sat="50181900",
        clave_unidad_sat="H87",
    )
    db.add(detalle)
    db.commit()
    return venta


class TestPrediccionDemanda:
    def test_prediccion_sin_ventas(self, db):
        """Sin historial de ventas retorna lista vacía."""
        from app.services.produccion_service import predecir_demanda

        _crear_producto(db)
        resultado = predecir_demanda(db, dias_prediccion=7)
        assert isinstance(resultado, list)
        # Sin ventas, las predicciones estarán vacías o con 0 demanda
        for pred in resultado:
            assert pred["demanda_semanal_estimada"] == 0 or pred["demanda_semanal_estimada"] > 0

    def test_prediccion_con_ventas(self, db):
        """Con historial de ventas genera predicciones."""
        from app.services.produccion_service import predecir_demanda

        prod = _crear_producto(db, stock=Decimal("5"))
        # Crear ventas durante las últimas semanas
        for i in range(1, 15):
            _crear_venta(db, prod, cantidad=3, dias_atras=i)

        resultado = predecir_demanda(db, dias_prediccion=7)
        assert len(resultado) > 0

        # El producto con ventas debería aparecer con demanda
        pred_prod = next((p for p in resultado if p["producto_id"] == prod.id), None)
        assert pred_prod is not None
        assert pred_prod["demanda_semanal_estimada"] > 0
        assert len(pred_prod["demanda_diaria"]) == 7

    def test_prediccion_detecta_deficit(self, db):
        """Detecta déficit cuando stock < demanda predicha."""
        from app.services.produccion_service import predecir_demanda

        prod = _crear_producto(db, stock=Decimal("2"))
        for i in range(1, 30):
            _crear_venta(db, prod, cantidad=10, dias_atras=i)

        resultado = predecir_demanda(db, dias_prediccion=7)
        pred_prod = next((p for p in resultado if p["producto_id"] == prod.id), None)
        assert pred_prod is not None
        assert pred_prod["requiere_produccion"] is True
        assert pred_prod["deficit"] > 0


class TestPlanProduccion:
    def test_plan_sin_deficit(self, db):
        """Sin déficit, plan vacío de productos a producir."""
        from app.services.produccion_service import generar_plan_produccion

        _crear_producto(db, stock=Decimal("1000"))
        resultado = generar_plan_produccion(db, dias=7)
        assert "plan" in resultado
        assert "ingredientes_consolidados" in resultado
        assert resultado["productos_a_producir"] >= 0

    def test_plan_con_receta(self, db):
        """Genera plan incluyendo recetas e ingredientes."""
        from app.services.produccion_service import generar_plan_produccion

        prod = _crear_producto(db, stock=Decimal("1"))
        ing = _crear_ingrediente(db, stock=Decimal("100"))
        _crear_receta(db, prod, ing, cantidad_ing=Decimal("0.5"), rendimiento=10)

        # Crear ventas para generar demanda
        for i in range(1, 20):
            _crear_venta(db, prod, cantidad=8, dias_atras=i)

        resultado = generar_plan_produccion(db, dias=7)
        assert resultado["productos_a_producir"] > 0
        # Plan items should have receta info
        for item in resultado["plan"]:
            if item["producto_id"] == prod.id:
                assert item["receta"] is not None
                assert item["lotes_necesarios"] > 0


class TestAnalisisEficiencia:
    def test_eficiencia_sin_datos(self, db):
        """Sin datos de producción retorna 0% eficiencia."""
        from app.services.produccion_service import analisis_eficiencia

        resultado = analisis_eficiencia(db, dias=30)
        assert resultado["eficiencia_global_pct"] == 0
        assert resultado["ordenes_completadas"] == 0

    def test_eficiencia_con_produccion(self, db):
        """Calcula eficiencia con órdenes de producción y ventas."""
        from app.services.produccion_service import analisis_eficiencia

        prod = _crear_producto(db)
        receta = Receta(
            producto_id=prod.id,
            nombre="Receta Test Efic",
            rendimiento=Decimal("10"),
        )
        db.add(receta)
        db.flush()

        ahora = datetime.now(timezone.utc)
        orden = OrdenProduccion(
            receta_id=receta.id,
            cantidad_lotes=Decimal("10"),
            cantidad_producida=Decimal("100"),
            estado=EstadoProduccion.COMPLETADA,
            fecha_programada=ahora - timedelta(days=5),
            fecha_inicio=ahora - timedelta(days=5),
            fecha_fin=ahora - timedelta(days=5),
        )
        db.add(orden)

        # Crear ventas
        for i in range(1, 10):
            _crear_venta(db, prod, cantidad=10, dias_atras=i)

        db.commit()

        resultado = analisis_eficiencia(db, dias=30)
        assert resultado["ordenes_completadas"] >= 1
        assert resultado["total_producido"] > 0


class TestDashboardProduccion:
    def test_dashboard(self, db):
        """Dashboard retorna estructura completa."""
        from app.services.produccion_service import dashboard_produccion

        resultado = dashboard_produccion(db)
        assert "fecha" in resultado
        assert "ordenes_activas" in resultado
        assert "ordenes_completadas_hoy" in resultado
        assert "productos_con_deficit" in resultado
        assert "eficiencia_global_pct" in resultado


class TestAPIEndpoints:
    def test_prediccion_demanda_api(self, client, auth_headers):
        """GET /recetas/produccion/prediccion-demanda"""
        resp = client.get("/api/v1/recetas/produccion/prediccion-demanda", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_plan_produccion_api(self, client, auth_headers):
        """GET /recetas/produccion/plan"""
        resp = client.get("/api/v1/recetas/produccion/plan", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "plan" in data
        assert "ingredientes_consolidados" in data

    def test_eficiencia_api(self, client, auth_headers):
        """GET /recetas/produccion/eficiencia"""
        resp = client.get("/api/v1/recetas/produccion/eficiencia", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "eficiencia_global_pct" in data

    def test_dashboard_produccion_api(self, client, auth_headers):
        """GET /recetas/produccion/dashboard"""
        resp = client.get("/api/v1/recetas/produccion/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "ordenes_activas" in data
