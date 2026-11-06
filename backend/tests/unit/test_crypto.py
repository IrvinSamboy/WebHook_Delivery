import pytest
from cryptography.fernet import Fernet, InvalidToken

from relay.infrastructure.crypto import SecretCipher

SECRET = "whsec_c2VjcmV0"


def make_cipher() -> SecretCipher:
    return SecretCipher(Fernet.generate_key().decode())


def test_descifrar_devuelve_el_valor_original():
    cipher = make_cipher()

    assert cipher.decrypt(cipher.encrypt(SECRET)) == SECRET


def test_el_valor_cifrado_no_contiene_el_secreto():
    assert SECRET not in make_cipher().encrypt(SECRET)


def test_cifrar_dos_veces_da_resultados_distintos():
    cipher = make_cipher()

    assert cipher.encrypt(SECRET) != cipher.encrypt(SECRET)


def test_no_se_puede_descifrar_con_otra_clave():
    encrypted = make_cipher().encrypt(SECRET)

    with pytest.raises(InvalidToken):
        make_cipher().decrypt(encrypted)


def test_detecta_si_el_valor_cifrado_fue_alterado():
    cipher = make_cipher()
    encrypted = cipher.encrypt(SECRET)
    # Cambia un carácter en mitad del valor.
    middle = len(encrypted) // 2
    replacement = "A" if encrypted[middle] != "A" else "B"
    tampered = encrypted[:middle] + replacement + encrypted[middle + 1 :]

    with pytest.raises(InvalidToken):
        cipher.decrypt(tampered)
