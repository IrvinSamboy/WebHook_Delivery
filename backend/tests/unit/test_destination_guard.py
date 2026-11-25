import pytest

from relay.application.errors import DestinationNotAllowed
from relay.infrastructure.destination_guard import DnsDestinationGuard


def resolver(table: dict[str, list[str]], calls: list | None = None):
    """Un DNS falso: los tests no dependen de internet."""

    def resolve(host: str, port: int) -> list[str]:
        if calls is not None:
            calls.append((host, port))
        if host not in table:
            raise OSError("Name or service not known")
        return table[host]

    return resolve


def guard(table: dict[str, list[str]], allow_private: bool = False, calls=None):
    return DnsDestinationGuard(allow_private, resolver(table, calls))


def test_deja_pasar_un_host_que_resuelve_a_una_ip_publica():
    guard({"receptor.com": ["93.184.216.34"]}).check("https://receptor.com/hook")


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("http://169.254.169.254/latest/meta-data/", id="ip-de-metadatos"),
        pytest.param("http://127.0.0.1:5432/", id="ip-loopback"),
        pytest.param("http://[::1]:6379/", id="ipv6-loopback"),
        pytest.param("http://interno.com/", id="nombre-que-resuelve-a-privada"),
    ],
)
def test_rechaza_las_que_apuntan_a_una_direccion_interna(url):
    table = {
        "169.254.169.254": ["169.254.169.254"],
        "127.0.0.1": ["127.0.0.1"],
        "::1": ["::1"],
        "interno.com": ["10.0.0.7"],
    }

    with pytest.raises(DestinationNotAllowed, match="dirección interna"):
        guard(table).check(url)


def test_basta_una_ip_interna_entre_varias_para_rechazarla():
    # El cliente HTTP podría conectar a cualquiera de ellas.
    table = {"mixto.com": ["93.184.216.34", "127.0.0.1"]}

    with pytest.raises(DestinationNotAllowed):
        guard(table).check("https://mixto.com/")


@pytest.mark.parametrize("table", [{}, {"vacio.com": []}], ids=["no-existe", "sin-direcciones"])
def test_rechaza_un_host_que_no_se_puede_resolver(table):
    with pytest.raises(DestinationNotAllowed, match="no se pudo resolver"):
        guard(table).check("https://vacio.com/")


@pytest.mark.parametrize(
    "url", ["ftp://receptor.com/", "file:///etc/passwd", "https:///sin-host"], ids=str
)
def test_rechaza_lo_que_no_es_una_url_http(url):
    with pytest.raises(DestinationNotAllowed, match="URL no válida"):
        guard({}, allow_private=True).check(url)


@pytest.mark.parametrize(
    ("url", "port"),
    [
        ("https://receptor.com/", 443),
        ("http://receptor.com/", 80),
        ("https://receptor.com:8443/", 8443),
    ],
)
def test_resuelve_con_el_puerto_de_la_url(url, port):
    calls = []

    guard({"receptor.com": ["93.184.216.34"]}, calls=calls).check(url)

    assert calls == [("receptor.com", port)]


def test_con_allow_private_deja_pasar_las_internas_sin_resolver():
    calls = []

    guard({}, allow_private=True, calls=calls).check("http://receiver:9000/")

    assert calls == []


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("http://localhost:8000/", id="localhost"),
        pytest.param("http://127.0.0.1/", id="loopback"),
        # 2130706433 es 127.0.0.1 escrito como un número: el DNS real lo traduce.
        pytest.param("http://2130706433/", id="ip-como-numero"),
        pytest.param("http://0x7f000001/", id="ip-en-hexadecimal"),
    ],
)
def test_con_el_dns_real_tambien_rechaza_los_disfraces_de_localhost(url):
    # Sin resolver falso: estos nombres se resuelven sin salir a internet.
    with pytest.raises(DestinationNotAllowed):
        DnsDestinationGuard(allow_private=False).check(url)
