"""Importación de todos los modelos para que SQLAlchemy los registre."""

from app.models.usuario import Usuario, RolUsuario  # noqa: F401
from app.models.cliente import Cliente  # noqa: F401
from app.models.inventario import (  # noqa: F401
    CategoriaProducto, Ingrediente, Producto, Proveedor,
    LoteIngrediente, MovimientoInventario,
    UnidadMedida, CategoriaProductoEnum, TipoMovimiento, TasaIVA,
)
from app.models.receta import (  # noqa: F401
    Receta, RecetaIngrediente, OrdenProduccion, EstadoProduccion,
)
from app.models.empleado import (  # noqa: F401
    Empleado, RegistroNomina, RegistroAsistencia,
    TipoContrato, TipoJornada, Departamento,
)
from app.models.venta import (  # noqa: F401
    Venta, DetalleVenta, CorteCaja,
    MetodoPago, FormaPago, EstadoVenta,
)
from app.models.facturacion import (  # noqa: F401
    CFDIComprobante, CFDIConcepto,
    EstadoCFDI, TipoComprobante, TipoRelacion,
)
from app.models.cofepris import (  # noqa: F401
    RegistroTemperatura, RegistroLimpieza, ControlPlagas,
    InspeccionSanitaria, LicenciaSanitaria,
    TipoRegistro, EstadoCumplimiento, AreaEstablecimiento,
)
