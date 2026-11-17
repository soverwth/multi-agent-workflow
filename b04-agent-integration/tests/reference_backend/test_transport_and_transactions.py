from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta

import pytest

from b04.reference_backend import create_app
from b04.reference_backend.repository import SQLiteUnitOfWork
from .support import ok,error,publish,database_state,LOST,USER_KEYS,LOST_KEYS,CLAIM_KEYS


@pytest.mark.parametrize('raw',['','{','[]','null','"text"','1','true','{"account":NaN}','{"account":"a","account":"b"}','{"nickname":"\\ud800"}'])
def test_bad_json_and_nonobjects_are_structured_errors(env,raw):
    before=database_state(env)
    response=env.client.post('/api/v1/auth/register',data=raw,content_type='application/json')
    assert response.status_code==400 and response.is_json
    assert response.get_json()['error']['code'] in {'INVALID_FIELD','REQUIRED_FIELD'}
    assert database_state(env)==before


@pytest.mark.parametrize('method,path,body',[('GET','/me',None),('PATCH','/me',{}),('POST','/auth/logout',None),('GET','/me/lost-items',None),('GET','/me/claims',None),('POST','/lost-items',{}),('POST','/lost-items/bad/claims',{})])
def test_every_protected_endpoint_authenticates_before_query_and_body(env,method,path,body):
    response=env.client.open('/api/v1'+path+'?unexpected=true',method=method,json=body)
    error(response,401,'UNAUTHENTICATED')


@pytest.mark.parametrize('method,path',[('GET','/me'),('GET','/me/lost-items'),('GET','/me/claims'),('POST','/auth/logout')])
def test_unlisted_body_rejected_on_bodyless_routes(env,alice,method,path):
    error(env.client.open('/api/v1'+path,method=method,headers=alice.headers,json={}),400,'INVALID_FIELD')


@pytest.mark.parametrize('path,query,field',[('/lost-items','publisher_id=forged','publisher_id'),('/lost-items','keyword=a&keyword=b','keyword'),('/lost-items','page=1&page=2','page'),('/me/claims','applicant_id=forged','applicant_id')])
def test_unknown_or_duplicate_query_params_are_rejected(env,alice,path,query,field):
    error(env.client.get('/api/v1'+path+'?'+query,headers=alice.headers),400,'INVALID_FIELD',field)


@pytest.mark.parametrize('content_type',['text/plain','application/x-www-form-urlencoded'])
def test_non_json_content_type_is_rejected(env,content_type):
    error(env.client.post('/api/v1/auth/register',data='{}',content_type=content_type),400,'INVALID_FIELD')


def test_unknown_body_fields_are_not_silently_accepted_on_authentication(env):
    body=dict(account='normal_01',password='test pass',nickname='Test',phone='private')
    error(env.client.post('/api/v1/auth/register',json=body),400,'INVALID_FIELD','phone')
    error(env.client.post('/api/v1/auth/login',json={'account':'normal_01','password':'test pass','remember':True}),400,'INVALID_FIELD','remember')


@pytest.mark.parametrize('method',['add_user','update_nickname','add_lost'])
def test_partial_mutations_rollback_in_each_backend_module(env,alice,monkeypatch,method):
    before=database_state(env);original=getattr(SQLiteUnitOfWork,method)
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('private password_hash stack')
    monkeypatch.setattr(SQLiteUnitOfWork,method,fail)
    if method=='add_user':response=env.client.post('/api/v1/auth/register',json=dict(account='another_01',password='test pass',nickname='Test'))
    elif method=='update_nickname':response=env.client.patch('/api/v1/me',headers=alice.headers,json={'nickname':'modified'})
    else:response=env.client.post('/api/v1/lost-items',headers=alice.headers,json=LOST)
    error(response,500,'INTERNAL_ERROR')
    assert 'password_hash' not in response.get_data(as_text=True) and database_state(env)==before


def test_session_rechecked_inside_write_after_initial_authentication(env,alice,monkeypatch):
    backend=env.app.extensions['b04_reference_backend'];original=backend.lost.publish
    def revoke_then_publish(identity,body):
        backend.auth.logout(identity)
        return original(identity,body)
    monkeypatch.setattr(backend.lost,'publish',revoke_then_publish)
    before=database_state(env)
    error(env.client.post('/api/v1/lost-items',headers=alice.headers,json=LOST),401,'UNAUTHENTICATED')
    assert database_state(env)==before


def test_concurrent_duplicate_registration_is_case_insensitive(env):
    other=create_app(database_path=env.path,clock=lambda:env.clock.now);barrier=Barrier(2)
    def post(pair):
        app,account=pair
        with app.test_client() as client:
            barrier.wait(timeout=5)
            return client.post('/api/v1/auth/register',json=dict(account=account,password='test pass',nickname='Test'))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(post,[(env.app,'User_ABC'),(other,'USER_abc')]))
        assert sorted(r.status_code for r in results)==[201,409]
        error(next(r for r in results if r.status_code==409),409,'DUPLICATE_ACCOUNT','account')
    finally:other.extensions['b04_reference_backend'].repository.close()


def test_database_unique_account_exception_is_mapped(env,alice,monkeypatch):
    monkeypatch.setattr(SQLiteUnitOfWork,'user_by_account',lambda *args:None)
    error(env.client.post('/api/v1/auth/register',json=dict(account='ALICE_01',password='test pass',nickname='Test')),409,'DUPLICATE_ACCOUNT','account')


def test_reference_data_and_revocation_persist_across_app_restart(env,alice):
    item=publish(env,alice)
    assert ok(env.client.post('/api/v1/auth/logout',headers=alice.headers)) is None
    env.repo.close()
    other=create_app(database_path=env.path,clock=lambda:env.clock.now)
    try:
        client=other.test_client()
        assert ok(client.get('/api/v1/lost-items/'+item['id']))==item
        error(client.get('/api/v1/me',headers=alice.headers),401,'UNAUTHENTICATED')
    finally:other.extensions['b04_reference_backend'].repository.close()


def test_full_flow_and_maximum_field_lengths_are_supported(env):
    # TC-FLOW: the whole path uses actual HTTP handlers and SQLite, not mocks.
    account='a'*64;password=' p'+('x'*125)+' '
    profile=ok(env.client.post('/api/v1/auth/register',json=dict(account=account,password=password,nickname='名'*30)),201,USER_KEYS)
    login=ok(env.client.post('/api/v1/auth/login',json=dict(account=account,password=password)))
    headers={'Authorization':'Bearer '+login['token']}
    item=ok(env.client.post('/api/v1/lost-items',headers=headers,json={**LOST,'name':'名'*80,'description':'描'*1000,'location':'地'*120}),201,LOST_KEYS)
    from .conftest import user
    other=user(env.client,'other_00')
    assert ok(env.client.get('/api/v1/lost-items',query_string={'keyword':'名'*80}))['items']==[item]
    application=ok(env.client.post(f"/api/v1/lost-items/{item['id']}/claims",headers=other.headers,json={'statement':'申'*500}),201,CLAIM_KEYS)
    assert ok(env.client.get('/api/v1/me/claims',headers=other.headers))['items']==[application]
    assert ok(env.client.get('/api/v1/me/lost-items',headers=headers))['items']==[item]
