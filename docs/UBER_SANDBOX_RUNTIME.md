# Receptor aislado de Jacaranda Sandbox

Este servicio recibe webhooks de la aplicacion TEST de Jacaranda. No inicia
el POS, sus migraciones, usuarios ni procesos de negocio. Por defecto solo recibe
eventos y no necesita OAuth. La gestion manual es optativa, privada y exclusiva
de la tienda de pruebas; nunca usa sesiones o credenciales del POS.

## Aislamiento

- Proyecto Railway Jacaranda; entorno nuevo `uber-sandbox`, creado sin duplicar
  produccion. Nunca usar `railway environment new --duplicate production`.
- Servicio `uber-sandbox-webhook`, arranque `python -m app.uber_sandbox_runtime`.
- PostgreSQL privado independiente `uber-sandbox-db`; base
  `jacaranda_uber_sandbox`, usuario `jacaranda_sandbox` y volumen propio.
- Solo permite `uber_sandbox_events`, `uber_sandbox_orders` y
  `uber_sandbox_actions`; rechaza una base con otras tablas antes de cualquier
  DDL. En modo receptor solo crea la primera tabla. No se restaura ningun
  respaldo operativo en esta base.
- El arranque valida entorno, host privado, nombre de base, usuario, aplicacion
  TEST, UUID sandbox y dominios de API/autenticacion exclusivamente sandbox.
- Por defecto solo publica `POST /api/v1/uber-eats/sandbox/webhook` y `GET /health`.
  La comprobacion de salud consulta la tabla; no es solo liveness.
- Las credenciales de PostgreSQL y firma son nuevas y permanecen en variables
  privadas de este entorno. No reutilizar claves de usuarios, OCR, Google,
  sesiones, base de ventas ni credenciales de la tienda real.

## Configuracion

La configuracion en `.railway/railway.ts` usa una partial con nombre y valida el
Project ID y Environment ID del sandbox. Solo administra el receptor; no migra
`railway.json`, no administra produccion y no elimina otros recursos del proyecto.
La base y el volumen se aprovisionan por separado. Revisar el plan antes de aplicar.

```sh
npm ci --prefix .railway --ignore-scripts
npx --yes @railway/cli@5.71.0 config plan --environment uber-sandbox
npx --yes @railway/cli@5.71.0 config apply --environment uber-sandbox --yes
```

No aplicar si el plan incluye eliminaciones, otros servicios, produccion o la
eliminacion de limites de recursos. No usar `--confirm-destructive` para este flujo.
El receptor y PostgreSQL estan limitados individualmente a 0.1 vCPU y 0.25 GB.
No cambiar limites globales de gasto: podrian detener los servicios de ventas.
Los US$5-10/mes comunicados son estimacion de consumo, no tarifa ni tope garantizado.

Variables del receptor:

```dotenv
JACARANDA_RUNTIME=uber-sandbox
JACARANDA_SANDBOX_DATABASE_HOST=${{uber-sandbox-db.RAILWAY_PRIVATE_DOMAIN}}
DATABASE_URL=${{uber-sandbox-db.DATABASE_URL}}
UBER_EATS_SANDBOX_ENABLED=true
UBER_EATS_SANDBOX_WEBHOOK_ENABLED=true
UBER_EATS_SANDBOX_ACTIONS_ENABLED=false
UBER_EATS_SANDBOX_MANAGEMENT_ENABLED=false
UBER_EATS_SANDBOX_CLIENT_ID=I2pbZ-jD6Qa7FQzhLUbX3Y5gN12EasPL
UBER_EATS_SANDBOX_STORE_ID=b412bb20-cf36-4ada-ba77-fdda96ce8a9e
UBER_EATS_SANDBOX_WEBHOOK_SECRET=<clave privada exclusiva, nunca en Git>
```

En el Developer Dashboard de la aplicacion TEST se configura Primary Webhook y
Basic HMAC, con esa misma clave en Signing Key. La persona titular introduce y
guarda la clave; no enviarla por chat ni correo. No configurar una aplicacion
Production ni activar POS Integration de la tienda real.

## Gestion privada de pedidos de pruebas

Solo despues de preparar y verificar credenciales TEST:

```dotenv
UBER_EATS_SANDBOX_MANAGEMENT_ENABLED=true
UBER_EATS_SANDBOX_ADMIN_TOKEN=<clave aleatoria exclusiva de al menos 48 caracteres>
UBER_EATS_SANDBOX_CLIENT_SECRET=<Client Secret de la aplicacion TEST>
UBER_EATS_SANDBOX_ACTIONS_ENABLED=true
```

La clave administrativa no puede ser la de OAuth ni la del webhook. Guardarla
solo en variables privadas y en el gestor de la persona titular. La persona
introduce las credenciales en los servicios correspondientes; nunca en el chat.

La raiz del dominio muestra la bandeja de Sandbox. Todos los datos y acciones
requieren `Authorization: Bearer` con la clave exclusiva; no acepta la clave en
URL ni cookies. El navegador solo la mantiene en memoria, la limpia al salir y
al abandonar la pagina, y no usa localStorage ni credenciales de produccion.
Las respuestas son no-store, sin CORS, sin terceros y no pueden enmarcarse.

La bandeja reutiliza los servicios de consulta y acciones existentes: lista
notificaciones, consulta detalles autenticados, conserva instrucciones completas
y solicita confirmacion manual para aceptar, rechazar o cancelar. El servidor
verifica tienda/pedido, detalle reciente y su hash antes de actuar. Registra la
operacion antes de enviarla y bloquea reenvios ante resultados inciertos.
No crea ventas ni movimientos de existencias. No hay aceptacion automatica.

### Avisos y recuperacion

`GET /api/v1/uber-eats/sandbox/atencion` consulta solo el inbox privado y los
estados locales de pruebas. Agrupa por pedido, cuenta toda la cola y devuelve
hasta 100 pendientes; no depende de la pagina de historial ni llama a Uber.
Conserva las operaciones inciertas y los cambios por verificar, y excluye los
pedidos terminados o ya listos cuando no requieren revision.

La banda de pendientes se actualiza cada 15 segundos en todas las secciones
del panel. El sonido se habilita con un toque; cada pedido/tipo suena una vez
por sesion, conservando el aviso visual hasta su resolucion. Credenciales y
deduplicacion de sonido permanecen en memoria, no en almacenamiento del navegador.

Al perder conexion se conserva la ultima lista, se muestra la hora de su ultima
consulta y se bloquean las acciones basadas en detalles antiguos. La recuperacion
consulta otra vez la bandeja con esperas de 5, 10, 20 y hasta 30 segundos; nunca
reenvia acciones. La vuelta a una pagina visible tambien fuerza una consulta.
Una sesion vencida limpia el panel. Los cambios de pedido recibidos durante la
consulta de detalles requieren otra revision antes de enviar una accion.

Esta comprobacion cubre el panel Sandbox con la pagina visible. Safari en un iPad
fisico, integracion de avisos en las secciones de caja y registro automatico de
ventas/inventario siguen siendo etapas distintas; no se habilitan aqui.

Vista local con datos ficticios y sin red saliente:
`python scripts/preview_uber_sandbox.py --port 8767`.
Solo escucha en `127.0.0.1`; la clave de fixture es `local-fixture-only` y no sirve
en el servidor. Las pruebas de reconexion y sonido no deben producir acciones
de Uber ni movimientos financieros.

La prueba con Uber debe confirmar que la cuenta es TEST, la tienda es
`b412bb20-cf36-4ada-ba77-fdda96ce8a9e` y el medio de pago es exclusivamente
`UBER_TEST`. Si se ofrece un cobro real o no aparece ese medio, detenerse antes
de confirmar. Probar recepcion, consulta, aceptacion y rechazo en pedidos
distintos; registrar evidencia de Uber por separado de las pruebas sinteticas.
No afirmar que la operacion en iPad esta validada solo por recibir un webhook.

## Verificacion antes de avisar a Uber

1. Confirmar despliegue correcto, PostgreSQL propio y HTTPS con certificado valido.
2. Comprobar 401 sin firma, 200 vacio con firma valida, 403 para otra tienda y 409
   si un mismo evento firmado intenta cambiar de identidad.
3. Repetir el evento y reiniciar solo el receptor sandbox. Un conflicto posterior
   al reinicio demuestra que la identidad original persiste en PostgreSQL.
4. Confirmar 404 en rutas de ventas, clientes, inventario y autenticacion.
5. Guardar el webhook en Uber, comprobar URL y aplicacion TEST en el dashboard y
   solicitar una entrega de prueba del proveedor. Una prueba sintetica propia no
   demuestra aun la entrega de Uber ni el flujo completo de pedidos.
6. Verificar que los despliegues de web y PostgreSQL de produccion no cambiaron.

Fuente oficial: https://developer.uber.com/docs/eats/guides/webhooks
Fuente Railway: https://docs.railway.com/infrastructure-as-code

## Ensayo de desvinculacion

La accion privada `desvincular` solo esta disponible en el runtime aislado y
requiere confirmacion, revision reciente, tienda pausada y el token de comerciante
ya autorizado. Usa `DELETE /v1/eats/stores/{TEST_STORE_ID}/pos_data`; no elimina la
tienda ni su menu. No acepta otra tienda ni un token client_credentials.

Un DELETE confirmado con 200 y posterior 403/404 de GET pos_data permite mostrar
la integracion revocada, sin fingir que aun puede consultarse su disponibilidad.
Si se pierde la respuesta, el 403/404 solo no basta: se necesita tambien una
notificacion de revocacion firmada posterior a la accion. Nunca se reenvia DELETE.
La accion existente `vincular` recupera la asociacion con el mismo comerciante;
despues deben verificarse configuracion, menu y disponibilidad antes de finalizar.

No ejecutar este ensayo con pedidos de prueba activos. Un HTTP 200 de la accion
no acredita por si solo haber recibido `store.deprovisioned` de Uber.

El worker conserva como `superseded` / `sustituido_por_baja` los avisos de estado
pendientes o fallidos estrictamente anteriores a una baja firmada de la misma
tienda y aplicacion. No vuelve a consultar ese acceso retirado ni borra la
evidencia; avisos nuevos, de la misma fecha o sin esa prueba siguen su manejo
normal de errores. La recuperacion posterior no reactiva esos avisos obsoletos.
