"""VAPID 鍵ペアを生成して JSON で出力する。

使い方:
    python -m app.cli_vapid              # public/private を base64url で表示
    python -m app.cli_vapid --out FILE   # FILE に JSON で書き出し (chmod 600)

private は秘密 (1Password 等)、public はブラウザにも渡る applicationServerKey。
どちらも env (VAPID_PRIVATE_KEY / VAPID_PUBLIC_KEY) にそのまま渡せる base64url 文字列。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate() -> dict[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private_value = key.private_numbers().private_value
    raw_priv = private_value.to_bytes(32, "big")
    pub = key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return {"public_key": _b64url(pub), "private_key": _b64url(raw_priv)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="JSON 書き出し先 (chmod 600)")
    args = parser.parse_args()
    keys = generate()
    if args.out:
        with open(args.out, "w") as f:
            json.dump(keys, f)
        os.chmod(args.out, 0o600)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(json.dumps(keys, indent=2))


if __name__ == "__main__":
    main()
