"""Qué direcciones IP puede recibir un webhook (protección contra SSRF).

SSRF: el atacante registra como endpoint una dirección interna (la de
metadatos de la nube, localhost, la base de datos...) y nuestro worker le hace
el POST desde dentro de nuestra red. Como guardamos el principio de la
respuesta y se puede leer en /attempts, podría leer servicios internos.
"""

import ipaddress


def is_public_ip(address: str) -> bool:
    """Indica si es una dirección de internet pública, a la que sí se puede enviar.

    is_global ya excluye las privadas (10/8, 172.16/12, 192.168/16, fc00::/7),
    loopback, link-local (169.254/16: los metadatos de la nube), 100.64/10,
    0.0.0.0 y los rangos reservados o de documentación.
    """
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])  # Sin la zona IPv6 (fe80::1%eth0).
    except ValueError:
        return False
    # ::ffff:127.0.0.1 es 127.0.0.1 escrito como IPv6: se juzga la IPv4 de dentro.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast
