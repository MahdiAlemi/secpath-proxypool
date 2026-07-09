import argparse
import os

BUFFER_SIZE = 64 * 1024

HAVE_CRYPTO = True
try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import NoEncryption
    from cryptography.hazmat.backends import default_backend
except Exception:
    HAVE_CRYPTO = False

DEFAULT_BIND = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_ROTATE = "better_cost"
DEFAULT_THREADS = 100
DEFAULT_TIMEOUT = 10
DEFAULT_COST_THRESHOLD = None


def parse_args():
    parser = argparse.ArgumentParser(description="Proxy Server")
    parser.add_argument("--protocol", default="http", help="Proxy protocol (http, https, socks4, socks5)")
    parser.add_argument("--bind", default=DEFAULT_BIND, help="Bind address")
    parser.add_argument("--listen_port", type=int, default=DEFAULT_PORT, help="Listen port")
    parser.add_argument("--w_latency", type=float, default=0.4, help="Weight for latency cost")
    parser.add_argument("--w_fail", type=float, default=0.4, help="Weight for failure cost")
    parser.add_argument("--rotate", default=DEFAULT_ROTATE, choices=["fixed", "per_connection", "better_cost", "time", "sticky"], help="Rotation mode")
    parser.add_argument("--rotate_interval", type=int, default=60, help="Rotate interval (seconds)")
    parser.add_argument("--min_cost", type=float, default=0.0, help="Minimum cost filter")
    parser.add_argument("--cost_threshold", type=float, default=DEFAULT_COST_THRESHOLD, help="Cost threshold (optional)")
    parser.add_argument("--auth_required", help="Require auth (true/false)")
    parser.add_argument("--username", help="Username for auth")
    parser.add_argument("--password", help="Password for auth")
    parser.add_argument("--certfile", help="TLS certificate file")
    parser.add_argument("--keyfile", help="TLS key file")
    parser.add_argument("--insecure_upstream", action="store_true", help="Allow insecure upstream")
    parser.add_argument("--sticky_upstream", help="Sticky upstream proxy")
    parser.add_argument("--upstream_protocol", help="Upstream protocol")
    parser.add_argument("--candidate_statuses", default="alive", help="Candidate proxy statuses (comma-separated). Default: alive")
    parser.add_argument("--countryCodes", help="Filter by country codes (comma-separated)")
    parser.add_argument("--regions", help="Filter by regions (comma-separated)")
    parser.add_argument("--cities", help="Filter by cities (comma-separated)")
    parser.add_argument("--orgs", help="Filter by organizations (comma-separated)")
    parser.add_argument("--isp", help="Filter by ISP (comma-separated)")
    parser.add_argument("--asn", help="Filter by ASN (comma-separated)")
    parser.add_argument("--continentCode", help="Filter by continent code")
    parser.add_argument("--zip_codes", help="Filter by zip codes (comma-separated)")
    parser.add_argument("--timezones", help="Filter by timezones (comma-separated)")
    parser.add_argument("--mobile", help="Filter by mobile (true/false)")
    parser.add_argument("--proxy", help="Filter by proxy type (true/false)")
    parser.add_argument("--hosting", help="Filter by hosting (true/false)")
    parser.add_argument("--readonly", action="store_true", help="Do not update proxy health metrics from the server")
    return parser.parse_args()
