from datetime import timedelta
import hashlib
import json

from argon2 import extract_parameters, Type
import pytest

from .conftest import user
from .support import ok,error,USER_KEYS,LOST_KEYS,CLAIM_KEYS,database_state,publish,is_uuid


def test_register_structure_argon2id_and_no_automatic_login(env):
    body = dict(account='  MiXeD_123  ', password=' space password ', nickname='  小汤  ')
    profile = ok(env.client.post('/api/v1/auth/register',json=body),201,USER_KEYS)
    is_uuid(profile['id'])
    assert profile['account']=='mixed_123' and profile['nickname']=='小汤'
    with env.repo.transaction() as tx:
        stored=tx.user(profile['id']);assert tx.db.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
    assert stored['password_hash'] != body['password'] and body['password'] not in json.dumps(profile)
    p=extract_parameters(stored['password_hash'])
    assert (p.type,p.memory_cost,p.time_cost,p.parallelism)==(Type.ID,19456,2,1) and p.salt_len>=16
    error(env.client.get('/api/v1/me'),401,'UNAUTHENTICATED')


def test_duplicate_accounts_casefold_and_salted_passwords(env,alice):
    before=database_state(env)
    error(env.client.post('/api/v1/auth/register',json=dict(account=' ALICE_01 ',password='test pass 123',nickname='other')),409,'DUPLICATE_ACCOUNT','account')
    assert database_state(env)==before
    another=user(env.client,'other_123')
    with env.repo.transaction() as tx:assert tx.user(alice.id)['password_hash'] != tx.user(another.id)['password_hash']


@pytest.mark.parametrize('field,value',[('account','ab'),('account','x'*65),('account','中文账号'),('account','Kaa'),('account','a-b'),('account',None),('account',123),
    ('nickname',''),('nickname','  '),('nickname','x'*31),('nickname',None),('password','x'*7),('password','x'*129),('password',123),('password',None)])
def test_registration_field_boundaries_do_not_write(env,field,value):
    body=dict(account='valid_user',password='valid pass',nickname='Name');body[field]=value
    before=database_state(env)
    error(env.client.post('/api/v1/auth/register',json=body),400,'INVALID_FIELD',field)
    assert database_state(env)==before


@pytest.mark.parametrize('field',['account','password','nickname'])
def test_registration_required_fields(env,field):
    body=dict(account='valid_user',password='valid pass',nickname='Name');del body[field]
    error(env.client.post('/api/v1/auth/register',json=body),400,'REQUIRED_FIELD',field)


def test_password_spaces_not_trimmed_and_sessions_are_unpredictable_and_hashed(env):
    user(env.client,'space_user',password=' 12345678 ')
    error(env.client.post('/api/v1/auth/login',json=dict(account='space_user',password='12345678')),401,'UNAUTHENTICATED')
    results=[ok(env.client.post('/api/v1/auth/login',json=dict(account='SPACE_USER',password=' 12345678 '))) for _ in range(2)]
    assert set(results[0])=={'token','expires_at','user'} and len(results[0]['token'])>=43 and results[0]['token']!=results[1]['token']
    with env.repo.transaction() as tx:
        row=tx.session(hashlib.sha256(results[0]['token'].encode()).hexdigest())
        assert row and results[0]['token'] not in json.dumps(row)
    assert results[0]['expires_at']=='2026-11-18T03:20:00.123Z'


@pytest.mark.parametrize('account,password',[('Alice_01','wrong password'),('unknown_00','test pass 123')])
def test_login_invalid_credentials_have_same_401_and_no_writes(env,alice,account,password):
    before=database_state(env)
    error(env.client.post('/api/v1/auth/login',json=dict(account=account,password=password)),401,'UNAUTHENTICATED')
    assert database_state(env)==before


def test_expiration_at_exact_24_hours(env,alice):
    env.clock.now += timedelta(hours=24)-timedelta(milliseconds=1)
    ok(env.client.get('/api/v1/me',headers=alice.headers),keys=USER_KEYS)
    env.clock.now += timedelta(milliseconds=1)
    error(env.client.get('/api/v1/me',headers=alice.headers),401,'UNAUTHENTICATED')


def test_logout_revokes_only_current_session(env,alice):
    second=ok(env.client.post('/api/v1/auth/login',json=dict(account='alice_01',password='test pass 123')))
    assert ok(env.client.post('/api/v1/auth/logout',headers=alice.headers)) is None
    error(env.client.get('/api/v1/me',headers=alice.headers),401,'UNAUTHENTICATED')
    error(env.client.post('/api/v1/auth/logout',headers=alice.headers),401,'UNAUTHENTICATED')
    ok(env.client.get('/api/v1/me',headers={'Authorization':'Bearer '+second['token']}))


@pytest.mark.parametrize('authorization',[None,'','Basic xxx','Bearer bad','Bearer '+'x'*43,'Bearer '+'é'*43])
def test_invalid_authentication_precedes_invalid_body_and_target(env,authorization):
    headers={} if authorization is None else {'Authorization':authorization}
    error(env.client.post('/api/v1/lost-items/not-a-uuid/claims',headers=headers,data='{malformed',content_type='application/json'),401,'UNAUTHENTICATED')


def test_get_update_and_own_lists_do_not_leak_other_users(env,alice,bob):
    own=publish(env,alice);other=publish(env,bob)
    ok(env.client.post(f"/api/v1/lost-items/{other['id']}/claims",headers=alice.headers,json={'statement':'自己的申请'}),201,CLAIM_KEYS)
    patched=ok(env.client.patch('/api/v1/me',headers=alice.headers,json={'nickname':' 新昵称 '}),keys=USER_KEYS)
    assert patched['nickname']=='新昵称'
    assert ok(env.client.get('/api/v1/me',headers=bob.headers))['nickname']==bob.profile['nickname']
    mine=ok(env.client.get('/api/v1/me/lost-items',headers=alice.headers))
    assert [x['id'] for x in mine['items']]==[own['id']] and set(mine['items'][0])==LOST_KEYS
    assert ok(env.client.get('/api/v1/me/claims',headers=bob.headers))['items']==[]
    assert len(ok(env.client.get('/api/v1/me/claims',headers=alice.headers))['items'])==1


@pytest.mark.parametrize('body',[{'nickname':'other','id':'forged'},{'nickname':'other','account':'hacked'},{'nickname':'other','password':'new pass'},{'nickname':None},{'nickname':'x'*31},{}])
def test_only_nickname_is_writable_and_rejections_leave_profile_unchanged(env,alice,body):
    before=database_state(env)
    response=env.client.patch('/api/v1/me',headers=alice.headers,json=body)
    assert response.status_code==400 and response.get_json()['error']['code'] in {'INVALID_FIELD','REQUIRED_FIELD'}
    assert database_state(env)==before


def test_client_cannot_choose_user_for_own_record_endpoints(env,alice,bob):
    for path in ['/api/v1/me','/api/v1/me/lost-items','/api/v1/me/claims']:
        error(env.client.get(path,headers=alice.headers,query_string={'user_id':bob.id}),400,'INVALID_FIELD','user_id')
