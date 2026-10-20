# Importar gastos desde Excel

Disponible para usuarios con permiso de editar Egresos. No depende del lector
OCR ni envia los datos a un proveedor de inteligencia artificial.

## Archivo

- Libro `.xlsx`, hasta 5 MB y 500 gastos por importacion. Se elige una hoja.
- Columnas obligatorias: fecha, proveedor/persona, monto y forma de pago.
- Concepto, categoria y notas son opcionales. Si no hay concepto, se conserva
  el proveedor como concepto. La categoria que falte usa la seleccion visible.
- Se reconocen encabezados comunes y se pueden asignar las columnas a mano,
  cambiar la fila del encabezado o indicar que no hay encabezados.
- Fechas reales de Excel (incluido calendario 1904), ISO y textos como
  `01-sep-26`. Los textos numericos usan dia/mes/ano por defecto; se puede
  seleccionar mes/dia/ano. La vista previa siempre muestra la fecha completa.
- Montos en MXN, positivos, con hasta dos decimales. Se conservan los centavos
  y se rechazan valores ambiguos, formulas y errores de Excel en los campos
  seleccionados. No se recalculan formulas ni se confia en su valor cacheado.
- No se admiten fotos, PDF, `.xls` antiguo, macros ni archivos cifrados en este
  importador. Un libro antiguo debe guardarse como `.xlsx` previamente.

## Revision y confirmacion

La lectura solo prepara una vista previa. No crea gastos ni proveedores.
La auditoria automatica de la solicitud HTTP puede registrar la consulta.

Las filas validas quedan seleccionadas. Los totales/subtotales se muestran
excluidos. Las filas invalidas no se pueden seleccionar. Los posibles
duplicados se comparan por fecha, proveedor, monto y forma de pago, tanto
contra Egresos activos como dentro del archivo. No se asume que una coincidencia
es necesariamente un duplicado: incluirla requiere seleccion expresa y se
advierte de nuevo al confirmar.

La confirmacion guarda solo las filas seleccionadas en una transaccion. Usa
la misma creacion de Egresos que la captura manual, incluidos proveedor,
permisos, validacion de fechas, auditoria y saldo de resguardo. Un fallo en una
fila revierte todos los gastos nuevos, proveedores y eventos del lote. Un
duplicado aparecido despues de la revision requiere otra vista previa.

No se considera que efectivo proviene de resguardo: solo el metodo explicito
`resguardo` lo descuenta. `A CREDITO` se conserva como metodo `credito`, no como
efectivo. Los gastos importados participan en los reportes y la contabilidad
operativa igual que los capturados manualmente.

## Trazabilidad y reintentos

- El servidor firma la vista previa para el usuario actual, con vigencia de una
  hora. La confirmacion no acepta filas agregadas o cambiadas fuera de ella.
- Cada fila tiene clave idempotente derivada del contenido del archivo, hoja y
  numero de fila. Reintentar la confirmacion no crea otra captura.
- Ante una respuesta incierta se conserva el mismo cuerpo de confirmacion y se
  bloquean los cambios hasta reintentar. No se guardan el archivo ni la vista
  previa en localStorage, IndexedDB o Cache Storage.
- Al volver a leer el mismo libro, sus filas importadas se marcan ya registradas.
  Una fila anulada no se reactiva por reimportarla.
- Cada gasto nuevo queda con origen `excel`, usuario creador y auditoria que
  incluye nombre del archivo, SHA-256, hoja y fila. No se sobrescriben gastos
  anteriores ni se modifica inventario.

## Validacion tecnica

`tests/test_egresos_import.py` cubre lectura, formatos, errores, permisos,
duplicados, idempotencia, reportes, proveedores y rollback con resguardo.
`tests/test_egresos_import_frontend.py` ejecuta el JS real para comprobar
seleccion, cancelacion, aislamiento de sesion y reintento de respuestas inciertas.
Las pruebas usan exclusivamente libros y bases de datos sinteticos.
