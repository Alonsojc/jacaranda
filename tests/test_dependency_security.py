"""Dependency regression checks use synthetic files, forms and signing keys."""

import base64
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
from PIL import Image
from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.config import Settings, settings
from app.services import lealtad_service, ocr_service, pagos_service


def form_client(max_fields=1, **limits):
    async def receive(request):
        async with request.form(max_fields=max_fields, **limits) as form:
            result = {}
            for name, value in form.multi_items():
                if isinstance(value, UploadFile):
                    result[name] = {
                        "filename": value.filename,
                        "content": (await value.read()).decode("ascii"),
                    }
                else:
                    result[name] = value
            return JSONResponse(result)

    return TestClient(Starlette(routes=[Route("/form", receive, methods=["POST"])]))


def test_urlencoded_field_limit_is_not_ignored():
    with form_client() as client:
        response = client.post(
            "/form", content="one=1&two=2",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    assert response.status_code == 400


def test_urlencoded_semicolon_remains_part_of_value():
    with form_client(max_fields=3) as client:
        response = client.post(
            "/form", content="note=one;two&total=2",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    assert response.status_code == 200
    assert response.json() == {"note": "one;two", "total": "2"}


def test_multipart_preserves_file_and_json_options():
    with form_client() as client:
        response = client.post(
            "/form", files={"archivo": ("synthetic.xlsx", b"fixture", "application/octet-stream")},
            data={"opciones": '{"fecha":"DMY"}'},
        )
    assert response.status_code == 200
    assert response.json() == {
        "archivo": {"filename": "synthetic.xlsx", "content": "fixture"},
        "opciones": '{"fecha":"DMY"}',
    }


def test_multipart_missing_boundary_is_a_client_error():
    with form_client() as client:
        response = client.post(
            "/form", content=b"not a multipart body",
            headers={"Content-Type": "multipart/form-data"},
        )
    assert response.status_code == 400


@pytest.mark.parametrize("multipart", [False, True])
def test_form_field_size_limit_is_enforced(multipart):
    with form_client(max_part_size=8) as client:
        if multipart:
            response = client.post("/form", files={"note": (None, "123456789")})
        else:
            response = client.post(
                "/form", content="note=123456789",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    assert response.status_code == 400


def test_dotenv_reads_only_the_selected_synthetic_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_NAME", raising=False)
    source = tmp_path / "synthetic.env"
    source.write_text('APP_NAME="Synthetic configuration"\n', encoding="utf-8")
    configured = Settings(
        _env_file=source, DATABASE_URL="sqlite://", ENVIRONMENT="testing",
        RAILWAY_ENVIRONMENT="", SECRET_KEY="synthetic-configuration-key-not-for-production",
    )
    assert configured.APP_NAME == "Synthetic configuration"
    assert configured.DATABASE_URL == "sqlite://"


def test_transparent_ocr_image_becomes_opaque_jpeg():
    source = BytesIO()
    Image.new("RGBA", (300, 300), (0, 0, 0, 0)).save(source, "PNG")
    blocks, _ = ocr_service.preparar_documento(source.getvalue(), "image/png")
    content = base64.b64decode(blocks[0]["source"]["data"])
    with Image.open(BytesIO(content)) as converted:
        assert converted.format == "JPEG"
        assert converted.mode == "RGB"
        assert min(converted.getpixel((150, 150))) > 245


def test_animated_ocr_image_is_rejected():
    source = BytesIO()
    Image.new("RGB", (300, 300), "white").save(
        source, "GIF", save_all=True,
        append_images=[Image.new("RGB", (300, 300), "black")],
    )
    with pytest.raises(ValueError, match="animada"):
        ocr_service.preparar_documento(source.getvalue(), "image/gif")


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.mark.parametrize("prefix", ["", "sha256="])
def test_webhook_signature_accepts_original_and_rejects_modified_body(signing_key, monkeypatch, prefix):
    public_key = signing_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    monkeypatch.setattr(settings, "CONEKTA_WEBHOOK_PUBLIC_KEY", public_key)
    body = b'{"type":"order.paid","amount":500}'
    signature = signing_key.sign(body, padding.PKCS1v15(), hashes.SHA256())
    digest = prefix + base64.b64encode(signature).decode("ascii")
    pagos_service.verificar_firma_webhook_conekta(body, digest)
    with pytest.raises(pagos_service.WebhookSignatureError):
        pagos_service.verificar_firma_webhook_conekta(body.replace(b"500", b"900"), digest)
    with pytest.raises(pagos_service.WebhookSignatureError):
        pagos_service.verificar_firma_webhook_conekta(body, "not@base64")


def wallet_fixture(monkeypatch):
    customer = SimpleNamespace(
        nombre="Synthetic customer", tarjeta_qr="synthetic-qr",
        monto_lealtad_acumulado=100, puntos_acumulados=10,
    )
    monkeypatch.setattr(lealtad_service, "_public_cliente_por_qr", lambda *args: customer)
    monkeypatch.setattr(lealtad_service, "obtener_configuracion", lambda *args: object())
    monkeypatch.setattr(lealtad_service, "progreso_recompensa", lambda *args: {
        "nombre": "Synthetic reward", "disponibles": 0, "monto_restante": 900,
    })
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://example.invalid/")
    return customer


def test_google_wallet_signature_round_trip_with_synthetic_key(signing_key, monkeypatch):
    customer = wallet_fixture(monkeypatch)
    private_pem = signing_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    monkeypatch.setattr(settings, "GOOGLE_WALLET_ISSUER_ID", "synthetic")
    monkeypatch.setattr(settings, "GOOGLE_WALLET_CLASS_ID", "loyalty")
    monkeypatch.setattr(settings, "GOOGLE_WALLET_SERVICE_ACCOUNT_JSON", json.dumps({
        "client_email": "synthetic@example.invalid", "private_key": private_pem,
    }))
    url = lealtad_service.generar_google_wallet_url(None, customer)
    token = url.rsplit("/", 1)[1]
    header, payload, signature = token.split(".")
    signing_key.public_key().verify(
        base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
        f"{header}.{payload}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256(),
    )
    decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert decoded["iss"] == "synthetic@example.invalid"
    assert decoded["payload"]["genericObjects"][0]["classId"] == "synthetic.loyalty"


def test_apple_wallet_detached_signature_and_manifest(signing_key, monkeypatch, tmp_path):
    wallet_fixture(monkeypatch)
    now = datetime.now(timezone.utc)

    def certificate(name):
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        return (
            x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(signing_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1)).sign(signing_key, hashes.SHA256())
        )

    leaf, issuer = certificate("Synthetic wallet"), certificate("Synthetic issuer")
    monkeypatch.setattr(lealtad_service, "wallet_status_publico", lambda *args: {"apple_wallet_faltante": []})
    monkeypatch.setattr(settings, "APPLE_WALLET_PASS_TYPE_ID", "pass.invalid.synthetic")
    monkeypatch.setattr(settings, "APPLE_WALLET_TEAM_ID", "SYNTHETIC")
    monkeypatch.setattr(settings, "APPLE_WALLET_CERT_PEM", leaf.public_bytes(serialization.Encoding.PEM).decode())
    monkeypatch.setattr(settings, "APPLE_WALLET_WWDR_PEM", issuer.public_bytes(serialization.Encoding.PEM).decode())
    monkeypatch.setattr(settings, "APPLE_WALLET_KEY_PEM", signing_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ).decode())
    result = lealtad_service.generar_apple_pkpass(None, "synthetic-qr")
    with ZipFile(BytesIO(result)) as archive:
        manifest_bytes = archive.read("manifest.json")
        manifest = json.loads(manifest_bytes)
        for filename, digest in manifest.items():
            assert hashlib.sha1(archive.read(filename)).hexdigest() == digest
        signature_bytes = archive.read("signature")
        certificates = pkcs7.load_der_pkcs7_certificates(signature_bytes)
        assert leaf in certificates
        assert issuer in certificates
        assert json.loads(archive.read("pass.json"))["serialNumber"] == "jacaranda-synthetic-qr"

    openssl = shutil.which("openssl")
    assert openssl, "OpenSSL is required to validate the synthetic CMS signature"
    signature_path = tmp_path / "signature.der"
    manifest_path = tmp_path / "manifest.json"
    signature_path.write_bytes(signature_bytes)
    manifest_path.write_bytes(manifest_bytes)
    # The fixture is self-signed: skip trust-chain validation, not the signature.
    command = [openssl, "cms", "-verify", "-binary", "-inform", "DER", "-noverify",
               "-in", str(signature_path), "-content", str(manifest_path)]
    valid = subprocess.run(command, capture_output=True, timeout=10)
    assert valid.returncode == 0, valid.stderr.decode(errors="replace")
    assert valid.stdout == manifest_bytes
    manifest_path.write_bytes(manifest_bytes + b"\n")
    tampered = subprocess.run(command, capture_output=True, timeout=10)
    assert tampered.returncode != 0
