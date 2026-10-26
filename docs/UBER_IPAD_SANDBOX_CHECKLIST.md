# Validacion de Jacaranda en iPad, solo Sandbox

Estado revisado el 25 de octubre de 2026. Este documento no autoriza produccion
ni acredita que se haya probado ya en un iPad fisico.

## Comprobado en el entorno hospedado

- Aplicacion TEST y tienda `b412bb20-cf36-4ada-ba77-fdda96ce8a9e` aisladas.
- `real_store_enabled=false`; no existen rutas operativas del POS en el receptor.
- Tienda TEST ONLINE, integracion habilitada, cuenta autorizada y menu ficticio.
- Catorce trabajos de tienda terminados y uno sustituido; sin pendientes de menu.
- El pedido UBER_TEST `bacf5bc2-2744-4272-a05d-6b92c739a5fc` ahora devuelve FAILED
  en la consulta canonica. La accion incierta se concilio usando esa lectura y
  el aviso firmado previo, sin reenviar cancelacion, aceptacion o ready.
- Su revision financiera TEST es 1. Permanece por revisar como pedido fallido y
  cancelacion de alimentos preparados; no se reponen existencias automaticamente.
- Efectivo recibido cero, sin cobros reales ni nuevos movimientos de inventario.
- Los avisos privados se actualizan mientras se usan otras secciones del panel.
  La prueba integrada de attention.js, finance.js y sandbox.js comprueba llegada
  en Finanzas TEST, apertura del pedido, invalidacion de un ticket por cambios,
  bloqueo al perder red, reconexion sin reenvio de acciones y salida segura.

Estas pruebas de navegador usan datos ficticios y no certifican el audio,
las restricciones de Safari o el comportamiento de un iPad concreto.

## Prueba fisica pendiente

1. Anotar modelo de iPad, version de iPadOS y si se usa Safari o acceso desde
   pantalla de inicio. Usar exclusivamente Jacaranda Sandbox y sus credenciales;
   no cerrar, cambiar ni autorizar la cuenta de la tienda real.
2. Comprobar la tienda TEST, el menu ficticio y el indicador de conexion antes
   de iniciar. Confirmar con Uber el modo de integracion que no requiere Orders
   visible; ONLINE en una consulta no demuestra por si solo esa configuracion.
3. Dejar solo Jacaranda Sandbox visible a pantalla completa, sin Split View y
   sin Orders Sandbox en primer plano. La configuracion de Orders real no se toca.
4. Activar el sonido con un toque y mantener Finanzas TEST abierta. Crear desde
   la cuenta de consumidor de pruebas un pedido del menu ficticio con UBER_TEST.
   Si aparece tarjeta, efectivo real u otro cobro, detenerse antes de confirmar.
5. Registrar hora del checkout, llegada del webhook y aviso visual/sonoro en el
   iPad. Abrirlo desde la banda de pendientes, comprobar productos, instrucciones
   y alergias, y aceptar/marcar listo una sola vez con las confirmaciones del panel.
6. Revisar la venta TEST y las existencias ficticias. Repetir la consulta no debe
   duplicar venta ni salida de producto/empaque. Efectivo de caja debe seguir cero.
7. Solo con el iPad dedicado a pruebas, y sin ventas o pedidos reales en el equipo,
   la persona operadora puede ensayar perdida y recuperacion de Wi-Fi. Mantener
   la ultima bandeja visible, bloquear acciones antiguas y exigir nueva revision
   al recuperar conexion. No reenviar una aceptacion/cancelacion incierta.
8. Ensayar regreso de Safari tras bloqueo de pantalla y verificar la conexion y
   el estado del sonido antes de seguir. No prometer audio ni ejecucion continua
   mientras Safari esta suspendido. Conservar evidencia y marcar cada paso como
   aprobado, fallido o no probado.

## Antes de cualquier uso real

- Obtener la validacion de Uber y confirmacion de la configuracion sin Orders
  visible para este integrador. Una TEST APP no autoriza acceso de produccion.
- Cerrar la prueba fisica del iPad y el procedimiento de contingencia del personal.
- Mantener separado el canal externo de los cobros de caja y completar la revision
  de liquidaciones reales, ediciones y cancelaciones antes de habilitar escrituras.
- Autorizar por separado la aplicacion y vinculacion de la tienda real. El PR87
  de Sandbox sigue en borrador y no se integra a main para este ensayo.

## Fuentes oficiales

- https://developer.uber.com/docs/eats/guides/sandbox
- https://developer.uber.com/docs/eats/guides/order-integration
- https://help.uber.com/en/merchants-and-restaurants/article/do-i-still-need-a-tablet-if-i-am-pos-integrated?nodeId=98105c86-944d-40ad-b9f0-3abea73005a9

Uber indica que muchas integraciones permiten operar sin tablet, pero depende
de las capacidades y configuracion del integrador; no es una garantia para esta
tienda antes de su validacion.
