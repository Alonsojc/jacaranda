"""Router principal que agrega todos los módulos."""

from fastapi import APIRouter

from app.api.routes import (
    auth, inventario, recetas, punto_de_venta,
    clientes, facturacion, empleados, cofepris, reportes,
)

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["Autenticación"])
router.include_router(inventario.router, prefix="/inventario", tags=["Inventario"])
router.include_router(recetas.router, prefix="/recetas", tags=["Recetas y Producción"])
router.include_router(punto_de_venta.router, prefix="/punto-de-venta", tags=["Punto de Venta"])
router.include_router(clientes.router, prefix="/clientes", tags=["Clientes"])
router.include_router(facturacion.router, prefix="/facturacion", tags=["Facturación CFDI 4.0"])
router.include_router(empleados.router, prefix="/empleados", tags=["Empleados y Nómina"])
router.include_router(cofepris.router, prefix="/cofepris", tags=["COFEPRIS / NOM-051"])
router.include_router(reportes.router, prefix="/reportes", tags=["Reportes e Impuestos"])
