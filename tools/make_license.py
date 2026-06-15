# -*- coding: utf-8 -*-
"""Emite una licencia de PressForge firmada. SOLO para el vendedor.

Requiere `license_private_key.txt` (la clave privada, fuera del repo).

Uso:
    python tools/make_license.py "Nombre Cliente" [correo] [expira YYYY-MM-DD]

Ej:
    python tools/make_license.py "Juan Pérez" juan@correo.com
    python tools/make_license.py "Acme SL" ventas@acme.com 2027-01-01

Imprime la CLAVE DE LICENCIA que le envías al cliente (la pega en la app).
"""
import base64
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def main() -> None:
    key_file = Path("license_private_key.txt")
    if not key_file.exists():
        sys.exit("✗ Falta license_private_key.txt (la clave privada del vendedor).")
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(key_file.read_text().strip()))

    name = sys.argv[1] if len(sys.argv) > 1 else "Cliente"
    email = sys.argv[2] if len(sys.argv) > 2 else ""
    exp = sys.argv[3] if len(sys.argv) > 3 else None

    payload = json.dumps({"name": name, "email": email, "exp": exp},
                         separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sig = priv.sign(payload)
    key = f"{b64url(payload)}.{b64url(sig)}"

    print(f"\nLicencia para: {name}" + (f" <{email}>" if email else "") + (f"  (expira {exp})" if exp else "  (sin expiración)"))
    print("─" * 60)
    print(key)
    print("─" * 60)
    print("Envíasela al cliente: la pega en la pantalla de activación.\n")


if __name__ == "__main__":
    main()
