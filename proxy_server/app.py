#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proxy_server.config import parse_args
from proxy_server.server import ProxyStore, start_listener
from proxy_server.utils.cert import generate_self_signed_cert
from proxy_server.utils.logging import log


def main():
    args = parse_args()
    
    # Only enable TLS for HTTP/HTTPS, not for SOCKS4/SOCKS5
    if args.protocol in ('http', 'https'):
        if args.certfile is None:
            try:
                cert, key = generate_self_signed_cert()
                args.certfile = cert
                args.keyfile = key
                log("[*] Generated self-signed cert")
            except Exception as e:
                log("[*] No TLS (cert generation failed): {0}", e)
    else:
        # SOCKS4/SOCKS5 don't use TLS
        args.certfile = None
        args.keyfile = None
        log("[*] TLS disabled for {0} protocol", args.protocol)

    store = ProxyStore(args)
    
    log("[*] Starting proxy server...")
    log("[*] Protocol: {0}", args.protocol)
    log("[*] Bind: {0}:{1}", args.bind, args.listen_port)
    log("[*] Rotate mode: {0}", args.rotate)
    log("[*] Min cost: {0}", args.min_cost)
    
    start_listener(args.bind, args.listen_port, store)


if __name__ == "__main__":
    main()
