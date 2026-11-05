# Avisos del receptor Uber Sandbox

Esta funcion pertenece al servicio aislado `uber-sandbox-webhook`, no al POS ni a
la tienda real. Requiere el entorno, aplicacion, tienda y base de datos TEST
ya validados por el runtime. Esta desactivada por defecto.

En Railway se deben configurar claves exclusivas y privadas para la aplicacion
de pruebas: `UBER_EATS_SANDBOX_PUSH_VAPID_PRIVATE_KEY` (escalar P-256 de 32
bytes en base64url sin relleno) y `UBER_EATS_SANDBOX_PUSH_STORAGE_KEY` (clave
Fernet). Despues se puede habilitar `UBER_EATS_SANDBOX_PUSH_ENABLED`. No usar
claves de Firebase, OAuth, webhooks ni de produccion. Si se cambia alguna clave,
los dispositivos tendran que restablecer y activar sus avisos de prueba.

La suscripcion se registra bajo autenticacion privada y se cifra en la base
Sandbox. El navegador conserva su suscripcion despues de bloquear o cerrar la
app; se puede dar de baja desde el boton de notificaciones. Los mensajes no
contienen datos de clientes. La cola recibe solo eventos de webhook de Uber
TEST previamente verificados, caduca a los 15 minutos y reintenta errores
temporales. Un evento puede llegar mas de una vez si falla el proceso despues
de enviarlo. El proveedor puede diferir o descartar avisos; el estado `sent`
solo confirma la aceptacion por el proveedor, no su llegada al iPad.

En iPadOS compatible se debe agregar la pagina a la pantalla de inicio, abrirla
desde su icono y pulsar el boton de activacion para conceder permiso. Probar la
entrega en pantalla bloqueada y al recuperar la conexion. Sin internet el
dispositivo no puede recibir el aviso en ese momento, y no debe asumirse que
siempre se entregara despues. Consultar la bandeja al volver a conectarse.

Las cancelaciones se consideran confirmadas solo con el webhook firmado que
corresponda. Una lectura `FAILED` sin webhook es una alerta de revision, no
una confirmacion firmada. Esta primera version envia push por eventos firmados;
una falla detectada solo por consulta sigue apareciendo en la bandeja, pero no
genera por si sola un push.
