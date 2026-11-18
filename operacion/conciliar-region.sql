-- Huellas de las tablas operativas con el mismo formato en origen y en la copia.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL TIME ZONE 'UTC';
SET LOCAL search_path TO public, pg_catalog;

SELECT format(
  $consulta$
    SELECT %L, count(*),
           encode(sha256(coalesce(string_agg(huella, ''::bytea ORDER BY huella), ''::bytea)), 'hex')
    FROM (
      SELECT sha256(convert_to(to_jsonb(fila)::text, 'UTF8')) AS huella
      FROM public.%I AS fila
    ) AS filas
  $consulta$,
  tabla, tabla
)
FROM unnest(ARRAY[
  'alembic_version', 'cortes_caja', 'detalles_pedido', 'detalles_venta',
  'ingredientes', 'movimientos_inventario', 'pagos_venta', 'pedidos', 'productos', 'ventas'
]) AS tablas(tabla)
ORDER BY tabla
\gexec
COMMIT;
