# Migración de costos Jacaranda

Generado automáticamente desde `Ingredientes y Costos.xlsx`.

## Archivos

- `ingredientes.csv`: materias primas detectadas desde la hoja Ingredientes.
- `insumos_operativos.csv`: insumos/gastos operativos detectados, para revisar antes de meterlos a Egresos o proveedores.
- `empaques.csv`: empaques/cajas detectados o sugeridos para ligar a productos. Los detectados con costo real quedan en `importar=si`; los sugeridos sin costo quedan en `importar=no`.
- `productos.csv`: productos/recetas detectados desde las hojas de costeo. Vienen con `importar=no` hasta que los revises.
- `recetas.csv`: cabeceras de recetas. Vienen con `importar=no` hasta que los revises.
- `receta_ingredientes.csv`: ingredientes por receta.
- `revision_pendiente.csv`: cosas que el Excel no deja migrar a ciegas.
- `proveedores.csv`: plantilla para llenar proveedores y usarlos después en ingredientes/egresos.

## Conteo

- Ingredientes: 104
- Insumos operativos: 1
- Empaques: 10
- Productos sugeridos: 46
- Recetas sugeridas: 46
- Líneas de receta: 458
- Revisiones pendientes: 27

## Flujo recomendado

1. No edites el Excel original para importar. Revisa y corrige estos CSVs.
2. Abre primero `revision_pendiente.csv`.
3. Revisa unidades, nombres duplicados, precios, rendimientos y presentaciones.
4. En cada CSV cambia `importar=no` a `importar=si` solo en filas confiables.
5. Si quieres una primera carga conservadora, deja importables solo `ingredientes.csv` y los empaques con costo real; productos/recetas deben seguir en `importar=no`.
6. Para importar una receta, marca también su producto correspondiente en `productos.csv` con el mismo `codigo`.
7. Corre validación sin escribir:

```bash
python scripts/import_costing_catalog.py --input-dir migration/costing_import
```

8. Cuando la validación esté limpia y tengas backup reciente, aplica:

```bash
python scripts/import_costing_catalog.py --input-dir migration/costing_import --apply
```

No importes productos/recetas sin revisar porque el Excel mezcla presentaciones, cajas, recetas auxiliares y fórmulas. Las filas pendientes no son fallas: son puntos donde el script prefirió detenerse antes de adivinar.
