"""
Script de datos demo para demostración del sistema Jacaranda.
Genera clientes, ventas, pedidos, empleados, merma y más.
Ejecutar después de init_db.py: python scripts/seed_demo.py
"""

import sys
import os
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine, Base, SessionLocal
from app.core.security import get_password_hash

# Ensure base data exists
from scripts.init_db import crear_tablas, crear_datos_semilla

# Import models
from app.models.usuario import Usuario, RolUsuario
from app.models.cliente import Cliente
from app.models.inventario import Producto
from app.models.empleado import (
    Empleado, TipoContrato, TipoJornada, Departamento,
)
from app.models.venta import (
    Venta, DetalleVenta, MetodoPago, FormaPago, EstadoVenta,
)
from app.models.pedido import (
    Pedido, DetallePedido, EstadoPedido, OrigenPedido,
)
from app.models.merma import RegistroMerma, TipoMerma
from app.models.crm import Campana, InteraccionCliente, EncuestaSatisfaccion
from app.models.cofepris import (
    RegistroTemperatura, RegistroLimpieza, AreaEstablecimiento,
)

HOY = date.today()
AHORA = datetime.now(timezone.utc)


def _random_date(days_back=30):
    d = HOY - timedelta(days=random.randint(0, days_back))
    h = random.randint(8, 20)
    m = random.randint(0, 59)
    return datetime(d.year, d.month, d.day, h, m, 0, tzinfo=timezone.utc)


def seed_demo():
    crear_tablas()
    crear_datos_semilla()

    db = SessionLocal()
    try:
        # Check if demo data already exists
        if db.query(Cliente).filter(Cliente.nombre == "María González").first():
            print("Datos demo ya existen. Saltando.")
            return

        # Get admin user and products
        admin = db.query(Usuario).filter(Usuario.rol == RolUsuario.ADMINISTRADOR).first()
        if not admin:
            print("ERROR: No hay usuario administrador. Ejecuta init_db.py primero.")
            return
        productos = db.query(Producto).filter(Producto.activo.is_(True)).all()
        if not productos:
            print("ERROR: No hay productos. Ejecuta init_db.py primero.")
            return

        print("Insertando datos demo...")

        # ── Clientes ─────────────────────────────────────────────
        clientes_data = [
            ("María González", "4421234567", "maria@gmail.com", "GOMA850315LK2"),
            ("Carlos Hernández", "4429876543", "carlos.h@outlook.com", "HESC900428AB1"),
            ("Ana López Ramírez", "4425551234", "ana.lopez@yahoo.com", "LORA880612CD3"),
            ("Roberto Díaz", "4428887766", "roberto.diaz@gmail.com", "DIRR920115EF4"),
            ("Patricia Morales", "4426543210", "paty.morales@hotmail.com", "MOPP870930GH5"),
            ("Luis Miguel Torres", "4421112233", "lmtorres@gmail.com", "TOLL930722IJ6"),
            ("Sofía Martínez", "4423344556", "sofia.m@gmail.com", "MASS950805KL7"),
            ("Fernando Ruiz", "4427788990", "fer.ruiz@outlook.com", "RUOF880413MN8"),
            ("Gabriela Sánchez", "4424455667", "gaby.sanchez@gmail.com", "SAGG910207OP9"),
            ("Diego Ramírez", "4426677889", "diego.ramirez@gmail.com", "RAMD960118QR0"),
        ]
        clientes = []
        niveles = ["bronce", "bronce", "bronce", "plata", "plata", "plata", "oro", "oro", "bronce", "plata"]
        for i, (nombre, tel, email, rfc) in enumerate(clientes_data):
            c = Cliente(
                nombre=nombre, telefono=tel, email=email, rfc=rfc,
                razon_social=nombre.upper(), regimen_fiscal="616",
                domicilio_fiscal_cp="76146", uso_cfdi="S01",
                puntos_acumulados=random.randint(0, 500),
                nivel_lealtad=niveles[i],
                puntos_totales_historicos=random.randint(100, 2000),
            )
            db.add(c)
            clientes.append(c)
        db.flush()
        print(f"  - {len(clientes)} clientes creados")

        # ── Empleados ────────────────────────────────────────────
        empleados_data = [
            ("Javier", "Pérez", "López", "PELJ850315HQRRPR01",
             "PELJ850315AB1", "12345678901", date(1985, 3, 15),
             "EMP-001", Departamento.PRODUCCION, "Maestro Panadero",
             Decimal("450.00"), TipoJornada.DIURNA),
            ("Lucía", "Mendoza", "García", "MEGL900428MQRNDR02",
             "MEGL900428CD2", "23456789012", date(1990, 4, 28),
             "EMP-002", Departamento.VENTAS, "Cajera",
             Decimal("300.00"), TipoJornada.DIURNA),
            ("Miguel", "Flores", "Hernández", "FOHM880612HQRLRG03",
             "FOHM880612EF3", "34567890123", date(1988, 6, 12),
             "EMP-003", Departamento.ADMINISTRACION, "Gerente",
             Decimal("500.00"), TipoJornada.DIURNA),
            ("Rosa", "Vega", "Torres", "VETR920115MQRGRS04",
             "VETR920115GH4", "45678901234", date(1992, 1, 15),
             "EMP-004", Departamento.PRODUCCION, "Auxiliar de Producción",
             Decimal("280.00"), TipoJornada.MIXTA),
            ("Pedro", "Castro", "Ruiz", "CARP930722HQRSRD05",
             "CARP930722IJ5", "56789012345", date(1993, 7, 22),
             "EMP-005", Departamento.LIMPIEZA, "Auxiliar General",
             Decimal("278.80"), TipoJornada.DIURNA),
        ]
        empleados = []
        for (nom, ap, am, curp, rfc, nss, fnac, num, dept, puesto, sal, jorn) in empleados_data:
            e = Empleado(
                nombre=nom, apellido_paterno=ap, apellido_materno=am,
                curp=curp, rfc=rfc, nss=nss, fecha_nacimiento=fnac,
                numero_empleado=num, fecha_ingreso=HOY - timedelta(days=random.randint(90, 730)),
                tipo_contrato=TipoContrato.INDETERMINADO,
                tipo_jornada=jorn, departamento=dept, puesto=puesto,
                salario_diario=sal,
                salario_diario_integrado=sal * Decimal("1.0493"),
                tiene_tarjeta_salud=True, capacitacion_higiene=True,
            )
            db.add(e)
            empleados.append(e)
        db.flush()
        print(f"  - {len(empleados)} empleados creados")

        # ── Ventas (últimos 30 días) ─────────────────────────────
        metodos = [MetodoPago.EFECTIVO, MetodoPago.TARJETA_DEBITO,
                    MetodoPago.TARJETA_CREDITO, MetodoPago.TRANSFERENCIA]
        ventas = []
        for i in range(30):
            fecha = _random_date(30)
            # 1-4 products per sale
            items = random.sample(productos, k=min(random.randint(1, 4), len(productos)))
            subtotal = Decimal("0")
            detalles = []
            for prod in items:
                qty = random.randint(1, 3)
                precio = prod.precio_unitario
                item_sub = precio * qty
                tasa = Decimal("0.16") if float(prod.tasa_iva.value) > 0 else Decimal("0")
                iva = (item_sub * tasa).quantize(Decimal("0.01"))
                detalles.append({
                    "producto_id": prod.id,
                    "cantidad": qty,
                    "precio_unitario": precio,
                    "subtotal": item_sub,
                    "tasa_iva": tasa,
                    "monto_iva": iva,
                    "clave_prod_serv_sat": prod.clave_prod_serv_sat or "50181904",
                    "clave_unidad_sat": "H87",
                })
                subtotal += item_sub

            iva_16 = sum(d["monto_iva"] for d in detalles)
            total = subtotal + iva_16
            metodo = random.choice(metodos)

            venta = Venta(
                folio=f"T-DEMO-{i+1:04d}",
                serie="T",
                usuario_id=admin.id,
                cliente_id=random.choice(clientes).id if random.random() > 0.3 else None,
                subtotal=subtotal,
                iva_16=iva_16,
                total_impuestos=iva_16,
                total=total,
                metodo_pago=metodo,
                forma_pago=FormaPago.PUE,
                monto_recibido=total if metodo != MetodoPago.EFECTIVO else total + Decimal(str(random.randint(0, 50))),
                cambio=Decimal("0") if metodo != MetodoPago.EFECTIVO else Decimal(str(random.randint(0, 50))),
                estado=EstadoVenta.COMPLETADA,
                fecha=fecha,
            )
            db.add(venta)
            db.flush()

            for d in detalles:
                db.add(DetalleVenta(
                    venta_id=venta.id,
                    producto_id=d["producto_id"],
                    cantidad=d["cantidad"],
                    precio_unitario=d["precio_unitario"],
                    subtotal=d["subtotal"],
                    tasa_iva=d["tasa_iva"],
                    monto_iva=d["monto_iva"],
                    clave_prod_serv_sat=d["clave_prod_serv_sat"],
                    clave_unidad_sat=d["clave_unidad_sat"],
                ))
            ventas.append(venta)
        db.flush()
        print(f"  - {len(ventas)} ventas creadas")

        # ── Pedidos ──────────────────────────────────────────────
        estados_pedido = list(EstadoPedido)
        origenes = list(OrigenPedido)
        pedidos_data = [
            ("Birthday Cake grande", "Pastel de cumpleaños con letrero 'Feliz cumple Ana'"),
            ("Caja Brownies x16", "Para evento corporativo"),
            ("Nutella Cookie Pie grande", "Entregar en domicilio"),
            ("Carrot Cake chico", "Sin nuez por alergia"),
            ("Cookies & Cream Cake grande", "Para XV años"),
            ("Polvorones de Nuez x25", "Regalo día de las madres"),
            ("Apple Crumble grande", "Para cena familiar"),
            ("Rosca de Chocolate", "Para bautizo"),
            ("Panqué de Plátano", "Pedido recurrente"),
            ("Linzer x7", "Caja de regalo"),
        ]
        for i, (prod_nombre, notas) in enumerate(pedidos_data):
            cli = random.choice(clientes)
            estado = estados_pedido[i % len(estados_pedido)]
            prod = db.query(Producto).filter(Producto.nombre == prod_nombre).first()
            precio = prod.precio_unitario if prod else Decimal("400")
            qty = random.randint(1, 3)
            total = precio * qty

            ped = Pedido(
                folio=f"PED-DEMO-{i+1:03d}",
                cliente_nombre=cli.nombre,
                cliente_telefono=cli.telefono,
                cliente_id=cli.id,
                fecha_entrega=HOY + timedelta(days=random.randint(-5, 10)),
                hora_entrega=f"{random.randint(10, 18)}:00",
                estado=estado,
                origen=random.choice(origenes),
                anticipo=total * Decimal("0.5") if random.random() > 0.3 else Decimal("0"),
                total=total,
                pagado=estado == EstadoPedido.ENTREGADO,
                notas=notas,
                creado_en=_random_date(15),
            )
            db.add(ped)
            db.flush()
            db.add(DetallePedido(
                pedido_id=ped.id,
                producto_id=prod.id if prod else None,
                descripcion=prod_nombre + (f" x{qty}" if qty > 1 else ""),
                cantidad=qty,
                precio_unitario=precio,
            ))
        db.flush()
        print(f"  - {len(pedidos_data)} pedidos creados")

        # ── Merma ────────────────────────────────────────────────
        tipos_merma = list(TipoMerma)
        motivos_merma = [
            "Producto caducado en vitrina",
            "Daño durante transporte",
            "Error en producción - textura incorrecta",
            "Devuelto por cliente",
            "Sobreproducción del día",
            "Humedad en almacén",
            "Quemado en horno",
            "Contaminación cruzada",
        ]
        for i in range(8):
            prod = random.choice(productos)
            tipo = tipos_merma[i % len(tipos_merma)]
            qty = Decimal(str(random.randint(1, 5)))
            costo = prod.costo_produccion or Decimal("25")
            db.add(RegistroMerma(
                producto_id=prod.id,
                tipo=tipo,
                cantidad=qty,
                unidad_medida="pz",
                costo_unitario=costo,
                costo_total=costo * qty,
                motivo=motivos_merma[i],
                fecha_merma=HOY - timedelta(days=random.randint(0, 20)),
                responsable_id=admin.id,
            ))
        db.flush()
        print("  - 8 registros de merma creados")

        # ── CRM: Campañas ────────────────────────────────────────
        campanas_data = [
            ("Promo Día de las Madres", "email", "¡20% en pasteles para mamá!"),
            ("Happy Hour Viernes", "whatsapp", "2x1 en galletas de 4-6pm"),
            ("Cumpleaños del mes", "sms", "Te regalamos un brownie en tu cumpleaños"),
            ("Nuevos Panqués", "email", "Conoce nuestros nuevos panqués artesanales"),
            ("Descuento primera compra", "whatsapp", "10% OFF en tu primera compra"),
        ]
        for nombre, tipo, mensaje in campanas_data:
            db.add(Campana(
                nombre=nombre,
                tipo=tipo,
                mensaje=mensaje,
                fecha_inicio=HOY - timedelta(days=random.randint(0, 15)),
            ))
        db.flush()
        print("  - 5 campañas CRM creadas")

        # ── CRM: Interacciones ───────────────────────────────────
        tipos_inter = ["compra", "consulta", "queja", "felicitacion", "seguimiento"]
        canales = ["presencial", "whatsapp", "telefono", "email"]
        descripciones = [
            "Compra regular de pies para la semana",
            "Consulta sobre pasteles para evento",
            "Queja: pedido llegó tarde",
            "Felicitación por calidad del producto",
            "Seguimiento post-compra satisfactorio",
            "Consulta precios para mayoreo",
            "Pedido especial de galletas navideñas",
            "Solicitud de factura",
            "Pregunta sobre ingredientes (alergias)",
            "Reservación para pastel de cumpleaños",
            "Queja: producto no fresco",
            "Felicitación al panadero",
            "Consulta sobre programa de puntos",
            "Pedido recurrente semanal",
            "Solicitud de catálogo actualizado",
        ]
        for i in range(15):
            cli = random.choice(clientes)
            db.add(InteraccionCliente(
                cliente_id=cli.id,
                tipo=random.choice(tipos_inter),
                canal=random.choice(canales),
                descripcion=descripciones[i],
                creado_en=_random_date(30),
            ))
        db.flush()
        print("  - 15 interacciones CRM creadas")

        # ── CRM: Encuestas ───────────────────────────────────────
        categorias_enc = ["servicio", "producto", "entrega", "precio", "ambiente"]
        for i in range(10):
            cli = random.choice(clientes)
            db.add(EncuestaSatisfaccion(
                cliente_id=cli.id,
                calificacion=random.randint(3, 5),
                categoria=random.choice(categorias_enc),
                comentario=random.choice([
                    "Excelente producto", "Muy buen servicio",
                    "Podría mejorar la presentación", "Todo perfecto",
                    "Precios justos", None, "Siempre fresco",
                ]),
            ))
        db.flush()
        print("  - 10 encuestas de satisfacción creadas")

        # ── COFEPRIS: Temperatura ────────────────────────────────
        emp_ids = [e.id for e in empleados]
        areas_temp = [AreaEstablecimiento.REFRIGERACION, AreaEstablecimiento.CONGELACION,
                      AreaEstablecimiento.PRODUCCION]
        for i in range(3):
            temp = Decimal(str(round(random.uniform(2.0, 5.0), 1)))
            db.add(RegistroTemperatura(
                area=areas_temp[i],
                equipo=f"Refrigerador {i+1}",
                temperatura_registrada=temp,
                temperatura_minima=Decimal("0.0"),
                temperatura_maxima=Decimal("6.0"),
                en_rango=temp <= Decimal("6.0"),
                responsable_id=emp_ids[i % len(emp_ids)],
            ))
        db.flush()
        print("  - 3 registros COFEPRIS temperatura creados")

        # ── COFEPRIS: Limpieza ───────────────────────────────────
        areas_limp = [AreaEstablecimiento.PRODUCCION, AreaEstablecimiento.PUNTO_VENTA]
        for i in range(2):
            db.add(RegistroLimpieza(
                area=areas_limp[i],
                actividad="Limpieza y desinfección general" if i == 0 else "Sanitización de superficies",
                productos_utilizados="Cloro, jabón neutro, desengrasante",
                responsable_id=emp_ids[i % len(emp_ids)],
            ))
        db.flush()
        print("  - 2 registros COFEPRIS limpieza creados")

        db.commit()
        print("\n✓ Datos demo insertados exitosamente.")
        print("  El sistema está listo para demostración.")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo()
