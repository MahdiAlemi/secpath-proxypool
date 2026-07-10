#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import ensure_db_schema
from proxy_server.config import parse_args
from proxy_server.lifecycle import claim, release
from proxy_server.server.listener import start_listener
from proxy_server.server.proxy_store import ProxyStore
from proxy_server.utils.cert import generate_self_signed_cert
from proxy_server.utils.logging import log


def main():
    args = parse_args()
    generated_files = []
    root_dir = Path(__file__).resolve().parents[1]
    try:
        if args.protocol == "https" and not args.certfile:
            cert, key = generate_self_signed_cert()
            args.certfile, args.keyfile = cert, key
            generated_files.extend([cert, key])
            log("[*] Generated temporary self-signed listener certificate")
        elif args.protocol != "https":
            args.certfile = None
            args.keyfile = None

        ensure_db_schema()
        claim(root_dir, args.server_id, token=args.claim_token)
        store = ProxyStore(args)
        log("[*] Starting proxy server {0}", args.server_id)
        log("[*] Protocol: {0}", args.protocol)
        log("[*] Bind: {0}:{1}", args.bind, args.listen_port)
        log("[*] Rotate mode: {0}", args.rotate)
        start_listener(args.bind, args.listen_port, store)
    finally:
        release(root_dir, args.server_id, pid=os.getpid())
        for filename in generated_files:
            with contextlib.suppress(OSError):
                os.unlink(filename)


if __name__ == "__main__":
    main()
