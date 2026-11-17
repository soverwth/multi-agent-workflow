"""C1 regressions for server exceptions and complete Unicode string storage."""
from datetime import datetime, timezone
import sqlite3

import pytest
from werkzeug.exceptions import (
    BadGateway, BadRequest, Conflict, Forbidden, GatewayTimeout, HTTPException,
    InternalServerError, NotFound, ServiceUnavailable, Unauthorized,
)

from b04.reference_backend import create_app
from b04.reference_backend.contracts import ApiError
from b04.reference_backend.repository import SCHEMA, SQLiteUnitOfWork
from .support import CLAIM_KEYS, LOST, LOST_KEYS, USER_KEYS, database_state, error, ok, publish


@pytest.mark.parametrize('failure', [InternalServerError, BadGateway, ServiceUnavailable, GatewayTimeout])
@pytest.mark.parametrize('operation', ['register', 'update_me', 'publish_lost', 'create_claim'])
def test_server_http_errors_after_mutation_remain_500_and_roll_back(env, alice, bob, monkeypatch, failure, operation):
    item = publish(env, alice)
    method, path, actor, body, store_method = {
        'register': ('POST', '/auth/register', None, {'account': 'fresh_user', 'password': 'new password', 'nickname': 'Fresh'}, 'add_user'),
        'update_me': ('PATCH', '/me', alice, {'nickname': 'Changed'}, 'update_nickname'),
        'publish_lost': ('POST', '/lost-items', alice, LOST, 'add_lost'),
        'create_claim': ('POST', f"/lost-items/{item['id']}/claims", bob, {'statement': 'Mine'}, 'add_claim'),
    }[operation]
    original = getattr(SQLiteUnitOfWork, store_method)
    before = database_state(env)

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise failure('private SQL password and stack must not escape')

    monkeypatch.setattr(SQLiteUnitOfWork, store_method, fail_after_write)
    response = env.client.open('/api/v1' + path, method=method, headers=actor.headers if actor else {}, json=body)
    error(response, 500, 'INTERNAL_ERROR')
    assert database_state(env) == before
    assert all(word not in response.get_data(as_text=True) for word in ['private SQL', 'password', 'stack'])


@pytest.mark.parametrize('failure', [HTTPException, Conflict])
def test_unclassified_http_exceptions_do_not_invent_a_c1_client_error(env, monkeypatch, failure):
    def fail(*args):
        raise failure('private adapter failure')
    monkeypatch.setattr(env.app.extensions['b04_reference_backend'].lost, 'search', fail)
    response = env.client.get('/api/v1/lost-items')
    error(response, 500, 'INTERNAL_ERROR')
    assert 'private adapter' not in response.get_data(as_text=True)


@pytest.mark.parametrize('failure,status,code', [
    (BadRequest, 400, 'INVALID_FIELD'), (Unauthorized, 401, 'UNAUTHENTICATED'),
    (Forbidden, 403, 'FORBIDDEN'), (NotFound, 404, 'NOT_FOUND'),
])
def test_known_http_errors_preserve_c1_semantics(env, monkeypatch, failure, status, code):
    def fail(*args):
        raise failure('private transport detail')
    monkeypatch.setattr(env.app.extensions['b04_reference_backend'].lost, 'search', fail)
    response = env.client.get('/api/v1/lost-items')
    error(response, status, code)
    assert 'private transport' not in response.get_data(as_text=True)


@pytest.mark.parametrize('code,field', [
    ('DUPLICATE_ACCOUNT', 'account'), ('DUPLICATE_CLAIM', 'lost_item_id'), ('INVALID_STATE', 'status'),
])
def test_typed_c1_domain_conflicts_stay_distinct(env, monkeypatch, code, field):
    def fail(*args):
        raise ApiError(code, field)
    monkeypatch.setattr(env.app.extensions['b04_reference_backend'].lost, 'search', fail)
    error(env.client.get('/api/v1/lost-items'), 409, code, field)


def mutation(env, alice, bob, operation, value):
    if operation == 'register_nickname':
        return env.client.post('/api/v1/auth/register', json={'account': 'nul_register', 'password': 'test password', 'nickname': value})
    if operation == 'update_nickname':
        return env.client.patch('/api/v1/me', headers=alice.headers, json={'nickname': value})
    if operation == 'statement':
        item = publish(env, alice)
        return env.client.post(f"/api/v1/lost-items/{item['id']}/claims", headers=bob.headers, json={'statement': value})
    return env.client.post('/api/v1/lost-items', headers=alice.headers, json={**LOST, operation: value})


@pytest.mark.parametrize('operation', ['register_nickname', 'update_nickname', 'name', 'description', 'location', 'statement'])
@pytest.mark.parametrize('value', ['\x00A', 'A\x00B', 'A\x00', '\x00'])
def test_c1_text_with_nul_is_preserved_in_response_storage_and_reads(env, alice, bob, operation, value):
    response = mutation(env, alice, bob, operation, value)
    field = 'nickname' if operation.endswith('nickname') else operation
    keys = USER_KEYS if field == 'nickname' else CLAIM_KEYS if field == 'statement' else LOST_KEYS
    result = ok(response, 200 if operation == 'update_nickname' else 201, keys)
    assert result[field] == value
    if field == 'nickname':
        if operation == 'register_nickname':
            login = ok(env.client.post('/api/v1/auth/login', json={'account': 'nul_register', 'password': 'test password'}))
            headers = {'Authorization': 'Bearer ' + login['token']}
        else:
            headers = alice.headers
        assert ok(env.client.get('/api/v1/me', headers=headers))['nickname'] == value
        with env.repo.transaction() as tx:
            assert tx.user(result['id'])['nickname'] == value
    elif field == 'statement':
        assert ok(env.client.get('/api/v1/me/claims', headers=bob.headers))['items'] == [result]
        with env.repo.transaction() as tx:
            assert tx.claim(result['lost_item_id'], bob.id)['statement'] == value
    else:
        assert ok(env.client.get('/api/v1/lost-items/' + result['id']))[field] == value
        with env.repo.transaction() as tx:
            assert tx.lost(result['id'])[field] == value


@pytest.mark.parametrize('field,maximum', [('nickname', 30), ('name', 80), ('description', 1000), ('location', 120), ('statement', 500)])
def test_nul_counts_towards_c1_character_limits_and_rejections_do_not_write(env, alice, bob, field, maximum):
    valid = '\x00' + '文' * (maximum - 1)
    operation = 'update_nickname' if field == 'nickname' else field
    assert ok(mutation(env, alice, bob, operation, valid), 200 if field == 'nickname' else 201)[field] == valid
    # Keep the claim subject fixed: this comparison includes all business rows.
    if field == 'statement':
        item = publish(env, alice)
        path = f"/api/v1/lost-items/{item['id']}/claims"
    before = database_state(env)
    invalid = valid + '多'
    if field == 'statement':
        response = env.client.post(path, headers=bob.headers, json={'statement': invalid})
    else:
        response = mutation(env, alice, bob, operation, invalid)
    error(response, 400, 'INVALID_FIELD', field)
    assert database_state(env) == before


@pytest.mark.parametrize('field,maximum,table', [('nickname', 30, 'users'), ('name', 80, 'lost_items'), ('description', 1000, 'lost_items'), ('location', 120, 'lost_items'), ('statement', 500, 'claim_applications')])
def test_database_length_constraints_are_not_disabled_or_bypassed_by_nul(env, alice, bob, field, maximum, table):
    item = publish(env, alice)
    application = ok(env.client.post(f"/api/v1/lost-items/{item['id']}/claims", headers=bob.headers, json={'statement': 'Mine'}), 201)
    row_id = alice.id if table == 'users' else application['id'] if table == 'claim_applications' else item['id']
    before = database_state(env)
    for invalid in ['', 'A\x00' + '文' * (maximum - 1)]:
        with pytest.raises(sqlite3.IntegrityError):
            with env.repo.transaction(write=True) as tx:
                tx.db.execute(f'UPDATE {table} SET {field}=? WHERE id=?', (invalid, row_id))
        assert database_state(env) == before


def test_nul_remains_literal_in_search_and_location(env, alice):
    item = publish(env, alice, name='Before\x00After', description='Nul\x00description', location='\x00Library')
    publish(env, alice, name='Before', description='Other', location='Library')
    for query in [{'keyword': '\x00After'}, {'keyword': '\x00description'}, {'location': '\x00Library'}]:
        assert ok(env.client.get('/api/v1/lost-items', query_string=query))['items'] == [item]


def test_account_and_time_grammars_are_not_relaxed_for_nul(env, alice):
    before = database_state(env)
    error(env.client.post('/api/v1/auth/register', json={'account': 'a\x00bc', 'password': 'test password', 'nickname': 'Valid'}), 400, 'INVALID_FIELD', 'account')
    error(env.client.post('/api/v1/lost-items', headers=alice.headers, json={**LOST, 'lost_at': '2026-11-12T00:00:00Z\x00'}), 400, 'INVALID_FIELD', 'lost_at')
    assert database_state(env) == before


def test_nul_password_is_not_truncated_or_removed(env):
    ok(env.client.post('/api/v1/auth/register', json={'account': 'nul_password', 'password': 'pass\x00word', 'nickname': 'Valid'}), 201)
    ok(env.client.post('/api/v1/auth/login', json={'account': 'nul_password', 'password': 'pass\x00word'}))
    error(env.client.post('/api/v1/auth/login', json={'account': 'nul_password', 'password': 'password'}), 401, 'UNAUTHENTICATED')


def test_existing_reference_database_works_without_rebuild_or_global_sqlite_changes(tmp_path):
    path = tmp_path / 'legacy-reference.sqlite3'
    with sqlite3.connect(path) as legacy:
        legacy.executescript(SCHEMA)
        old_schema = legacy.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name").fetchall()
        assert legacy.execute('SELECT length(?)', ('\x00A',)).fetchone()[0] == 0
    for _ in range(2):
        app = create_app(database_path=path, clock=lambda: datetime(2026, 11, 17, tzinfo=timezone.utc))
        repo = app.extensions['b04_reference_backend'].repository
        try:
            client = app.test_client()
            if _ == 0:
                ok(client.post('/api/v1/auth/register', json={'account': 'legacy_user', 'password': 'test password', 'nickname': '\x00A'}), 201)
            session = ok(client.post('/api/v1/auth/login', json={'account': 'legacy_user', 'password': 'test password'}))
            assert session['user']['nickname'] == '\x00A'
            with repo.transaction() as tx:
                assert tx.db.execute('SELECT length(?)', ('\x00A',)).fetchone()[0] == 2
                assert [tuple(row) for row in tx.db.execute("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name")] == old_schema
        finally:
            repo.close()
    with sqlite3.connect(path) as independent:
        assert independent.execute('SELECT length(?)', ('\x00A',)).fetchone()[0] == 0
