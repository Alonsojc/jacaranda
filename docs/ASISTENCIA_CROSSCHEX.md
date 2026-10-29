# Asistencia CrossChex: primera etapa

Preparacion local; no habilitar en produccion hasta verificar cuenta, equipo y
ventana de mantenimiento. No depende de Uber y no modifica ventas o inventario.

## Alcance

- Consulta manual de checadas mediante `authorize.token` y `attendance.record`.
- Resumen por dia local/persona: primera marca, ultima marca y numero de marcas.
  No son horas trabajadas: puede haber comidas, salidas, turnos nocturnos o marcas
  incompletas. Una sola marca no se convierte en entrada/salida completa.
- Vinculacion explicita con un empleado existente de Jacaranda. No se adivina por
  nombre ni se crean empleados automaticamente. El endpoint del selector no
  expone salarios, CURP, RFC ni NSS.
- Historial paginado, busqueda y CSV con proteccion contra formulas.
- Administrador y gerente: consulta, importacion y vinculacion. Contador: lectura.
  Se requieren tanto rol autorizado como permiso del modulo `asistencia`.
- Tablas independientes de `registros_asistencia` y `registros_nomina`. No genera
  descuentos, faltas, retardos, horas extra, salarios ni decisiones laborales.

## Conectar cuando llegue el equipo

1. Crear una cuenta CrossChex exclusiva del negocio, con acceso de la propietaria.
   Elegir/verificar su region, sin deducirla a partir del idioma o la ubicacion.
2. Vincular el EP30 por numero de serie y verificar fecha, zona horaria y WiFi.
   Confirmar que el firmware/modelo exacto admite CrossChex Cloud.
3. Revisar Settings > Developer Mode. Si no aparece, solicitar habilitacion al
   soporte Anviz con Company ID y numero de serie. Verificar el alcance/costo de
   API en la cuenta; el nivel gratuito de 1 admin + 1 equipo no prueba por si solo
   que Developer Mode este habilitado.
4. Guardar API Key y API Secret en un gestor y exclusivamente en variables
   privadas del backend. Nunca en el navegador, Git, un correo o capturas.
5. Configurar `CROSSCHEX_REGION` (`us`, `eu` o `ap`), `CROSSCHEX_COMPANY_ID` y
   `CROSSCHEX_DEVICE_SERIALS` (lista separada por comas de equipos autorizados).
   Se requieren todos, mas las dos claves, antes de poner `CROSSCHEX_ENABLED=true`.
6. Hacer respaldo verificado y revisar la migracion `a6d8e102c739`. El despliegue
   requiere caja cerrada y todos los dispositivos sin pendientes de sincronizar.
7. Probar primero con una identidad ficticia: dos marcas, consulta del mismo dia,
   reintento, marca sin salida y fecha cerca de medianoche. Confirmar los codigos
   `checktype` reales del equipo antes de interpretar entrada/salida.
8. Vincular cada numero del reloj con su empleado y comparar evidencia con Cloud.
   Si se recicla un numero de empleado del reloj, detener la importacion: esta
   version no admite reasignaciones silenciosas ni historiales por vigencia.

## Limites y seguridad

- La integracion permanece desactivada por defecto. La pantalla puede consultarse
  vacia sin tener cuenta ni equipo. No hay trabajo programado ni webhook entrante.
- Sincronizacion de hasta 7 dias, 500 registros/pagina, hasta 10 paginas. Se valida
  toda la respuesta antes de insertar. Si hay demasiados datos, dividir el periodo.
- Consultas de hasta 31 dias/10,000 marcas. Cualquier error deja el lote sin importar.
  Respuestas parciales o paginacion cambiante requieren reintento; no se presentan
  como exito. Reconsultar dias anteriores recupera marcas subidas tarde por WiFi.
- Identidad unica: region/empresa + serie + numero de persona + instante UTC +
  codigo original. La restriccion en base de datos impide duplicados por reintento
  o peticiones concurrentes. Marcas distintas del mismo segundo con distinto
  codigo se conservan. Dos eventos realmente identicos no pueden distinguirse
  sin un identificador estable de CrossChex.
- Se guarda solo numero/nombre, hora UTC, codigo y equipo. Otros campos se ignoran;
  no se importan imagenes, huellas, plantillas biometricas ni respuestas completas.
- Los datos laborales requieren permisos, politica de retencion y aviso de
  privacidad del negocio antes del uso real. La inscripcion biometrica se gestiona
  en el equipo/Cloud, fuera de Jacaranda.
- Los endpoints salen solo a los tres hosts CrossChex fijos por HTTPS, sin
  redirecciones. Token efimero en memoria; secretos no se retornan ni registran.
- CSV y API usan `Cache-Control: no-store`. El frontend borra marcas y nombres al
  cerrar sesion; el service worker no almacena las respuestas API.
- La migracion es aditiva. Su downgrade conserva evidencia en vez de eliminarla.
  Desactivar la integracion no borra checadas ni altera la nomina.

## Pendientes despues de la primera validacion real

- Sincronizacion automatica con cursor/solapamiento, bloqueo distribuido y alertas.
- Jornadas/turnos por persona, descansos y turnos nocturnos, tras definir reglas.
- Correcciones con aprobacion, motivos y conservacion de las marcas originales.
- Reporte de horas revisadas para nomina, nunca descuentos automaticos.

## Fuentes

- API: https://community.anviz.com/t/how-to-use-api-to-get-the-records-from-the-crosschex-cloud/726
- Suscripcion: https://support.anviz.com/hc/en-us/articles/45737200923929-CrossChex-Cloud-Subscription-s-FAQ-List
- Equipos/Cloud: https://support.anviz.com/hc/en-us/articles/41632975467545-How-to-Transfer-Data-from-CrossChex-Standard-to-CrossChex-Cloud
- Iconos: Lucide, descargados de https://github.com/lucide-icons/lucide/tree/main/icons
  el 2026-10-28; licencia incluida en `icons/lucide/LICENSE`.
