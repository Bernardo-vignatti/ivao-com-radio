"""HTTPS na rede local, sem mkcert.

O Safari so guarda a pagina no celular (service worker) em HTTPS. Para isso
o projeto cria uma CA propria uma unica vez, que o iPhone passa a confiar, e
um certificado de servidor assinado por ela.

A CA nunca e trocada: reinstalar no iPhone e o passo chato. O certificado do
servidor se refaz sozinho quando o IP muda ou quando falta pouco para vencer,
e o celular nem percebe, porque confia na CA.

Tambem serve a pagina de instalacao por HTTP puro, que e por onde o iPhone
baixa a CA antes de confiar nela.
"""

import datetime as dt
import ipaddress
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

log = logging.getLogger("certs")

CA_NAME = "COM Radio CA"
# a Apple recusa certificado de servidor com mais de 825 dias, mesmo de CA
# instalada a mao. 397 fica longe do limite e renova sozinho
LEAF_DAYS = 397
RENEW_BEFORE = dt.timedelta(days=30)
PRIVATE_NETS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8")


def hostname() -> str:
    return socket.gethostname()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _key() -> rsa.RSAPrivateKey:
    # RSA 2048 em vez de EC: e o que todo iOS aceita sem discussao
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _write_key(path: Path, key) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )


def _ensure_ca(folder: Path) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    crt, key = folder / "ca.crt", folder / "ca.key"
    if crt.exists() and key.exists():
        return (
            x509.load_pem_x509_certificate(crt.read_bytes()),
            serialization.load_pem_private_key(key.read_bytes(), None),
        )

    log.info("criando a CA local (so acontece uma vez)")
    ca_key = _key()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME)])
    ski = x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key())
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - dt.timedelta(days=1))
        .not_valid_after(_now() + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(ski, critical=False)
        # a CA so vale para a rede local. Se a ca.key vazar, nao da para
        # assinar um site de verdade que o iPhone aceite. CAs criadas antes
        # disto continuam valendo, sem a restricao
        .add_extension(
            x509.NameConstraints(
                permitted_subtrees=[x509.DNSName("local"), x509.DNSName("localhost")]
                + [x509.IPAddress(ipaddress.ip_network(n)) for n in PRIVATE_NETS],
                excluded_subtrees=None,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(key, ca_key)
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert, ca_key


def names(ip: str) -> tuple[list[str], list[str]]:
    # so o .local: o nome curto nao resolve no iPhone, e a restricao de
    # nomes da CA so permite .local e localhost
    dns = sorted({hostname() + ".local", "localhost"})
    ips = sorted({ip, "127.0.0.1"})
    return dns, ips


def _leaf_ok(path: Path, dns: list[str], ips: list[str]) -> bool:
    if not path.exists():
        return False
    cert = x509.load_pem_x509_certificate(path.read_bytes())
    if cert.not_valid_after_utc - _now() < RENEW_BEFORE:
        return False
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    have_dns = sorted(san.get_values_for_type(x509.DNSName))
    have_ips = sorted(str(i) for i in san.get_values_for_type(x509.IPAddress))
    return have_dns == dns and have_ips == ips


def ensure(folder: Path, ip: str) -> tuple[Path, Path]:
    """Garante CA e certificado do servidor validos para este IP.

    Devolve (cert, chave) do servidor, prontos para o uvicorn.
    """
    folder.mkdir(parents=True, exist_ok=True)
    ca_cert, ca_key = _ensure_ca(folder)
    crt, key = folder / "server.crt", folder / "server.key"
    dns, ips = names(ip)
    if _leaf_ok(crt, dns, ips) and key.exists():
        return crt, key

    log.info("gerando certificado do servidor para %s", ", ".join(dns + ips))
    leaf_key = _key()
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns[0])]))
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - dt.timedelta(days=1))
        .not_valid_after(_now() + dt.timedelta(days=LEAF_DAYS))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(d) for d in dns]
                + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(key, leaf_key)
    # a cadeia inteira no arquivo, para o iPhone montar o caminho ate a CA
    crt.write_bytes(
        cert.public_bytes(serialization.Encoding.PEM)
        + ca_cert.public_bytes(serialization.Encoding.PEM)
    )
    return crt, key


def serve_setup(port: int, page: Path, ca: Path, https_port: int) -> ThreadingHTTPServer:
    """Pagina de instalacao por HTTP puro, numa thread.

    O iPhone ainda nao confia na CA quando chega aqui, entao isto nao pode
    ser HTTPS. So serve a pagina e o certificado da CA, nada do radio.
    """
    host = hostname()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/ca.crt"):
                body = ca.read_bytes()
                kind = "application/x-x509-ca-cert"
            else:
                html = page.read_text(encoding="utf-8")
                html = html.replace("{{HOST}}", host + ".local").replace("{{PORT}}", str(https_port))
                body = html.encode("utf-8")
                kind = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True, name="setup").start()
    return httpd


if __name__ == "__main__":
    # confere que a CA assina o servidor e que um segundo ensure nao regera
    import ssl
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        crt, key = ensure(folder, "192.168.1.50")
        first = crt.read_bytes()
        assert ensure(folder, "192.168.1.50")[0].read_bytes() == first, "regerou sem motivo"
        ca_before = (folder / "ca.crt").read_bytes()
        assert ensure(folder, "192.168.1.51")[0].read_bytes() != first, "nao regerou com IP novo"
        assert (folder / "ca.crt").read_bytes() == ca_before, "a CA nao pode mudar"

        ctx = ssl.create_default_context(cafile=str(folder / "ca.crt"))
        ctx.load_cert_chain(crt, key)
        leaf = x509.load_pem_x509_certificate(crt.read_bytes())
        ca_cert = x509.load_pem_x509_certificate(ca_before)
        leaf.verify_directly_issued_by(ca_cert)
        assert ca_cert.extensions.get_extension_for_class(x509.NameConstraints).critical
        print("ok")
