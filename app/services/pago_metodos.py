"""Helpers para separar forma SAT y canal operativo de pago."""

from app.models.venta import MetodoPago, TerminalPago


SAT_FORMA_PAGO = {
    MetodoPago.EFECTIVO: "01 - Efectivo",
    MetodoPago.CHEQUE: "02 - Cheque nominativo",
    MetodoPago.TRANSFERENCIA: "03 - Transferencia electronica de fondos",
    MetodoPago.TARJETA_CREDITO: "04 - Tarjeta de credito",
    MetodoPago.TARJETA_DEBITO: "28 - Tarjeta de debito",
    MetodoPago.VALES_DESPENSA: "08 - Vales de despensa",
    MetodoPago.POR_DEFINIR: "99 - Por definir",
}

CANAL_PAGO_LABELS = {
    "efectivo": "Efectivo",
    "clip": "CLIP",
    "bbva": "BBVA",
    "transferencia": "Transferencia",
    "tarjeta": "Otra tarjeta",
    "otro": "Otro",
}


def normalizar_metodo_terminal(
    metodo: MetodoPago,
    terminal: TerminalPago | None,
) -> MetodoPago:
    """Corrige payloads historicos donde una terminal tarjeta llegaba como SAT 03."""
    if terminal == TerminalPago.BBVA and metodo == MetodoPago.TRANSFERENCIA:
        return MetodoPago.TARJETA_DEBITO
    if terminal == TerminalPago.CLIP and metodo == MetodoPago.TRANSFERENCIA:
        return MetodoPago.TARJETA_CREDITO
    return metodo


def validar_metodo_terminal(metodo: MetodoPago, terminal: TerminalPago | None) -> None:
    metodo = normalizar_metodo_terminal(metodo, terminal)
    if terminal in (TerminalPago.CLIP, TerminalPago.BBVA) and metodo not in (
        MetodoPago.TARJETA_CREDITO,
        MetodoPago.TARJETA_DEBITO,
    ):
        raise ValueError("CLIP/BBVA deben registrarse como tarjeta SAT 04 o 28")
    if metodo == MetodoPago.TRANSFERENCIA and terminal in (TerminalPago.CLIP, TerminalPago.BBVA):
        raise ValueError("Transferencia SAT 03 no debe usarse para pagos con terminal")


def canal_pago(metodo: MetodoPago, terminal: TerminalPago | None = None) -> str:
    metodo = normalizar_metodo_terminal(metodo, terminal)
    if metodo == MetodoPago.EFECTIVO:
        return "efectivo"
    if metodo == MetodoPago.TRANSFERENCIA:
        return "transferencia"
    if terminal == TerminalPago.CLIP:
        return "clip"
    if terminal == TerminalPago.BBVA:
        return "bbva"
    if metodo in (MetodoPago.TARJETA_CREDITO, MetodoPago.TARJETA_DEBITO):
        return "tarjeta"
    return "otro"


def etiqueta_canal_pago(metodo: MetodoPago, terminal: TerminalPago | None = None) -> str:
    return CANAL_PAGO_LABELS.get(canal_pago(metodo, terminal), "Otro")


def proveedor_por_terminal(terminal: TerminalPago | None) -> str | None:
    if terminal == TerminalPago.CLIP:
        return "clip"
    if terminal == TerminalPago.BBVA:
        return "bbva"
    return None


def descripcion_sat(metodo: MetodoPago) -> str:
    return SAT_FORMA_PAGO.get(metodo, metodo.value)
