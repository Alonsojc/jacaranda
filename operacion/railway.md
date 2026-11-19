# Jacaranda en Railway

## Configuración del servicio web

El servicio `web` de `Jacaranda / production` usa la definición en
`.railway/railway.ts`. El volumen `web-volume` está montado en `/data`.
Las variables se administran en Railway. PostgreSQL y el entorno de Uber
Sandbox tienen administración independiente.

Desde el repositorio vinculado a producción, instalar el SDK con
`npm ci --prefix .railway --ignore-scripts` y revisar cualquier cambio con
`railway config plan --environment production`. Se verificó con la CLI
5.75.0. La versión 5.71.0 puede volver a proponer los diez reintentos
predeterminados aunque la instancia ya tenga esa política. El plan de la
migración solo actualiza construcción, arranque, salud y reintentos de `web`.

## Respaldos automáticos

Con `BACKUP_SCHEDULE_ENABLED=true` en el servicio `web`, Jacaranda ejecuta
`pg_dump` en segundo plano y publica la copia completa en `/data/backups`,
en un volumen separado de PostgreSQL. A partir de las 03:00 de Ciudad de
México crea la copia del día y conserva la primera captura de cada semana.
Al arrancar recupera el periodo pendiente y reintenta cada cinco minutos.
Se conservan las últimas siete diarias y cuatro semanales. El panel
**Respaldos** permite inspeccionarlas y descargarlas. El registro del
servicio incluye el SHA-256 del archivo diario al publicarlo.

## Traslado de región de PostgreSQL

Desde el 18 de noviembre de 2026, la aplicación y PostgreSQL están en
Virginia (`us-east4-eqdc4a`). El traslado desde Ámsterdam se verificó con
una restauración aislada y la conciliación de diez tablas. El volumen de
PostgreSQL está montado en `/var/lib/postgresql/data`. Se conserva el
procedimiento usado en esa ventana.

1. Al cierre de caja, confirmar el último corte y la sincronización de los
   dispositivos. Mantener pausados los registros de ventas, pagos, pedidos y
   movimientos hasta la conciliación. Guardar el último folio y el total del
   corte. Obtener las huellas de producción con una conexión de solo lectura
   y `psql -X -qAt -v ON_ERROR_STOP=1 -f operacion/conciliar-region.sql`.
2. En **Respaldos**, crear una copia PostgreSQL posterior al cierre.
   Conservar el SHA-256 informado al crearla y descargar ese mismo archivo
   por nombre al volumen cifrado `JacarandaRespaldos`. Mantener allí la
   copia y los comprobantes.
3. Con las herramientas de PostgreSQL 18 en el `PATH`, ejecutar
   `sh operacion/verificar-respaldo.sh "/ruta/cifrada/respaldo.sql" "$sha256_del_servidor"`.
   El verificador comprueba el hash, restaura el SQL en una instancia local
   con socket privado y emite los conteos y huellas de diez tablas.
   Compararlos con los del cierre. Una restauración fallida o una diferencia
   deja el cambio pendiente de revisión.
4. En **Jacaranda → production → Postgres**, seleccionar **US East Metal
   (Virginia)** y revisar que Railway trasladará el volumen de datos
   existente. Aplicar únicamente ese cambio de región y esperar a que
   termine el traslado del volumen y PostgreSQL vuelva a estar disponible.
5. Antes de reabrir, repetir la conciliación de las diez tablas y comprobar
   el último folio y corte contra los del cierre. Verificar `/ready`, catálogo,
   alertas y lectura de un ticket desde el iPad. Registrar región, salud y
   tiempos de respuesta. Reanudar escrituras al concluir estas comprobaciones.
6. Si falla el traslado, mantener la caja en pausa y comprobar la región y
   el montaje efectivos en Railway. Conservar el volumen y la copia cifrada.
   Si hace falta volver a Ámsterdam, mover el mismo volumen y repetir la
   conciliación. Si se requiere recuperación desde el respaldo, restaurarlo
   en una instancia separada, validarla y vincular un solo destino de escritura.

La verificación desde el panel de respaldos inspecciona el SQL. La prueba
del paso 3 ejecuta una restauración completa. La conciliación compara datos
operativos y excluye los eventos administrativos generados al crear y
descargar la copia.

[Regiones y traslado de volúmenes en Railway](https://docs.railway.com/deployments/regions)
