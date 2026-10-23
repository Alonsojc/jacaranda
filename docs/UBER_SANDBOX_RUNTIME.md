# Receptor aislado de Jacaranda Sandbox

Este servicio solo recibe webhooks de la aplicacion TEST de Jacaranda. No inicia
el POS, sus migraciones, usuarios, procesos de negocio ni rutas administrativas.
No consulta, acepta ni rechaza pedidos y no necesita el Client Secret de OAuth.

## Aislamiento

- Proyecto Railway Jacaranda; entorno nuevo `uber-sandbox`, creado sin duplicar
  produccion. Nunca usar `railway environment new --duplicate production`.
- Servicio `uber-sandbox-webhook`, arranque `python -m app.uber_sandbox_runtime`.
- PostgreSQL privado independiente `uber-sandbox-db`; base
  `jacaranda_uber_sandbox`, usuario `jacaranda_sandbox` y volumen propio.
- Solo crea `uber_sandbox_events`; rechaza una base con otras tablas antes de
  hacer cualquier DDL. No se restaura ningun respaldo operativo en esta base.
- El arranque valida entorno, host privado, nombre de base, usuario, aplicacion
  TEST, UUID sandbox y acciones deshabilitadas.
- Solo publica `POST /api/v1/uber-eats/sandbox/webhook` y `GET /health`.
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
UBER_EATS_SANDBOX_CLIENT_ID=I2pbZ-jD6Qa7FQzhLUbX3Y5gN12EasPL
UBER_EATS_SANDBOX_STORE_ID=b412bb20-cf36-4ada-ba77-fdda96ce8a9e
UBER_EATS_SANDBOX_WEBHOOK_SECRET=<clave privada exclusiva, nunca en Git>
```

En el Developer Dashboard de la aplicacion TEST se configura Primary Webhook y
Basic HMAC, con esa misma clave en Signing Key. La persona titular introduce y
guarda la clave; no enviarla por chat ni correo. No configurar una aplicacion
Production ni activar POS Integration de la tienda real.

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
