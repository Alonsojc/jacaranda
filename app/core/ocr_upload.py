"""Validacion compartida y acotada de archivos para OCR."""

from fastapi import HTTPException, UploadFile

from app.core.security_validation import detect_mime

MAX_OCR_BYTES = 20_000_000


async def leer_archivo_ocr(archivo: UploadFile) -> tuple[bytes, str]:
    contenido = bytearray()
    try:
        while chunk := await archivo.read(min(1_000_000, MAX_OCR_BYTES + 1 - len(contenido))):
            contenido.extend(chunk)
            if len(contenido) > MAX_OCR_BYTES:
                raise HTTPException(status_code=413, detail="El ticket supera el limite de 20 MB")
    finally:
        await archivo.close()
    mime = detect_mime(contenido)
    if mime is None:
        raise HTTPException(
            status_code=400,
            detail="Usa una foto JPG, PNG, WebP o GIF, o un PDF. Para HEIC, exporta la foto como JPG.",
        )
    return bytes(contenido), mime
