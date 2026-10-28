"""Bounded CrossChex Cloud pull client. No device, employee or biometric writes."""

import hashlib
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from pydantic import AwareDatetime, BaseModel, Field, StrictInt, ValidationError

from app.core.config import settings

ENDPOINTS = {
    "us": "https://api.us.crosschexcloud.com/",
    "eu": "https://api.eu.crosschexcloud.com/",
    "ap": "https://api.ap.crosschexcloud.com/",
}
PAGE_SIZE = 500
MAX_PAGES = 10
MAX_SECONDS = 45
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class CrossChexError(Exception):
    """Messages are safe for the operator; never include provider responses."""


class ClockEmployee(BaseModel):
    workno: str = Field(min_length=1, max_length=80, pattern=r"^\S(?:.*\S)?$")
    first_name: str = Field(default="", max_length=100)
    last_name: str = Field(default="", max_length=100)


class ClockDevice(BaseModel):
    serial_number: str = Field(min_length=1, max_length=80)
    name: str = Field(default="", max_length=100)


class ClockRecord(BaseModel):
    employee: ClockEmployee
    device: ClockDevice
    checktime: AwareDatetime
    checktype: StrictInt = Field(ge=0, le=65535)


class ClockPage(BaseModel):
    count: StrictInt = Field(ge=0, le=PAGE_SIZE * MAX_PAGES)
    page: StrictInt = Field(ge=1)
    perPage: StrictInt = Field(ge=1, le=1000)
    pageCount: StrictInt = Field(ge=0, le=MAX_PAGES)
    records: list[ClockRecord] = Field(alias="list", max_length=PAGE_SIZE)


def configuration() -> dict:
    region = settings.CROSSCHEX_REGION.strip().lower()
    company = settings.CROSSCHEX_COMPANY_ID.strip()
    devices = {s.strip() for s in settings.CROSSCHEX_DEVICE_SERIALS.split(",") if s.strip()}
    missing = []
    if region not in ENDPOINTS:
        missing.append("region")
    if not company or len(company) > 120:
        missing.append("empresa")
    if not devices or any(len(s) > 80 for s in devices):
        missing.append("equipo")
    if not settings.CROSSCHEX_API_KEY.get_secret_value():
        missing.append("api_key")
    if not settings.CROSSCHEX_API_SECRET.get_secret_value():
        missing.append("api_secret")
    return {
        "cuenta": f"{region}:{company}" if region in ENDPOINTS and company else "",
        "region": region,
        "devices": devices,
        "faltantes": missing,
        "habilitada": settings.CROSSCHEX_ENABLED,
        "lista": settings.CROSSCHEX_ENABLED and not missing,
    }


def record_identity(account: str, record: ClockRecord) -> str:
    # Cloud does not document a record UUID. Preserve raw type and second/fraction.
    key = [account, record.device.serial_number, record.employee.workno,
           record.checktime.astimezone(timezone.utc).isoformat(), record.checktype]
    return hashlib.sha256(json.dumps(key, ensure_ascii=True).encode()).hexdigest()


def _request(client, endpoint, namespace, action, payload, deadline, token=None):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CrossChexError("La consulta tardó demasiado. Reintenta con un periodo menor.")
    body = {
        "header": {
            "nameSpace": namespace, "nameAction": action, "version": "1.0",
            "requestId": str(uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "payload": payload,
    }
    if token:
        body["authorize"] = {"type": "token", "token": token}
    try:
        with client.stream("POST", endpoint, json=body, timeout=min(10, remaining)) as response:
            if response.status_code != 200:
                raise CrossChexError("CrossChex no respondió correctamente. Revisa acceso y región.")
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE_BYTES or time.monotonic() > deadline:
                    raise CrossChexError("Respuesta demasiado grande o lenta. Reduce el periodo.")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("code") != 200 or data.get("error"):
            raise CrossChexError("CrossChex rechazó la consulta. Revisa Developer Mode y credenciales.")
        result = data["data"]["payload"]
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise CrossChexError("No se pudo validar la respuesta de CrossChex; no se importó nada.") from exc


def fetch_records(begin: datetime, end: datetime, config: dict) -> tuple[list[ClockRecord], int]:
    if not config["lista"]:
        raise CrossChexError("Conexión pendiente: configura CrossChex antes de sincronizar.")
    endpoint = ENDPOINTS[config["region"]]
    deadline = time.monotonic() + MAX_SECONDS
    records = []
    omitted = 0
    expected_count = None
    received = 0
    with httpx.Client(follow_redirects=False, trust_env=False) as client:
        auth = _request(client, endpoint, "authorize.token", "token", {
            "api_key": settings.CROSSCHEX_API_KEY.get_secret_value(),
            "api_secret": settings.CROSSCHEX_API_SECRET.get_secret_value(),
        }, deadline)
        token = auth.get("token")
        if not isinstance(token, str) or not token or len(token) > 8192:
            raise CrossChexError("CrossChex no entregó un token válido.")
        for page_number in range(1, MAX_PAGES + 1):
            payload = _request(client, endpoint, "attendance.record", "getrecord", {
                "begin_time": begin.isoformat(), "end_time": end.isoformat(),
                "order": "asc", "page": page_number, "per_page": PAGE_SIZE,
            }, deadline, token)
            try:
                page = ClockPage.model_validate(payload)
            except ValidationError as exc:
                raise CrossChexError("Hay checadas incompletas o un formato no reconocido. No se importó nada.") from exc
            if expected_count is None:
                expected_count = page.count
            pages_expected = (page.count + page.perPage - 1) // page.perPage
            if (page.page != page_number or page.perPage != PAGE_SIZE
                    or page.count != expected_count
                    or page.pageCount != pages_expected and not (page.count == 0 and page.pageCount == 1)):
                raise CrossChexError("La paginación cambió o está incompleta. Reintenta la consulta.")
            expected_size = min(PAGE_SIZE, max(0, page.count - (page_number - 1) * PAGE_SIZE))
            if len(page.records) != expected_size:
                raise CrossChexError("Faltan checadas en la respuesta. No se importó nada.")
            received += len(page.records)
            for record in page.records:
                if not begin <= record.checktime <= end:
                    raise CrossChexError("CrossChex devolvió una fecha fuera del periodo solicitado.")
                if record.device.serial_number not in config["devices"]:
                    omitted += 1
                    continue
                records.append(record)
            if page_number >= page.pageCount:
                if received != expected_count:
                    raise CrossChexError("La respuesta está incompleta. No se importó nada.")
                return records, omitted
    raise CrossChexError("Demasiadas checadas. Sincroniza un periodo menor.")
