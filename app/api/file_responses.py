"""Private file downloads whose copies must not outlive the request."""

import logging
from pathlib import Path

from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)


def remove_download_copy(path):
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        logger.error("Could not remove a temporary private download copy")


class PrivateDownloadResponse(FileResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            remove_download_copy(self.path)
