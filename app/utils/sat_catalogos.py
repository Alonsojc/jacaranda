"""
Catálogos del SAT para CFDI 4.0.
Claves de productos/servicios, unidades, régimen fiscal, uso CFDI, etc.
"""

# Claves de producto/servicio SAT relevantes para panadería
CLAVES_PRODUCTO_SERVICIO = {
    "50181900": "Pan y productos de panadería",
    "50181901": "Pan blanco",
    "50181902": "Pan de dulce",
    "50181903": "Pan integral",
    "50181904": "Pasteles y pastelería",
    "50192100": "Galletas",
    "50202300": "Bebidas no alcohólicas",
    "50171500": "Harinas y productos de molienda",
    "50161500": "Chocolates y confitería",
    "90101500": "Servicios de catering",  # Para pedidos especiales
}

# Claves de unidad SAT
CLAVES_UNIDAD = {
    "H87": "Pieza",
    "KGM": "Kilogramo",
    "GRM": "Gramo",
    "LTR": "Litro",
    "MLT": "Mililitro",
    "XBX": "Caja",
    "XBG": "Bolsa",
    "XSA": "Saco",
    "E48": "Unidad de servicio",
    "ACT": "Actividad",
}

# Régimen fiscal
REGIMENES_FISCALES = {
    "601": "General de Ley Personas Morales",
    "603": "Personas Morales con Fines no Lucrativos",
    "605": "Sueldos y Salarios e Ingresos Asimilados a Salarios",
    "606": "Arrendamiento",
    "607": "Régimen de Enajenación o Adquisición de Bienes",
    "608": "Demás ingresos",
    "610": "Residentes en el Extranjero sin Establecimiento Permanente en México",
    "611": "Ingresos por Dividendos (socios y accionistas)",
    "612": "Personas Físicas con Actividades Empresariales y Profesionales",
    "614": "Ingresos por intereses",
    "616": "Sin obligaciones fiscales",
    "620": "Sociedades Cooperativas de Producción",
    "621": "Incorporación Fiscal",
    "622": "Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras",
    "623": "Opcional para Grupos de Sociedades",
    "624": "Coordinados",
    "625": "Régimen de las Actividades Empresariales con ingresos a través de Plataformas Tecnológicas",
    "626": "Régimen Simplificado de Confianza",
}

# Uso CFDI
USOS_CFDI = {
    "G01": "Adquisición de mercancías",
    "G02": "Devoluciones, descuentos o bonificaciones",
    "G03": "Gastos en general",
    "I01": "Construcciones",
    "I02": "Mobiliario y equipo de oficina por inversiones",
    "I03": "Equipo de transporte",
    "I04": "Equipo de cómputo y accesorios",
    "I05": "Dados, troqueles, moldes, matrices y herramental",
    "I06": "Comunicaciones telefónicas",
    "I07": "Comunicaciones satelitales",
    "I08": "Otra maquinaria y equipo",
    "D01": "Honorarios médicos, dentales y gastos hospitalarios",
    "D02": "Gastos médicos por incapacidad o discapacidad",
    "D03": "Gastos funerales",
    "D04": "Donativos",
    "D05": "Intereses reales efectivamente pagados por créditos hipotecarios",
    "D06": "Aportaciones voluntarias al SAR",
    "D07": "Primas por seguros de gastos médicos",
    "D08": "Gastos de transportación escolar obligatoria",
    "D09": "Depósitos en cuentas para el ahorro",
    "D10": "Pagos por servicios educativos",
    "S01": "Sin efectos fiscales",
    "CP01": "Pagos",
    "CN01": "Nómina",
}

# Formas de pago SAT
FORMAS_PAGO = {
    "01": "Efectivo",
    "02": "Cheque nominativo",
    "03": "Transferencia electrónica de fondos",
    "04": "Tarjeta de crédito",
    "05": "Monedero electrónico",
    "06": "Dinero electrónico",
    "08": "Vales de despensa",
    "12": "Dación en pago",
    "13": "Pago por subrogación",
    "14": "Pago por consignación",
    "15": "Condonación",
    "17": "Compensación",
    "23": "Novación",
    "24": "Confusión",
    "25": "Remisión de deuda",
    "26": "Prescripción o caducidad",
    "27": "A satisfacción del acreedor",
    "28": "Tarjeta de débito",
    "29": "Tarjeta de servicios",
    "30": "Aplicación de anticipos",
    "31": "Intermediario pagos",
    "99": "Por definir",
}

# Motivos de cancelación CFDI
MOTIVOS_CANCELACION = {
    "01": "Comprobante emitido con errores con relación",
    "02": "Comprobante emitido con errores sin relación",
    "03": "No se llevó a cabo la operación",
    "04": "Operación nominativa relacionada en una factura global",
}

# Objeto de impuesto
OBJETOS_IMPUESTO = {
    "01": "No objeto de impuesto",
    "02": "Sí objeto de impuesto",
    "03": "Sí objeto del impuesto y no obligado al desglose",
    "04": "Sí objeto del impuesto y no causa impuesto",
}


def obtener_descripcion_regimen(clave: str) -> str:
    return REGIMENES_FISCALES.get(clave, "Régimen no encontrado")


def obtener_descripcion_uso_cfdi(clave: str) -> str:
    return USOS_CFDI.get(clave, "Uso CFDI no encontrado")


def obtener_descripcion_forma_pago(clave: str) -> str:
    return FORMAS_PAGO.get(clave, "Forma de pago no encontrada")


def obtener_descripcion_producto(clave: str) -> str:
    return CLAVES_PRODUCTO_SERVICIO.get(clave, "Producto no encontrado")


def obtener_descripcion_unidad(clave: str) -> str:
    return CLAVES_UNIDAD.get(clave, "Unidad no encontrada")
