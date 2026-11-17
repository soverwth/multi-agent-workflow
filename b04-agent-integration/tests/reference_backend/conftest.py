from datetime import datetime, timezone
from types import SimpleNamespace
import pytest

from b04.reference_backend import create_app


@pytest.fixture
def env(tmp_path):
    clock = SimpleNamespace(now=datetime(2026, 11, 17, 3, 20, 0, 123456, tzinfo=timezone.utc))
    path = tmp_path/'b04-reference.sqlite3'
    app = create_app(database_path=path, clock=lambda: clock.now)
    repo = app.extensions['b04_reference_backend'].repository
    yield SimpleNamespace(app=app, client=app.test_client(), repo=repo, clock=clock, path=path)
    repo.close()


@pytest.fixture
def alice(env):
    return user(env.client, 'Alice_01')


@pytest.fixture
def bob(env):
    return user(env.client, 'Bob_02')


def user(client, account, password='test pass 123'):
    registered = client.post('/api/v1/auth/register', json=dict(account=account, password=password, nickname=account))
    assert registered.status_code == 201, registered.get_json()
    logged = client.post('/api/v1/auth/login', json=dict(account=account, password=password))
    assert logged.status_code == 200, logged.get_json()
    data = logged.get_json()['data']
    return SimpleNamespace(id=data['user']['id'], token=data['token'], headers={'Authorization':'Bearer '+data['token']}, profile=registered.get_json()['data'])
