import tempfile
from datetime import datetime, timedelta, timezone
from ipaddress import IPv4Address
from typing import Tuple

from proxy_server.config import HAVE_CRYPTO


def generate_self_signed_cert(common_name: str = "localhost") -> Tuple[str, str]:
    if not HAVE_CRYPTO:
        raise RuntimeError("cryptography package not available (pip install cryptography)")

    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName("127.0.0.1"),
                x509.DNSName("proxy.local"),
                x509.IPAddress(IPv4Address("127.0.0.1")),
            ]),
            critical=False
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(private_key=key, algorithm=hashes.SHA256(), backend=default_backend())
    )

    tf_cert = tempfile.NamedTemporaryFile(prefix="proxy_cert_", suffix=".pem", delete=False)
    tf_key = tempfile.NamedTemporaryFile(prefix="proxy_key_", suffix=".pem", delete=False)

    tf_cert.write(cert.public_bytes(serialization.Encoding.PEM))
    tf_cert.flush()
    tf_key.write(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ))
    tf_key.flush()

    return tf_cert.name, tf_key.name
