"""Script de inicio para Railway/producción."""
import os
import subprocess
import sys

# Inicializar base de datos
subprocess.run([sys.executable, "scripts/init_db.py"], check=True)

# Obtener puerto de Railway o usar 8000
port = os.environ.get("PORT", "8000")

# Iniciar uvicorn
os.execvp(
    sys.executable,
    [sys.executable, "-m", "uvicorn", "main:app",
     "--host", "0.0.0.0", "--port", port]
)
