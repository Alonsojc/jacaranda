"""Rehearse TEST orders in a fresh in-memory POS; never deploy or post to Uber."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-id", type=UUID, help="Optional read-only canonical TEST order lookup.")
    parser.add_argument("--report", type=Path, help="Write a new JSON report; never overwrite an existing file.")
    args = parser.parse_args()
    if args.report and args.report.exists():
        parser.error("Report exists. Choose a new path; previous evidence is preserved.")
    # Set before importing configuration or models, even under railway run.
    os.environ["DATABASE_URL"] = "sqlite://"
    os.environ["JACARANDA_RUNTIME"] = "uber-pos-rehearsal"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    import app.models  # noqa: F401
    from app.core.database import Base
    from app.models.auditoria import LogAuditoria
    from app.models.inventario import Ingrediente, MovimientoInventario, Producto, UnidadMedida
    from app.models.usuario import RolUsuario, Usuario
    from app.models.venta import DetalleVenta, PagoVenta, Venta
    from app.services import uber_pos_sandbox_service as pos
    from app.services.venta_service import resumen_corte_caja

    engine = create_engine("sqlite://")
    report = {"source": "canonical_test_get" if args.order_id else "synthetic_fixture",
              "database": "fresh SQLite in memory", "real_store_enabled": False,
              "remote_mutations": 0, "real_payments": 0, "at": datetime.now(timezone.utc).isoformat()}
    code = 0
    try:
        with Session(bind=engine) as db:
            pos.validate_database(db)
            Base.metadata.create_all(engine)
            operator = Usuario(nombre="Operador ficticio", email="uber-test@example.invalid",
                               hashed_password="not-a-login-credential", rol=RolUsuario.ADMINISTRADOR)
            box = Ingrediente(nombre="Caja ficticia", unidad_medida=UnidadMedida.CAJA, es_empaque=True,
                              stock_actual=Decimal(20), costo_unitario=Decimal(1))
            db.add_all([operator, box])
            db.flush()
            products = [Producto(codigo="UBER-ENSAYO-" + str(index), nombre=name,
                                 precio_unitario=Decimal(99), precio_uber_eats=Decimal(88), stock_actual=Decimal(10),
                                 caja_ingrediente_id=box.id, caja_cantidad=Decimal(1))
                        for index, name in enumerate(("Brownie de ensayo", "Galleta de ensayo"))]
            db.add_all(products)
            db.commit()
            mapping = {"jacaranda-sandbox-brownie": products[0].id, "jacaranda-sandbox-cookie": products[1].id}
            try:
                if args.order_id:
                    payload, observed = pos.read_test_order(db, args.order_id)
                else:
                    payload = json.loads((Path(__file__).parent / "fixtures/uber_pos_order.json").read_text())
                    observed = datetime.now(timezone.utc)
                first = pos.import_order(db, payload, mapping, operator.id, client_id=pos.TEST_CLIENT_ID,
                                         retrieved_at=observed, reviewed=True)
                stocks = [product.stock_actual for product in products]
                movements = db.query(MovimientoInventario).count()
                repeated = pos.import_order(db, payload, mapping, operator.id, client_id=pos.TEST_CLIENT_ID,
                                            retrieved_at=observed, reviewed=True)
                assert repeated["repetida"] and repeated["venta_id"] == first["venta_id"]
                assert stocks == [product.stock_actual for product in products]
                assert movements == db.query(MovimientoInventario).count()
                cut = resumen_corte_caja(db)
                assert cut["total_ventas"] == 0 and cut["efectivo_esperado_base"] == 0
                report.update(status="passed", order_id=payload["order"]["id"], first=first, replay=repeated,
                              sale_state=db.get(Venta, first["venta_id"]).estado.value,
                              stock_before=[10, 10], stock_after=stocks, packaging_before=20, packaging_after=box.stock_actual,
                              sales=db.query(Venta).count(), lines=db.query(DetalleVenta).count(), payments=db.query(PagoVenta).count(),
                              stock_movements=movements, audit_events=db.query(LogAuditoria).count(),
                              expected_cash=cut["efectivo_esperado_base"], cash_register_sales=cut["total_ventas"],
                              ticket=pos.rehearsal_ticket(db, first["venta_id"]))
            except pos.RehearsalError as exc:
                db.rollback()
                report.update(status="blocked_without_writes", reason=str(exc), sales=db.query(Venta).count(),
                              stock_movements=db.query(MovimientoInventario).count())
                code = 2
    finally:
        engine.dispose()
    encoded = json.dumps(report, ensure_ascii=True, indent=2, default=str) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x") as output:
            output.write(encoded)
    print(encoded, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
