"""
Servicio de cumplimiento COFEPRIS.
NOM-251-SSA1-2009: Control de temperaturas, limpieza, inspecciones.
NOM-051: Etiquetado de productos empacados.
"""

from decimal import Decimal
from datetime import date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.cofepris import (
    RegistroTemperatura, RegistroLimpieza, ControlPlagas,
    InspeccionSanitaria, LicenciaSanitaria, AreaEstablecimiento,
    EstadoCumplimiento,
)
from app.models.inventario import Producto
from app.schemas.cofepris import (
    TemperaturaCreate, LimpiezaCreate, InspeccionCreate, ControlPlagasCreate,
)
from app.utils.nom051_helpers import (
    calcular_sellos_advertencia, calcular_leyendas_precautorias,
    generar_informacion_nutrimental,
)
from app.core.config import settings


# Rangos de temperatura por área (NOM-251)
RANGOS_TEMPERATURA = {
    AreaEstablecimiento.REFRIGERACION: (Decimal("-2"), Decimal("4")),
    AreaEstablecimiento.CONGELACION: (Decimal("-30"), Decimal("-18")),
    AreaEstablecimiento.PRODUCCION: (Decimal("15"), Decimal("35")),
    AreaEstablecimiento.ALMACEN_SECO: (Decimal("10"), Decimal("30")),
    AreaEstablecimiento.PUNTO_VENTA: (Decimal("15"), Decimal("35")),
}


# --- Temperaturas ---

def registrar_temperatura(db: Session, data: TemperaturaCreate) -> RegistroTemperatura:
    rango = RANGOS_TEMPERATURA.get(data.area, (Decimal("0"), Decimal("40")))
    temp_min, temp_max = rango
    en_rango = temp_min <= data.temperatura_registrada <= temp_max

    registro = RegistroTemperatura(
        area=data.area,
        equipo=data.equipo,
        temperatura_registrada=data.temperatura_registrada,
        temperatura_minima=temp_min,
        temperatura_maxima=temp_max,
        en_rango=en_rango,
        accion_correctiva=data.accion_correctiva,
        responsable_id=data.responsable_id,
    )

    if not en_rango and not data.accion_correctiva:
        registro.accion_correctiva = (
            f"ALERTA: Temperatura {data.temperatura_registrada}°C fuera de rango "
            f"({temp_min}°C - {temp_max}°C). Requiere acción correctiva inmediata."
        )

    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


def listar_temperaturas(
    db: Session, area: AreaEstablecimiento | None = None, limit: int = 100,
):
    query = db.query(RegistroTemperatura)
    if area:
        query = query.filter(RegistroTemperatura.area == area)
    return query.order_by(RegistroTemperatura.fecha_registro.desc()).limit(limit).all()


def alertas_temperatura(db: Session) -> list[dict]:
    """Últimos registros fuera de rango."""
    registros = db.query(RegistroTemperatura).filter(
        RegistroTemperatura.en_rango.is_(False)
    ).order_by(RegistroTemperatura.fecha_registro.desc()).limit(20).all()

    return [
        {
            "id": r.id,
            "area": r.area.value,
            "equipo": r.equipo,
            "temperatura": float(r.temperatura_registrada),
            "rango": f"{r.temperatura_minima}°C - {r.temperatura_maxima}°C",
            "fecha": r.fecha_registro.isoformat(),
            "accion": r.accion_correctiva,
        }
        for r in registros
    ]


# --- Limpieza ---

def registrar_limpieza(db: Session, data: LimpiezaCreate) -> RegistroLimpieza:
    registro = RegistroLimpieza(
        area=data.area,
        actividad=data.actividad,
        productos_utilizados=data.productos_utilizados,
        estado=EstadoCumplimiento.CONFORME,
        responsable_id=data.responsable_id,
        supervisor_id=data.supervisor_id,
        notas=data.notas,
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


def listar_limpieza(db: Session, limit: int = 100):
    return db.query(RegistroLimpieza).order_by(
        RegistroLimpieza.fecha_registro.desc()
    ).limit(limit).all()


# --- Control de plagas ---

def registrar_control_plagas(db: Session, data: ControlPlagasCreate) -> ControlPlagas:
    registro = ControlPlagas(**data.model_dump())
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


# --- Inspecciones ---

def crear_inspeccion(db: Session, data: InspeccionCreate) -> InspeccionSanitaria:
    inspeccion = InspeccionSanitaria(**data.model_dump())
    db.add(inspeccion)
    db.commit()
    db.refresh(inspeccion)
    return inspeccion


def listar_inspecciones(db: Session):
    return db.query(InspeccionSanitaria).order_by(
        InspeccionSanitaria.fecha_inspeccion.desc()
    ).all()


# --- Licencias ---

def licencias_por_vencer(db: Session, dias: int = 30) -> list[LicenciaSanitaria]:
    fecha_limite = date.today() + timedelta(days=dias)
    return db.query(LicenciaSanitaria).filter(
        and_(
            LicenciaSanitaria.fecha_vencimiento.isnot(None),
            LicenciaSanitaria.fecha_vencimiento <= fecha_limite,
            LicenciaSanitaria.estado == "vigente",
        )
    ).all()


# --- Reporte de cumplimiento ---

def generar_reporte_cumplimiento(db: Session) -> dict:
    """Genera reporte general de cumplimiento COFEPRIS."""
    hoy = date.today()
    hace_30_dias = hoy - timedelta(days=30)

    # Temperaturas fuera de rango en últimos 30 días
    temp_fuera_rango = db.query(RegistroTemperatura).filter(
        and_(
            RegistroTemperatura.en_rango.is_(False),
            RegistroTemperatura.fecha_registro >= hace_30_dias,
        )
    ).count()

    total_temperaturas = db.query(RegistroTemperatura).filter(
        RegistroTemperatura.fecha_registro >= hace_30_dias
    ).count()

    # Licencias
    licencias_vencer = licencias_por_vencer(db, 60)

    # Última inspección
    ultima_inspeccion = db.query(InspeccionSanitaria).order_by(
        InspeccionSanitaria.fecha_inspeccion.desc()
    ).first()

    # Control de plagas
    ultimo_control = db.query(ControlPlagas).order_by(
        ControlPlagas.fecha_servicio.desc()
    ).first()

    return {
        "periodo": f"{hace_30_dias} a {hoy}",
        "temperaturas": {
            "total_registros": total_temperaturas,
            "fuera_de_rango": temp_fuera_rango,
            "porcentaje_cumplimiento": (
                round((1 - temp_fuera_rango / total_temperaturas) * 100, 1)
                if total_temperaturas > 0 else 100
            ),
        },
        "licencias_por_vencer": [
            {
                "tipo": l.tipo,
                "numero": l.numero_licencia,
                "vencimiento": l.fecha_vencimiento.isoformat() if l.fecha_vencimiento else None,
            }
            for l in licencias_vencer
        ],
        "ultima_inspeccion": {
            "fecha": ultima_inspeccion.fecha_inspeccion.isoformat() if ultima_inspeccion else None,
            "tipo": ultima_inspeccion.tipo if ultima_inspeccion else None,
            "calificacion": ultima_inspeccion.calificacion_general if ultima_inspeccion else None,
        },
        "ultimo_control_plagas": {
            "fecha": ultimo_control.fecha_servicio.isoformat() if ultimo_control else None,
            "empresa": ultimo_control.empresa_fumigadora if ultimo_control else None,
            "proxima_fecha": (
                ultimo_control.proxima_fecha.isoformat()
                if ultimo_control and ultimo_control.proxima_fecha else None
            ),
        },
    }


# --- Etiquetado NOM-051 ---

def generar_etiquetado_nom051(db: Session, producto_id: int) -> dict:
    """Genera información de etiquetado NOM-051 para un producto."""
    producto = db.query(Producto).filter(Producto.id == producto_id).first()
    if not producto:
        raise ValueError("Producto no encontrado")

    sellos = calcular_sellos_advertencia(
        calorias_por_100g=producto.calorias_por_100g,
        azucar_g_por_100g=producto.azucar_g_por_100g,
        grasa_saturada_g_por_100g=producto.grasa_saturada_g_por_100g,
        grasa_trans_g_por_100g=producto.grasa_trans_g_por_100g,
        sodio_mg_por_100g=producto.sodio_mg_por_100g,
    )

    leyendas = calcular_leyendas_precautorias(
        contiene_edulcorantes=producto.contiene_edulcorantes,
        contiene_cafeina=producto.contiene_cafeina,
        sellos=sellos,
    )

    info_nutrimental = {}
    if all([producto.peso_neto_g, producto.calorias_por_100g,
            producto.azucar_g_por_100g, producto.grasa_saturada_g_por_100g,
            producto.sodio_mg_por_100g]):
        info_nutrimental = generar_informacion_nutrimental(
            peso_neto_g=producto.peso_neto_g,
            calorias_por_100g=producto.calorias_por_100g,
            azucar_g_por_100g=producto.azucar_g_por_100g,
            grasa_saturada_g_por_100g=producto.grasa_saturada_g_por_100g,
            grasa_trans_g_por_100g=producto.grasa_trans_g_por_100g,
            sodio_mg_por_100g=producto.sodio_mg_por_100g,
        )

    return {
        "producto_id": producto.id,
        "nombre_producto": producto.nombre,
        "peso_neto_g": float(producto.peso_neto_g) if producto.peso_neto_g else None,
        "informacion_nutrimental": info_nutrimental,
        "sellos_advertencia": sellos,
        "leyendas_precautorias": leyendas,
    }
