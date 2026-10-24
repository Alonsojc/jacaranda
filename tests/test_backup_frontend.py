"""Verification UI must not mistake SQL inspection for a proven restore."""

from pathlib import Path
import shutil
import subprocess

import pytest


HTML = Path("docs/index.html").read_text(encoding="utf-8")
START = HTML.index("function renderResultadoVerificacion(info)")
RENDER = HTML[START:HTML.index("async function probarRestauracionBackup", START)]


def test_verification_distinguishes_inspection_and_restore():
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node required")
    script = "const assert=require('node:assert/strict'); function escHtml(s){return String(s);} " + RENDER + r"""
for (const info of [{restored:false}, {}, {restored:false,restore_mode:'sql_inspection'}]) {
  const html=renderResultadoVerificacion({...info,filename:'test.sql'});
  assert(html.includes('sin restaurar'));
  assert(!html.includes('Restauraci&oacute;n probada:'));
}
const restored=renderResultadoVerificacion({restored:true,filename:'test.db',table_count:2});
assert(restored.includes('Restauraci&oacute;n probada:'));
assert(!restored.includes('sin restaurar'));
"""
    result = subprocess.run([executable, "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_container_context_excludes_private_backup_artifacts():
    patterns = set(Path(".dockerignore").read_text(encoding="utf-8").splitlines())
    assert {".env", ".env.*", ".admin_password", "backups/", "output/",
            "**/*.db", "**/*.db-wal", "**/*.db-shm", "**/jacaranda_*.sql",
            "*.key", "*.pem", "*.pfx"} <= patterns
