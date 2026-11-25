"""Qué IP se consideran públicas: la tabla de la protección contra SSRF."""

import pytest

from relay.domain.destinations import is_public_ip


@pytest.mark.parametrize(
    "address",
    [
        pytest.param("127.0.0.1", id="loopback"),
        pytest.param("127.8.8.8", id="loopback-todo-el-rango"),
        pytest.param("10.0.0.5", id="privada-10"),
        pytest.param("172.16.0.1", id="privada-172.16"),
        pytest.param("172.31.255.254", id="privada-172.31"),
        pytest.param("192.168.1.1", id="privada-192.168"),
        pytest.param("169.254.169.254", id="metadatos-de-la-nube"),
        pytest.param("100.64.0.1", id="cgnat"),
        pytest.param("0.0.0.0", id="cero"),
        pytest.param("224.0.0.1", id="multicast"),
        pytest.param("255.255.255.255", id="broadcast"),
        pytest.param("192.0.2.10", id="documentacion"),
        pytest.param("::1", id="ipv6-loopback"),
        pytest.param("fd00::1", id="ipv6-privada"),
        pytest.param("fe80::1", id="ipv6-link-local"),
        pytest.param("fe80::1%eth0", id="ipv6-link-local-con-zona"),
        pytest.param("::ffff:127.0.0.1", id="ipv4-dentro-de-ipv6"),
        pytest.param("::ffff:169.254.169.254", id="metadatos-dentro-de-ipv6"),
        pytest.param("::", id="ipv6-sin-especificar"),
        pytest.param("no-es-una-ip", id="basura"),
    ],
)
def test_las_direcciones_internas_no_son_publicas(address):
    assert is_public_ip(address) is False


@pytest.mark.parametrize(
    "address",
    [
        pytest.param("8.8.8.8", id="ipv4"),
        pytest.param("172.15.255.255", id="justo-antes-de-172.16"),
        pytest.param("172.32.0.0", id="justo-despues-de-172.31"),
        pytest.param("2606:4700::1111", id="ipv6"),
        pytest.param("::ffff:8.8.8.8", id="ipv4-publica-dentro-de-ipv6"),
    ],
)
def test_las_direcciones_de_internet_son_publicas(address):
    assert is_public_ip(address) is True
