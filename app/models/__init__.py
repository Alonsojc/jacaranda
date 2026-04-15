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
from app.models.pedido import (  # noqa: F401
    Pedido, DetallePedido, EstadoPedido, OrigenPedido,
)
from app.models.conteo_inventario import ConteoInventario  # noqa: F401
from app.models.gasto_fijo import GastoFijo  # noqa: F401
from app.models.contabilidad import (  # noqa: F401
    CuentaContable, AsientoContable, LineaAsiento, MovimientoBancario,
    TipoCuenta, NaturalezaCuenta, TipoAsiento,
)
from app.models.compras import (  # noqa: F401
    OrdenCompra, DetalleOrdenCompra, CuentaPagar, PagoCuentaPagar,
    EvaluacionProveedor, EstadoOrdenCompra, EstadoCuentaPagar,
)
from app.models.lealtad import (  # noqa: F401
    Cupon, CuponCliente, HistorialPuntos,
    NivelLealtad, TipoCupon, EstadoCupon,
)
from app.models.sucursal import (  # noqa: F401
    Sucursal, InventarioSucursal, Traspaso, DetalleTraspaso,
    EstadoTraspaso,
)
