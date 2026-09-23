# Preparacion de Uber Eats Marketplace

Estado: primera etapa de preparacion. No hay recepcion automatica de pedidos,
webhook habilitado, publicacion de menus ni vinculacion con una tienda real.
El canal manual de Uber Eats sigue siendo independiente de esta conexion.

Tienda compartida por el propietario:
https://www.ubereats.com/store-browse-uuid/d757be8e-a500-5e80-a148-8e7182329641?diningMode=DELIVERY
UUID del enlace: d757be8e-a500-5e80-a148-8e7182329641. Pendiente de confirmar
como store_id de API con Uber. No usar este identificador como tienda de pruebas.

## Disponible en Jacaranda

- Administrador: Punto de venta > Uber Eats > Conexion Uber Eats.
- Revision de productos activos, presentaciones, precios Uber Eats y existencias.
- ID propuesto estable por producto/presentacion, independiente del nombre y codigo
  editables. No equivale al ID del menu que ya existe en Uber.
- Diagnostico OAuth y consulta de una tienda de pruebas, con tokens privados en
  memoria del servidor, vencimiento, timeout y errores sin secretos.
- Solo se usan sandbox-login.uber.com y test-api.uber.com. No hay modo produccion.

Endpoints administrativos:

- GET /api/v1/uber-eats/preparacion: configuracion sin secretos y catalogo local.
- POST /api/v1/uber-eats/probar-conexion: autenticar y consultar tienda de pruebas.

## Lo que necesitamos de la tienda

1. Acceso de propietario/administrador a Uber Eats Manager, enlace de la tienda,
   sucursal e identificador store_id de produccion. No enviar la contrasena por chat.
2. Solicitar a Uber acceso a Eats Marketplace para integrar el POS propio de
   Jacaranda. Confirmar aprobacion, NDA/licencia API y permisos con su contacto
   comercial o https://t.uber.com/integration-support.
3. Crear aplicacion de tipo Testing, suite Eats Marketplace, en el Developer
   Dashboard. Solicitar una tienda de pruebas a soporte de integraciones.
4. Guardar Client ID y Client Secret de Testing en variables privadas del servidor.
   La tienda de pruebas usa su propio store_id, distinto del restaurante real.
5. Revisar el menu actual: precios, presentaciones, extras, combos, horarios,
   impuestos y tiempos de preparacion. Asignar explicitamente cada item de Uber
   a un producto local. No deducir relaciones por nombres similares ni sobrescribir
   el menu actual al conectarse.

## Configurar la prueba

```dotenv
UBER_EATS_SANDBOX_ENABLED=true
UBER_EATS_SANDBOX_CLIENT_ID=<client-id-de-testing>
UBER_EATS_SANDBOX_CLIENT_SECRET=<secreto-de-testing>
UBER_EATS_SANDBOX_STORE_ID=<store-id-de-pruebas>
```

El diagnostico solicita scope eats.store, usa client_credentials y consulta
GET https://test-api.uber.com/v1/eats/stores/{store_id}.
Una prueba exitosa solo verifica autenticacion y acceso a esa tienda; no indica
que pedidos, menu, aprobacion o tienda de produccion esten listos.
Credenciales vacias o flag apagado deshabilitan cualquier llamada a Uber.

## Siguientes etapas y criterios de activacion

1. Persistir vinculacion tienda/sucursal e items/presentaciones de ambos catalogos.
2. Implementar bandeja durable de webhooks con X-Uber-Signature (HMAC-SHA256 del
   cuerpo original usando el client secret), tienda y entorno verificados,
   deduplicacion por evento y pedido, reintentos y consulta autenticada del pedido.
   No seguir resource_href arbitrarios. No confirmar HTTP 200 antes de persistir.
3. Probar aceptar/rechazar, programados, cancelaciones y caidas. Uber exige
   aceptar/rechazar dentro de 11.5 minutos; recibir un webhook no acepta el pedido.
   Hacen falta procesamiento durable y alertas antes de habilitar pedidos reales.
4. Registrar venta/inventario una sola vez y revertir con trazabilidad cuando
   corresponda. Importes del pedido provienen de Uber, no de recalcular precios
   actuales. Separar cobro por plataforma de efectivo, CLIP y BBVA en el corte.
   Conciliar venta bruta, descuentos, comisiones y liquidaciones sin asumir que
   la venta bruta coincide con el deposito recibido.
5. Probar ticket e impresion con Easy POS Print y pedido importado; reimprimir
   nunca debe duplicar la venta. Probar reinicios y eventos fuera de orden.
6. Preparar vista previa de sincronizacion de menu/stock; confirmar vinculacion,
   horarios, impuestos, modificadores y cambios antes de enviar a Uber.
7. Verificacion con Uber, aplicacion Production y scopes aprobados, piloto con
   tienda actual y plan de retorno a Uber Eats Orders antes de activar POS.

Pruebas locales: `pytest -q tests/test_uber_eats.py`. La red de Uber se simula;
no se crean pedidos, no se modifica stock ni se activa una tienda durante tests.

## Solicitud sugerida a Uber (no enviada)

Hola, somos Jacaranda Reposteria Mexicana en Queretaro y ya tenemos una tienda
activa en Uber Eats. Queremos integrar nuestro sistema de punto de venta propio
con Uber Eats Marketplace para recibir pedidos, gestionar su aceptacion y
cancelacion, y sincronizar menu y disponibilidad. Podrian indicarnos el proceso
de aprobacion, los requisitos de licencia, el acceso a una tienda de pruebas y
la verificacion tecnica necesaria? Nuestra tienda es:
https://www.ubereats.com/store-browse-uuid/d757be8e-a500-5e80-a148-8e7182329641
Podrian confirmar tambien el store_id de API correspondiente a esta tienda?

## Fuentes oficiales consultadas el 22 de septiembre de 2026

- https://developer.uber.com/docs/eats/guides/getting-started
- https://developer.uber.com/docs/eats/guides/authentication
- https://developer.uber.com/docs/eats/guides/sandbox
- https://developer.uber.com/docs/eats/guides/webhooks
- https://developer.uber.com/docs/eats/guides/going-live
- https://developer.uber.com/docs/eats/references/api/v1/get-eats-stores-storeid

Nota: la pagina general menciona sandbox-auth; la guia especifica de sandbox
indica sandbox-login.uber.com/oauth/v2/token y ese es el dominio implementado.
Para consultar la tienda usamos /v1/eats/stores/{store_id}, documentado en
Get Store Details de Marketplace, aunque el ejemplo generico de sandbox muestra
otra ruta bajo /v1/delivery.
