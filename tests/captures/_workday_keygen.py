#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Generate an RSA-2048 keypair for Workday JWT Bearer authentication.

Run once per machine. Outputs two PEM files in
``solutions/ess-maker-skills/.local/`` (the kit's local-state directory,
which is gitignored):

    workday_oauth_private.pem    ← stays on this machine
    workday_oauth_public.pem     ← upload to Workday API Client

After running, follow the printed instructions to upload the public
key to your Workday "Register API Client for Integrations" client,
then set:

    $env:WORKDAY_JWT_PRIVATE_KEY_PATH = "<absolute path to private pem>"

and re-run tests/captures/record_workday_rest_admin.py.

The private key is generated entirely on this machine and is never sent
anywhere. The public key is the only thing that leaves your machine
(when you upload it to Workday via the UI).
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from _common import KIT_ROOT


def main() -> None:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        print("ERROR: 'cryptography' package not found.")
        print("Run: pip install cryptography")
        sys.exit(1)

    out_dir = KIT_ROOT / ".local"
    out_dir.mkdir(parents=True, exist_ok=True)
    private_path = out_dir / "workday_oauth_private.pem"
    public_path = out_dir / "workday_oauth_public.pem"

    if private_path.exists():
        print(f"  Private key already exists at {private_path}")
        ans = input("  Overwrite? [y/N]: ").strip().lower()
        if ans not in ("y", "yes"):
            print("  Aborted. To use the existing key, set:")
            print(f"    $env:WORKDAY_JWT_PRIVATE_KEY_PATH = \"{private_path}\"")
            return

    print("  Generating RSA-2048 keypair...")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    # Write private key with restrictive permissions (0600).
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd = os.open(str(private_path), flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(private_pem)
    finally:
        try:
            os.chmod(str(private_path), stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass  # Windows ignores chmod for files in some configurations

    public_path.write_bytes(public_pem)

    print(f"  ✓ Private key: {private_path}")
    print(f"  ✓ Public key:  {public_path}")
    print()
    print("=" * 70)
    print(" NEXT STEPS")
    print("=" * 70)
    print()
    print("1. Upload the PUBLIC key to Workday:")
    print()
    print("   a. Print the public PEM contents to your clipboard:")
    print(f"      Get-Content '{public_path}' | Set-Clipboard")
    print()
    print("   b. In Workday, find your API Client (the one created via")
    print("      'Register API Client for Integrations'):")
    print("      Search task: 'View API Client' or 'Edit API Client'")
    print("      Select your ESS-FlightCheck-Cassette-Recording client.")
    print()
    print("   c. From the Related Actions menu (the ... icon next to the")
    print("      client name), pick:")
    print("        API Client > Manage Public Keys")
    print("        OR")
    print("        Security > Manage Public Keys")
    print("      (the exact menu varies by Workday version)")
    print()
    print("   d. Add a new key entry. Paste the PEM from step (a) into")
    print("      the public-key field. Workday will read the key.")
    print()
    print("2. Set this env var so the wrapper can find the private key:")
    print(f"      $env:WORKDAY_JWT_PRIVATE_KEY_PATH = \"{private_path}\"")
    print()
    print("3. Re-run the wrapper. It will detect the env var and use")
    print("   JWT Bearer flow instead of client_credentials:")
    print("      python tests\\captures\\record_workday_rest_admin.py")
    print()
    print(f"The private key file ({private_path}) lives in .local/ which is")
    print("gitignored — it never leaves this machine. Treat it like the")
    print("Workday client secret: don't share, don't commit, rotate if")
    print("ever exposed.")


if __name__ == "__main__":
    main()
