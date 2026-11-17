from uuid import UUID


LOST = dict(name='黑色 Umbrella', description='Silver handle, 编号 100%_[]', location='图书馆', lost_at='2026-11-12T11:20:00.000+08:00')
USER_KEYS = {'id','account','nickname','created_at'}
LOST_KEYS = {'id','name','description','location','lost_at','status','created_at'}
CLAIM_KEYS = {'id','lost_item_id','statement','status','created_at'}


def ok(response, status=200, keys=None):
    assert response.status_code == status, response.get_json()
    body = response.get_json()
    assert set(body) == {'ok','data'} and body['ok'] is True
    if keys is not None:
        assert set(body['data']) == keys
    return body['data']


def error(response, status, code, field=None):
    assert response.status_code == status, response.get_json()
    body = response.get_json()
    assert set(body) == {'ok','error'} and body['ok'] is False
    assert set(body['error']) == {'code','field','message'}
    assert body['error']['code'] == code and body['error']['field'] == field
    assert isinstance(body['error']['message'], str) and body['error']['message']
    return body['error']


def publish(env, owner, **overrides):
    return ok(env.client.post('/api/v1/lost-items', headers=owner.headers, json={**LOST,**overrides}),201,LOST_KEYS)


def database_state(env):
    # Business rows only; compare every byte/field, not merely record counts.
    with env.repo.transaction() as tx:
        return {table:[tuple(r) for r in tx.db.execute(f'SELECT * FROM {table} ORDER BY id')] for table in ['users','lost_items','claim_applications']}


def is_uuid(value):
    assert str(UUID(value)) == value
