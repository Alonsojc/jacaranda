"""Loopback-only visual fixtures. No database, credentials, or outbound requests."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ASSETS = Path(__file__).resolve().parents[1] / "app" / "sandbox_static"
ORDER_ID = str(uuid5(NAMESPACE_URL, "jacaranda-local-order-preview"))
EVENT_ID = str(uuid5(NAMESPACE_URL, "jacaranda-local-event-preview"))
ACCESS = "local-fixture-only"
state = {"scenario": "empty", "commands": 0, "reads": 0}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, data, status=200):
        content = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        assets = {"/": ("index.html", "text/html"), "/sandbox.js": ("sandbox.js", "text/javascript"),
                  "/attention.js": ("attention.js", "text/javascript"), "/sandbox.css": ("sandbox.css", "text/css"),
                  "/favicon.svg": ("favicon.svg", "image/svg+xml")}
        if path in assets:
            name, content_type = assets[path]
            content = (ASSETS / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            return
        if path == "/fixture/state":
            return self.reply(state)
        if self.headers.get("Authorization") != "Bearer " + ACCESS:
            return self.reply({"detail": "Acceso local requerido"}, 401)
        state["reads"] += 1
        if path == "/sandbox/estado":
            return self.reply({"entorno": "sandbox", "tienda_real_activada": False})
        if path.endswith("/atencion"):
            if state["scenario"] == "unavailable":
                return self.reply({"detail": "Servicio de pruebas no disponible"}, 503)
            kind = "verificar" if state["scenario"] == "changed" else "nuevo"
            rows = [] if state["scenario"] == "empty" else [{
                "pedido_id": ORDER_ID, "event_id": EVENT_ID, "tipo": kind, "recibido_en": "2026-10-24T20:00:00Z",
            }]
            return self.reply({"entorno": "sandbox", "total": len(rows), "pedidos": rows,
                               "conteos": {value: len(rows) if value == kind else 0
                                           for value in ("nuevo", "verificar", "preparacion", "programado")}})
        if path.endswith("/eventos"):
            return self.reply({"entorno": "sandbox", "procesamiento": [], "eventos": [] if state["scenario"] == "empty" else [{
                "id": 1, "event_id": EVENT_ID, "pedido_id": ORDER_ID, "tipo": "orders.notification",
                "estado": "recibido", "recibido_en": "2026-10-24T20:00:00Z",
            }]})
        if path.endswith("/tienda"):
            return self.reply({"entorno": "sandbox", "nombre": "Jacaranda Sandbox", "tienda_id": "local-fixture-store",
                               "revision": 1, "estado": "ONLINE", "revocada": False,
                               "integracion": {"integration_enabled": True}, "requiere_conciliacion": False,
                               "cuenta_autorizada": True, "menu_publicado": True, "items": []})
        if path.endswith("/menu-ficticio"):
            return self.reply({"entorno": "sandbox", "menu": {"items": [{
                "id": "jacaranda-sandbox-brownie", "title": {"translations": {"es_mx": "Brownie ficticio de prueba"}},
                "price_info": {"price": 100},
            }]}})
        return self.reply({"detail": "Fixture no disponible"}, 404)

    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0))
        if size > 4096:
            return self.reply({}, 413)
        raw = self.rfile.read(size)
        if self.path == "/fixture/scenario":
            value = json.loads(raw).get("scenario")
            if value not in {"empty", "new", "changed", "unavailable"}:
                return self.reply({}, 400)
            state["scenario"] = value
            return self.reply(state)
        if self.headers.get("Authorization") != "Bearer " + ACCESS:
            return self.reply({}, 401)
        if self.path.endswith("/consultar"):
            return self.reply({"entorno": "sandbox", "acciones_habilitadas": state["scenario"] != "changed",
                               "requiere_conciliacion": state["scenario"] == "changed", "detalle_sha256": "0" * 64,
                               "listo_confirmado": False, "pedido": {
                                   "id": ORDER_ID, "display_id": "PRUEBA", "state": "OFFERED",
                                   "store_instructions": "Pedido ficticio. No preparar.",
                                   "carts": [{"items": [{"id": "jacaranda-sandbox-brownie", "title": "Brownie ficticio",
                                                         "quantity": {"amount": 1}, "special_instructions": "Sin nueces"}]}],
                               }})
        state["commands"] += 1
        return self.reply({"detail": "Las acciones no estan disponibles en esta vista local."}, 405)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    print(f"Local fictional preview: http://127.0.0.1:{args.port}", flush=True)
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
