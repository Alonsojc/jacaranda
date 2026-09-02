"""Regresiones del catálogo de venta, precios por canal y empaques."""

from decimal import Decimal


def _crear_producto(client, auth_headers, codigo, **extra):
    payload = {
        "codigo": codigo,
        "nombre": extra.pop("nombre", f"Producto {codigo}"),
        "precio_unitario": extra.pop("precio_unitario", "100.00"),
        "tasa_iva": "0.00",
        **extra,
    }
    response = client.post(
        "/api/v1/inventario/productos",
        json=payload,
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_codigos_se_normalizan_validan_y_sugieren(client, auth_headers):
    producto = _crear_producto(
        client,
        auth_headers,
        "ac-001",
        nombre="Apple Crumble chico",
        precio_uber_eats="135.00",
    )
    assert producto["codigo"] == "AC-001"
    assert Decimal(producto["precio_uber_eats"]) == Decimal("135.00")

    ocupado = client.get(
        "/api/v1/inventario/productos/codigo-disponible?codigo=ac-001",
        headers=auth_headers,
    )
    assert ocupado.status_code == 200
    assert ocupado.json() == {"codigo": "AC-001", "disponible": False}

    libre = client.get(
        "/api/v1/inventario/productos/codigo-disponible?codigo=ac-002",
        headers=auth_headers,
    )
    assert libre.status_code == 200
    assert libre.json() == {"codigo": "AC-002", "disponible": True}

    sugerido = client.get(
        "/api/v1/inventario/productos/codigo-sugerido"
        "?nombre=Apple%20Crumble%20grande&codigo_base=AC-001",
        headers=auth_headers,
    )
    assert sugerido.status_code == 200, sugerido.text
    assert sugerido.json()["codigo"] == "AC-002"
    assert sugerido.json()["prefijo"] == "AC"

    duplicado = client.post(
        "/api/v1/inventario/productos",
        json={
            "codigo": "Ac-001",
            "nombre": "Apple Crumble grande",
            "precio_unitario": "200.00",
        },
        headers=auth_headers,
    )
    assert duplicado.status_code == 400
    assert "Ya existe" in duplicado.json()["detail"]


def test_familias_formales_ligan_presentaciones_sin_usar_el_codigo(client, auth_headers):
    familia = client.post(
        "/api/v1/inventario/familias-producto",
        json={"nombre": "Caja Brownies"},
        headers=auth_headers,
    )
    assert familia.status_code == 201, familia.text
    familia_data = familia.json()

    x16 = _crear_producto(
        client,
        auth_headers,
        "CJ-001",
        nombre="Caja Brownies x16",
        familia_id=familia_data["id"],
        presentacion="x16",
    )
    assert x16["familia_id"] == familia_data["id"]
    assert x16["familia_nombre"] == "Caja Brownies"
    assert x16["presentacion"] == "x16"

    x8 = _crear_producto(
        client,
        auth_headers,
        "CJ-002",
        nombre="Caja Brownies x8",
        familia_id=familia_data["id"],
        presentacion="x8",
    )
    assert x8["familia_id"] == familia_data["id"]

    repetida = client.post(
        "/api/v1/inventario/productos",
        json={
            "codigo": "CJ-009",
            "nombre": "Otra caja de brownies",
            "precio_unitario": "100.00",
            "familia_id": familia_data["id"],
            "presentacion": "x16",
        },
        headers=auth_headers,
    )
    assert repetida.status_code == 400
    assert "Ya existe una presentación" in repetida.json()["detail"]

    actualizar_repetida = client.put(
        f"/api/v1/inventario/productos/{x8['id']}",
        json={"presentacion": "x16"},
        headers=auth_headers,
    )
    assert actualizar_repetida.status_code == 400
    assert "Ya existe una presentación" in actualizar_repetida.json()["detail"]

    individual = _crear_producto(client, auth_headers, "BR-001", nombre="Brownie")
    convertida = client.post(
        f"/api/v1/inventario/productos/{individual['id']}/crear-familia",
        headers=auth_headers,
    )
    assert convertida.status_code == 200, convertida.text
    assert convertida.json()["familia_nombre"] == "Brownie"
    assert convertida.json()["presentacion"] == "Original"


def test_venta_uber_eats_usa_solo_su_precio_configurado(client, auth_headers):
    producto = _crear_producto(
        client,
        auth_headers,
        "UE-001",
        precio_unitario="100.00",
        precio_uber_eats="145.00",
    )
    venta = client.post(
        "/api/v1/punto-de-venta/ventas",
        json={
            "canal": "uber_eats",
            "metodo_pago": "01",
            "terminal": "efectivo",
            "monto_recibido": "145.00",
            "detalles": [{"producto_id": producto["id"], "cantidad": 1}],
        },
        headers=auth_headers,
    )
    assert venta.status_code == 201, venta.text
    data = venta.json()
    assert data["canal"] == "uber_eats"
    assert Decimal(data["total"]) == Decimal("145.00")
    assert Decimal(data["detalles"][0]["precio_unitario"]) == Decimal("145.00")

    sin_precio = _crear_producto(client, auth_headers, "UE-002")
    rechazada = client.post(
        "/api/v1/punto-de-venta/ventas",
        json={
            "canal": "uber_eats",
            "metodo_pago": "01",
            "terminal": "efectivo",
            "monto_recibido": "100.00",
            "detalles": [{"producto_id": sin_precio["id"], "cantidad": 1}],
        },
        headers=auth_headers,
    )
    assert rechazada.status_code == 400
    assert "no tiene precio de Uber Eats" in rechazada.json()["detail"]


def test_catalogo_empaques_no_mezcla_ingredientes_y_ajusta_enteros(client, auth_headers):
    ingrediente = client.post(
        "/api/v1/inventario/ingredientes",
        json={
            "nombre": "Huevo por pieza",
            "unidad_medida": "pz",
            "stock_minimo": "6",
            "costo_unitario": "3.00",
        },
        headers=auth_headers,
    )
    assert ingrediente.status_code == 201, ingrediente.text
    assert ingrediente.json()["es_empaque"] is False

    empaque = client.post(
        "/api/v1/inventario/empaques",
        json={
            "nombre": "Base individual",
            "unidad_medida": "pz",
            "stock_actual": 12,
            "stock_minimo": 4,
            "costo_unitario": "2.50",
        },
        headers=auth_headers,
    )
    assert empaque.status_code == 201, empaque.text
    empaque_data = empaque.json()
    assert empaque_data["es_empaque"] is True
    assert Decimal(empaque_data["stock_actual"]) == Decimal("12.0000")

    catalogo = client.get("/api/v1/inventario/empaques", headers=auth_headers)
    assert catalogo.status_code == 200
    assert [item["nombre"] for item in catalogo.json()] == ["Base individual"]

    invalido = client.post(
        "/api/v1/inventario/productos",
        json={
            "codigo": "PK-INVALID",
            "nombre": "Producto con huevo",
            "precio_unitario": "30.00",
            "caja_ingrediente_id": ingrediente.json()["id"],
            "caja_cantidad": 1,
        },
        headers=auth_headers,
    )
    assert invalido.status_code == 400
    assert "marcado como caja/empaque" in invalido.json()["detail"]

    producto = _crear_producto(
        client,
        auth_headers,
        "PK-001",
        caja_ingrediente_id=empaque_data["id"],
        caja_cantidad=1,
    )
    assert producto["caja_ingrediente_id"] == empaque_data["id"]

    fraccion = client.post(
        f"/api/v1/inventario/ingredientes/{empaque_data['id']}/ajuste-stock"
        "?cantidad=8.5&motivo=Conteo",
        headers=auth_headers,
    )
    assert fraccion.status_code == 400

    ajuste = client.post(
        f"/api/v1/inventario/ingredientes/{empaque_data['id']}/ajuste-stock"
        "?cantidad=8&motivo=Conteo",
        headers=auth_headers,
    )
    assert ajuste.status_code == 200, ajuste.text
    assert ajuste.json()["stock_nuevo"] == 8.0
