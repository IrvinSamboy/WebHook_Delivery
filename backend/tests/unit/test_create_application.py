from fakes import FakeClock, FakeUnitOfWork
from relay.application.use_cases.create_application import CreateApplication
from relay.domain.api_keys import verify_api_key


def test_crea_la_aplicacion_con_una_key_que_funciona():
    uow = FakeUnitOfWork()

    application, plain_key = CreateApplication(uow, FakeClock()).execute("Mi tienda")

    assert uow.applications.items == [application]
    assert application.name == "Mi tienda"
    stored = uow.api_keys.items[0]
    assert stored.app_id == application.id
    assert verify_api_key(plain_key, stored.key_hash) is True
    assert uow.committed is True


def test_no_guarda_la_key_en_claro():
    uow = FakeUnitOfWork()

    _, plain_key = CreateApplication(uow, FakeClock()).execute("Mi tienda")

    stored = uow.api_keys.items[0]
    assert plain_key not in (stored.key_hash, stored.prefix)
    _, _, secret = plain_key.partition(".")
    assert secret not in stored.key_hash
