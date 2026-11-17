from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from b04.reference_backend import create_app
from b04.reference_backend.repository import SQLiteUnitOfWork
from .support import ok,error,publish,CLAIM_KEYS,database_state


def claim(env, who, item, **body):
    return env.client.post(f"/api/v1/lost-items/{item['id']}/claims",headers=who.headers,json=body or {'statement':'这是我的物品'})


def test_TC_C01_other_user_claim_duplicate_and_own_lists(env,alice,bob):
    item=publish(env,alice);before=database_state(env)
    application=ok(claim(env,bob,item),201,CLAIM_KEYS)
    assert application['status']=='pending' and application['lost_item_id']==item['id']
    with env.repo.transaction() as tx:
        stored=tx.claim(item['id'],bob.id)
        assert stored['applicant_id']==bob.id and tx.lost(item['id'])['status']=='waiting'
    after=database_state(env)
    error(claim(env,bob,item),409,'DUPLICATE_CLAIM','lost_item_id')
    error(claim(env,alice,item),403,'FORBIDDEN')
    assert database_state(env)==after
    assert ok(env.client.get('/api/v1/me/claims',headers=bob.headers))['items']==[application]
    assert ok(env.client.get('/api/v1/me/claims',headers=alice.headers))['items']==[]


@pytest.mark.parametrize('value',[None,'',' \n ',True,12,[],{},'x'*501])
def test_statement_validation_does_not_write(env,alice,bob,value):
    item=publish(env,alice);before=database_state(env)
    error(claim(env,bob,item,statement=value),400,'INVALID_FIELD','statement')
    assert database_state(env)==before


@pytest.mark.parametrize('field',['id','lost_item_id','applicant_id','status','created_at'])
def test_claim_ownership_and_metadata_cannot_be_supplied(env,alice,bob,field):
    item=publish(env,alice);before=database_state(env)
    error(claim(env,bob,item,statement='mine',**{field:'forged'}),400,'INVALID_FIELD',field)
    assert database_state(env)==before


def test_claim_fields_and_authentication_precede_existence_checks(env,bob):
    missing=str(uuid4())
    error(env.client.post('/api/v1/lost-items/not-uuid/claims',json={}),401,'UNAUTHENTICATED')
    error(env.client.post(f'/api/v1/lost-items/{missing}/claims',headers=bob.headers,json={}),400,'REQUIRED_FIELD','statement')
    error(env.client.post('/api/v1/lost-items/not-uuid/claims',headers=bob.headers,json={'statement':'mine'}),400,'INVALID_FIELD','id')
    error(env.client.post(f'/api/v1/lost-items/{missing}/claims',headers=bob.headers,json={'statement':'mine'}),404,'NOT_FOUND')


def set_upstream_state(env,item,state):
    # This fixture simulates an incompatible/legacy upstream object. It is not
    # a new API, status transition, or permission to change the T02 module.
    env.repo._db.execute('PRAGMA ignore_check_constraints=ON')
    try:env.repo._db.execute('UPDATE lost_items SET status=? WHERE id=?',(state,item['id']))
    finally:env.repo._db.execute('PRAGMA ignore_check_constraints=OFF')


def test_non_waiting_rejected_and_permission_state_duplicate_priority(env,alice,bob):
    item=publish(env,alice);ok(claim(env,bob,item),201)
    set_upstream_state(env,item,'legacy_closed')
    before=database_state(env)
    error(claim(env,alice,item),403,'FORBIDDEN')
    error(claim(env,bob,item),409,'INVALID_STATE','status')
    assert database_state(env)==before


def test_concurrent_duplicate_claim_across_two_app_instances(env,alice,bob):
    item=publish(env,alice)
    other=create_app(database_path=env.path,clock=lambda:env.clock.now)
    barrier=Barrier(2)
    def post(app):
        with app.test_client() as client:
            barrier.wait(timeout=5)
            return client.post(f"/api/v1/lost-items/{item['id']}/claims",headers=bob.headers,json={'statement':'mine'})
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(post,[env.app,other]))
        assert sorted(r.status_code for r in results)==[201,409]
        error(next(r for r in results if r.status_code==409),409,'DUPLICATE_CLAIM','lost_item_id')
        with env.repo.transaction() as tx:
            assert tx.db.execute('SELECT count(*) FROM claim_applications').fetchone()[0]==1
    finally:other.extensions['b04_reference_backend'].repository.close()


def test_database_unique_constraint_is_mapped_even_if_precheck_misses(env,alice,bob,monkeypatch):
    item=publish(env,alice);ok(claim(env,bob,item),201);before=database_state(env)
    monkeypatch.setattr(SQLiteUnitOfWork,'claim',lambda *args:None)
    error(claim(env,bob,item),409,'DUPLICATE_CLAIM','lost_item_id')
    assert database_state(env)==before


def test_insert_then_unexpected_failure_rolls_back_entire_claim_transaction(env,alice,bob,monkeypatch):
    item=publish(env,alice);before=database_state(env);original=SQLiteUnitOfWork.add_claim
    def fail_after_insert(tx,row):
        original(tx,row)
        raise RuntimeError('private-db-password internal stack')
    monkeypatch.setattr(SQLiteUnitOfWork,'add_claim',fail_after_insert)
    result=claim(env,bob,item)
    error(result,500,'INTERNAL_ERROR')
    assert 'private-db-password' not in result.get_data(as_text=True) and database_state(env)==before


def test_my_claims_paging_order_and_end_page(env,alice,bob):
    applications=[ok(claim(env,bob,publish(env,alice,name=str(i))),201) for i in range(3)]
    ordered=sorted(applications,key=lambda x:(x['created_at'],x['id']),reverse=True)
    data=ok(env.client.get('/api/v1/me/claims?page=2&page_size=1',headers=bob.headers))
    assert data['items']==[ordered[1]] and data['total']==3
    data=ok(env.client.get('/api/v1/me/claims?page=4&page_size=1',headers=bob.headers))
    assert data['items']==[] and data['total']==3
