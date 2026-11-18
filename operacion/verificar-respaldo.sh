#!/bin/sh
# Restaura el SQL de Jacaranda junto a la copia en el almacenamiento cifrado.
set -eu
umask 077

if [ "$#" -ne 2 ]; then
  echo "Uso: $0 respaldo.sql sha256_del_servidor" >&2
  exit 2
fi
dump_dir=$(cd "$(dirname "$1")" && pwd -P)
dump="$dump_dir/$(basename "$1")"
if command -v sha256sum >/dev/null 2>&1; then
  checksum=$(sha256sum < "$dump")
else
  checksum=$(shasum -a 256 < "$dump")
fi
actual=${checksum%% *}
if [ "$actual" != "$2" ]; then
  echo "SHA-256 distinto del registrado al crear el respaldo." >&2
  exit 1
fi

pg_ctl_path=$(command -v pg_ctl) || { echo "Falta pg_ctl en el PATH." >&2; exit 1; }
pg_bin=$(dirname "$pg_ctl_path")
data=$(mktemp -d "$dump_dir/.prueba-pg.XXXXXX")
socket=$(mktemp -d /tmp/jacaranda-pg.XXXXXX)
local_pg() {
  env -i PATH="$pg_bin:/usr/bin:/bin" LC_ALL=C "$@"
}
limpiar() {
  if [ -f "$data/cluster/postmaster.pid" ]; then
    local_pg pg_ctl -D "$data/cluster" -m fast -w stop >/dev/null || return 1
  fi
  rm -rf -- "$data" "$socket"
}
trap limpiar EXIT
trap 'exit 1' HUP INT TERM

local_pg initdb -D "$data/cluster" -U postgres --encoding=UTF8 --locale=C \
  --auth-local=trust --auth-host=reject >/dev/null
local_pg pg_ctl -D "$data/cluster" -l "$data/postgres.log" \
  -o "-k $socket -c listen_addresses='' -c unix_socket_permissions=0700" -w start >/dev/null

psql_local() {
  local_pg psql -X -w -h "$socket" -U postgres -d postgres -v ON_ERROR_STOP=1 "$@"
}
psql_local --single-transaction -f "$dump" >/dev/null
psql_local -qAt -f "$(dirname "$0")/conciliar-region.sql"
echo "Restauración local completada. SHA-256 $actual"
