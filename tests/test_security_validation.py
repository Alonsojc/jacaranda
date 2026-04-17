"""Tests para validación de seguridad al arranque y detección de archivos."""

import pytest
from unittest.mock import patch

from app.core.security_validation import (
    validate_secret_key,
    detect_mime,
    is_image,
)


class TestValidateSecretKey:
    def test_weak_secret_rejected_in_prod(self):
        with patch("app.core.security_validation.settings") as mock:
            mock.DEBUG = False
            mock.SECRET_KEY = "cambiar-por-una-clave-secreta-segura-de-al-menos-32-caracteres"
            with pytest.raises(RuntimeError, match="ejemplo"):
                validate_secret_key()

    def test_short_secret_rejected_in_prod(self):
        with patch("app.core.security_validation.settings") as mock:
            mock.DEBUG = False
            mock.SECRET_KEY = "too-short"
            with pytest.raises(RuntimeError, match="32 caracteres"):
                validate_secret_key()

    def test_strong_secret_accepted(self):
        with patch("app.core.security_validation.settings") as mock:
            mock.DEBUG = False
            mock.SECRET_KEY = "x" * 64
            validate_secret_key()  # no exception

    def test_weak_secret_allowed_in_debug(self):
        with patch("app.core.security_validation.settings") as mock:
            mock.DEBUG = True
            mock.SECRET_KEY = "short"
            validate_secret_key()  # solo warning


class TestDetectMime:
    def test_jpeg(self):
        assert detect_mime(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00") == "image/jpeg"

    def test_png(self):
        assert detect_mime(b"\x89PNG\r\n\x1a\n\x00\x00") == "image/png"

    def test_gif(self):
        assert detect_mime(b"GIF89a\x01\x00") == "image/gif"

    def test_webp(self):
        assert detect_mime(b"RIFF\x00\x00\x00\x00WEBPVP8") == "image/webp"

    def test_webp_false_riff(self):
        # RIFF sin WEBP no se considera webp
        assert detect_mime(b"RIFF\x00\x00\x00\x00WAVEfmt") is None

    def test_pdf(self):
        assert detect_mime(b"%PDF-1.4\n%...") == "application/pdf"

    def test_executable_rejected(self):
        # ELF binary
        assert detect_mime(b"\x7fELF\x02\x01\x01\x00") is None

    def test_windows_exe(self):
        assert detect_mime(b"MZ\x90\x00") is None


class TestIsImage:
    def test_true_for_jpeg(self):
        assert is_image(b"\xff\xd8\xff\xe0") is True

    def test_false_for_pdf(self):
        assert is_image(b"%PDF-1.4") is False

    def test_false_for_text(self):
        assert is_image(b"Hello World") is False
