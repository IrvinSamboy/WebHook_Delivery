from relay.domain.api_keys import generate_api_key, hash_api_key, prefix_of, verify_api_key


def test_la_key_generada_empieza_por_su_prefijo():
    api_key, prefix = generate_api_key()

    assert prefix.startswith("whr_")
    assert prefix_of(api_key) == prefix


def test_el_prefijo_cabe_en_la_columna():
    _, prefix = generate_api_key()

    assert len(prefix) <= 20


def test_verifica_la_key_correcta():
    api_key, _ = generate_api_key()

    assert verify_api_key(api_key, hash_api_key(api_key)) is True


def test_rechaza_una_key_con_el_prefijo_correcto_y_otro_secreto():
    api_key, prefix = generate_api_key()

    assert verify_api_key(f"{prefix}.otro-secreto", hash_api_key(api_key)) is False


def test_cada_key_es_distinta():
    assert generate_api_key()[0] != generate_api_key()[0]
