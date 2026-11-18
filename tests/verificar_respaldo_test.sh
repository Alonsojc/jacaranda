#!/bin/sh
set -eu
umask 077
prueba=$(mktemp -d)
trap 'rm -rf -- "$prueba"' EXIT
dump="$prueba/ejemplo.sql"
cat > "$dump" <<'SQL'
CREATE TABLE ventas (id integer PRIMARY KEY);
CREATE TABLE alembic_version (version_num text);
CREATE TABLE cortes_caja (LIKE ventas);
CREATE TABLE detalles_pedido (LIKE ventas);
CREATE TABLE detalles_venta (LIKE ventas);
CREATE TABLE ingredientes (LIKE ventas);
CREATE TABLE movimientos_inventario (LIKE ventas);
CREATE TABLE pagos_venta (LIKE ventas);
CREATE TABLE pedidos (LIKE ventas);
CREATE TABLE productos (LIKE ventas);
INSERT INTO ventas VALUES (1), (2);
SQL
checksum=$(openssl dgst -sha256 "$dump")
sha=${checksum##* }
if sh operacion/verificar-respaldo.sh "$dump" incorrecto >/dev/null 2>&1; then
  echo "Se aceptó un hash incorrecto" >&2
  exit 1
fi
sh operacion/verificar-respaldo.sh "$dump" "$sha" > "$prueba/resultado"
grep -Eq '^ventas\|2\|[[:xdigit:]]{64}$' "$prueba/resultado"
test "$(grep -Ec '\|[[:xdigit:]]{64}$' "$prueba/resultado")" -eq 10
