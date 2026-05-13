#!/usr/bin/env python3
"""
Valida o aplica la migración de costos generada por prepare_costing_migration.py.

Por seguridad, este script corre en modo dry-run por defecto. Solo escribe en la
base de datos si se pasa --apply, y aun así solo importa filas marcadas como
importar=si.

Uso:
    python scripts/import_costing_catalog.py --input-dir migration/costing_import
    python scripts/import_costing_catalog.py --input-dir migration/costing_import --apply
"""

from __future__ import annotations

import argparse
import csv
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.database import SessionLocal
import app.models  # noqa: F401  # Registra modelos en SQLAlchemy.
from app.models.inventario import (
    CategoriaProducto,
    CategoriaProductoEnum,
    Ingrediente,
    Producto,
    Proveedor,
    TasaIVA,
    UnidadMedida,
)
from app.models.receta import Receta, RecetaIngrediente


DEFAULT_INPUT_DIR = Path("migration/costing_import")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def yes(value: str | None) -> bool:
    return (value or "").strip().lower() in {"si", "sí", "s", "yes", "true", "1"}


def clean(value: Any) -> str:
    return ("" if value is None else str(value)).strip()


def as_decimal(value: str | None, default: Decimal | None = None) -> Decimal | None:
    raw = clean(value)
    if not raw:
        return default
    raw = raw.replace("$", "").replace(",", "").replace("%", "")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return default


def as_int(value: str | None) -> int | None:
    raw = clean(value)
    if not raw:
        return None
    try:
        return int(Decimal(raw))
    except (InvalidOperation, ValueError):
        return None


def parse_unit(value: str) -> UnidadMedida | None:
    try:
        return UnidadMedida(clean(value))
    except ValueError:
        return None


def parse_iva(value: str) -> TasaIVA:
    raw = clean(value).lower()
    if raw in {"16", "16%", "0.16", "tasa_16"}:
        return TasaIVA.TASA_16
    if raw in {"exento", "exenta"}:
        return TasaIVA.EXENTO
    return TasaIVA.TASA_0


def category_type(value: str) -> CategoriaProductoEnum:
    raw = clean(value).lower()
    if raw == "pasteleria":
        return CategoriaProductoEnum.PASTELERIA
    if raw == "galletas":
        return CategoriaProductoEnum.GALLETAS
    if raw == "pan_dulce":
        return CategoriaProductoEnum.PAN_DULCE
    if raw == "pan_salado":
        return CategoriaProductoEnum.PAN_SALADO
    if raw == "reposteria":
        return CategoriaProductoEnum.REPOSTERIA
    return CategoriaProductoEnum.OTROS


def find_by_name(db: Session, model, name: str):
    return db.query(model).filter(func.lower(model.nombre) == clean(name).lower()).first()


def upsert_provider(db: Session, name: str) -> Proveedor | None:
    name = clean(name)
    if not name:
        return None
    provider = find_by_name(db, Proveedor, name)
    if provider:
        return provider
    provider = Proveedor(nombre=name)
    db.add(provider)
    db.flush()
    return provider


def upsert_category(db: Session, name: str) -> CategoriaProducto:
    display = clean(name) or "otros"
    category = find_by_name(db, CategoriaProducto, display)
    if category:
        return category
    category = CategoriaProducto(
        nombre=display,
        tipo=category_type(display),
        descripcion="Importado desde Excel de costos",
    )
    db.add(category)
    db.flush()
    return category


def validate_rows(input_dir: Path) -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    counts: dict[str, int] = {}

    ingredientes = read_csv(input_dir / "ingredientes.csv")
    productos = read_csv(input_dir / "productos.csv")
    recetas = read_csv(input_dir / "recetas.csv")
    receta_ingredientes = read_csv(input_dir / "receta_ingredientes.csv")
    empaques = read_csv(input_dir / "empaques.csv")
    proveedores = read_csv(input_dir / "proveedores.csv")

    counts["ingredientes_total"] = len(ingredientes)
    counts["ingredientes_importar"] = sum(yes(row.get("importar")) for row in ingredientes)
    counts["productos_total"] = len(productos)
    counts["productos_importar"] = sum(yes(row.get("importar")) for row in productos)
    counts["recetas_total"] = len(recetas)
    counts["recetas_importar"] = sum(yes(row.get("importar")) for row in recetas)
    counts["receta_ingredientes_total"] = len(receta_ingredientes)
    counts["empaques_total"] = len(empaques)
    counts["empaques_importar"] = sum(yes(row.get("importar")) for row in empaques)
    counts["proveedores_total"] = len(proveedores)
    counts["proveedores_importar"] = sum(yes(row.get("importar")) for row in proveedores)

    ingredient_names = {
        clean(row.get("nombre")).lower()
        for row in ingredientes
        if yes(row.get("importar")) and clean(row.get("nombre"))
    }
    inventory_names = ingredient_names | {
        clean(row.get("nombre")).lower()
        for row in empaques
        if yes(row.get("importar")) and clean(row.get("nombre"))
    }
    product_codes = {clean(row.get("codigo")) for row in productos if clean(row.get("codigo"))}
    import_product_codes = {
        clean(row.get("codigo"))
        for row in productos
        if yes(row.get("importar")) and clean(row.get("codigo"))
    }

    for index, row in enumerate(ingredientes, start=2):
        if not clean(row.get("nombre")):
            errors.append(f"ingredientes.csv:{index} falta nombre")
        if parse_unit(clean(row.get("unidad_medida"))) is None:
            errors.append(f"ingredientes.csv:{index} unidad inválida: {row.get('unidad_medida')}")
        if as_decimal(row.get("costo_unitario")) is None:
            errors.append(f"ingredientes.csv:{index} costo_unitario inválido")

    for index, row in enumerate(empaques, start=2):
        if yes(row.get("importar")) and not clean(row.get("nombre")):
            errors.append(f"empaques.csv:{index} falta nombre")
        if yes(row.get("importar")) and parse_unit(clean(row.get("unidad_medida"))) is None:
            errors.append(f"empaques.csv:{index} unidad inválida: {row.get('unidad_medida')}")

    for index, row in enumerate(productos, start=2):
        if not yes(row.get("importar")):
            continue
        if not clean(row.get("codigo")):
            errors.append(f"productos.csv:{index} falta codigo")
        if not clean(row.get("nombre")):
            errors.append(f"productos.csv:{index} falta nombre")
        price = as_decimal(row.get("precio_unitario"))
        if price is None or price < 0:
            errors.append(f"productos.csv:{index} precio_unitario inválido")
        cafe_price = as_decimal(row.get("precio_cafeteria"), Decimal("0"))
        if cafe_price is not None and cafe_price < 0:
            errors.append(f"productos.csv:{index} precio_cafeteria inválido")
        caja = clean(row.get("caja"))
        if caja and caja.lower() not in inventory_names:
            errors.append(f"productos.csv:{index} caja no está marcada para importar en ingredientes/empaques: {caja}")

    for index, row in enumerate(recetas, start=2):
        if not yes(row.get("importar")):
            continue
        code = clean(row.get("producto_codigo"))
        if code not in product_codes:
            errors.append(f"recetas.csv:{index} producto_codigo no existe: {code}")
        if code not in import_product_codes:
            errors.append(f"recetas.csv:{index} producto {code} no está marcado importar=si")
        rendimiento = as_decimal(row.get("rendimiento"))
        if rendimiento is None or rendimiento <= 0:
            errors.append(f"recetas.csv:{index} rendimiento debe ser mayor a cero")

    recipe_codes = {clean(row.get("producto_codigo")) for row in recetas if yes(row.get("importar"))}
    for index, row in enumerate(receta_ingredientes, start=2):
        code = clean(row.get("producto_codigo"))
        if code not in recipe_codes:
            continue
        ingredient = clean(row.get("ingrediente_nombre"))
        if ingredient.lower() not in ingredient_names:
            errors.append(f"receta_ingredientes.csv:{index} ingrediente no existe: {ingredient}")
        qty = as_decimal(row.get("cantidad"))
        if qty is None or qty <= 0:
            errors.append(f"receta_ingredientes.csv:{index} cantidad debe ser mayor a cero")

    return errors, counts


def apply_import(db: Session, input_dir: Path) -> dict[str, int]:
    stats = {
        "proveedores": 0,
        "ingredientes": 0,
        "empaques": 0,
        "productos": 0,
        "recetas": 0,
    }

    for row in read_csv(input_dir / "proveedores.csv"):
        if not yes(row.get("importar")) or not clean(row.get("nombre")):
            continue
        provider = upsert_provider(db, row["nombre"])
        if provider:
            provider.rfc = clean(row.get("rfc")) or provider.rfc
            provider.contacto = clean(row.get("contacto")) or provider.contacto
            provider.telefono = clean(row.get("telefono")) or provider.telefono
            provider.email = clean(row.get("email")) or provider.email
            provider.direccion = clean(row.get("direccion")) or provider.direccion
            stats["proveedores"] += 1

    for file_name, stat_key in (("ingredientes.csv", "ingredientes"), ("empaques.csv", "empaques")):
        for row in read_csv(input_dir / file_name):
            if not yes(row.get("importar")) or not clean(row.get("nombre")):
                continue
            provider = upsert_provider(db, row.get("proveedor", ""))
            ingredient = find_by_name(db, Ingrediente, row["nombre"])
            unit = parse_unit(clean(row.get("unidad_medida"))) or UnidadMedida.PIEZA
            if not ingredient:
                ingredient = Ingrediente(nombre=clean(row["nombre"]), unidad_medida=unit)
                db.add(ingredient)
            ingredient.unidad_medida = unit
            ingredient.costo_unitario = as_decimal(row.get("costo_unitario"), Decimal("0")) or Decimal("0")
            ingredient.stock_actual = as_decimal(row.get("stock_actual"), Decimal("0")) or Decimal("0")
            ingredient.stock_minimo = as_decimal(row.get("stock_minimo"), Decimal("0")) or Decimal("0")
            ingredient.proveedor = provider
            ingredient.es_alergeno = yes(row.get("es_alergeno"))
            ingredient.tipo_alergeno = clean(row.get("tipo_alergeno")) or None
            ingredient.requiere_refrigeracion = yes(row.get("requiere_refrigeracion"))
            ingredient.descripcion = clean(row.get("notas")) or ingredient.descripcion
            ingredient.activo = True
            stats[stat_key] += 1

    db.flush()

    for row in read_csv(input_dir / "productos.csv"):
        if not yes(row.get("importar")) or not clean(row.get("codigo")):
            continue
        category = upsert_category(db, row.get("categoria", "otros"))
        product = db.query(Producto).filter(Producto.codigo == clean(row["codigo"])).first()
        caja = clean(row.get("caja"))
        caja_ingrediente = find_by_name(db, Ingrediente, caja) if caja else None
        if not product:
            product = Producto(
                codigo=clean(row["codigo"]),
                nombre=clean(row.get("nombre")),
                precio_unitario=as_decimal(row.get("precio_unitario"), Decimal("0")) or Decimal("0"),
            )
            db.add(product)
        product.nombre = clean(row.get("nombre")) or product.nombre
        product.categoria = category
        product.precio_unitario = as_decimal(row.get("precio_unitario"), product.precio_unitario) or Decimal("0")
        product.precio_cafeteria = as_decimal(row.get("precio_cafeteria"))
        product.costo_produccion = as_decimal(row.get("costo_produccion"), Decimal("0")) or Decimal("0")
        product.stock_actual = as_decimal(row.get("stock_actual"), Decimal("0")) or Decimal("0")
        product.stock_minimo = as_decimal(row.get("stock_minimo"), Decimal("0")) or Decimal("0")
        product.unidad_medida = UnidadMedida.PIEZA
        product.caja_ingrediente = caja_ingrediente
        product.caja_cantidad = as_decimal(row.get("caja_cantidad"), Decimal("1")) or Decimal("1")
        product.tasa_iva = parse_iva(row.get("tasa_iva", "0"))
        product.activo = True
        stats["productos"] += 1

    db.flush()

    recipe_ingredients = read_csv(input_dir / "receta_ingredientes.csv")
    recipe_ingredients_by_code: dict[str, list[dict[str, str]]] = {}
    for line in recipe_ingredients:
        recipe_ingredients_by_code.setdefault(clean(line.get("producto_codigo")), []).append(line)

    for row in read_csv(input_dir / "recetas.csv"):
        if not yes(row.get("importar")):
            continue
        product = db.query(Producto).filter(Producto.codigo == clean(row.get("producto_codigo"))).first()
        if not product:
            raise ValueError(f"Producto no encontrado para receta: {row.get('producto_codigo')}")

        recipe = db.query(Receta).filter(Receta.producto_id == product.id).first()
        if not recipe:
            recipe = Receta(producto=product, nombre=clean(row.get("receta_nombre")) or product.nombre)
            db.add(recipe)
        recipe.nombre = clean(row.get("receta_nombre")) or product.nombre
        recipe.rendimiento = as_decimal(row.get("rendimiento"), Decimal("1")) or Decimal("1")
        recipe.tiempo_preparacion_min = as_int(row.get("tiempo_preparacion_min"))
        recipe.tiempo_horneado_min = as_int(row.get("tiempo_horneado_min"))
        recipe.temperatura_horneado_c = as_int(row.get("temperatura_horneado_c"))
        recipe.descripcion = clean(row.get("notas_revision")) or recipe.descripcion
        recipe.activo = True
        recipe.ingredientes.clear()

        for line in recipe_ingredients_by_code.get(clean(row.get("producto_codigo")), []):
            ingredient = find_by_name(db, Ingrediente, line.get("ingrediente_nombre", ""))
            if not ingredient:
                raise ValueError(
                    f"Ingrediente no encontrado para {recipe.nombre}: {line.get('ingrediente_nombre')}"
                )
            recipe.ingredientes.append(RecetaIngrediente(
                ingrediente=ingredient,
                cantidad=as_decimal(line.get("cantidad"), Decimal("0")) or Decimal("0"),
                notas=clean(line.get("notas")) or None,
            ))
        stats["recetas"] += 1

    db.commit()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida/aplica CSVs de migración de costos.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--apply", action="store_true", help="Escribe cambios en la base de datos.")
    args = parser.parse_args()

    if not args.input_dir.exists():
        print(f"No existe el directorio: {args.input_dir}", file=sys.stderr)
        return 1

    errors, counts = validate_rows(args.input_dir)
    print("Resumen de migración:")
    for key in sorted(counts):
        print(f"- {key}: {counts[key]}")

    if errors:
        print("\nErrores de validación:")
        for error in errors[:100]:
            print(f"- {error}")
        if len(errors) > 100:
            print(f"- ... {len(errors) - 100} errores más")
        print("\nNo se aplicaron cambios.")
        return 1 if args.apply else 0

    if not args.apply:
        print("\nDry-run OK. No se escribió en la base de datos.")
        print("Marca filas con importar=si y usa --apply cuando quieras aplicar.")
        return 0

    db = SessionLocal()
    try:
        stats = apply_import(db, args.input_dir)
    except Exception as exc:
        db.rollback()
        print(f"Error aplicando migración: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print("\nMigración aplicada:")
    for key, value in stats.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
