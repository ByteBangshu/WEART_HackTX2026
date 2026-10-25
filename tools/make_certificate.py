"""Create a local development CA and SAN-bound host certificate; never disables validation."""

import argparse
import ipaddress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", required=True, help="Exact LAN IP or hostname used by phone/device")
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "runtime/tls")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    if any((a.out / name).exists() for name in ("ca.pem", "host.pem", "host.key")):
        raise SystemExit("Certificates already exist; use a new --out directory to rotate explicitly.")
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WEART local development CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    try:
        san = x509.IPAddress(ipaddress.ip_address(a.host))
    except ValueError:
        san = x509.DNSName(a.host)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, a.host)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=90))
        .add_extension(x509.SubjectAlternativeName([san]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    (a.out / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (a.out / "host.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (a.out / "host.key").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    (a.out / "host.key").chmod(0o600)
    print(
        f"Created certificates in {a.out}. Install ONLY ca.pem on the phone and camera. Keep host.key private."
    )


if __name__ == "__main__":
    main()
