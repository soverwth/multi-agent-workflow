import pytest
from .support import LOST,LOST_KEYS,ok,error,publish,database_state


def test_TC_P01_publish_search_detail_preserves_input_moment_and_privacy(env,alice):
    item=publish(env,alice)
    assert item['lost_at']=='2026-11-12T03:20:00.000Z' and item['created_at']=='2026-11-17T03:20:00.123Z' and item['status']=='waiting'
    rows=ok(env.client.get('/api/v1/lost-items',query_string={'keyword':'UMBRELLA','location':'图书馆'}))
    assert rows=={'items':[item],'page':1,'page_size':20,'total':1}
    assert ok(env.client.get('/api/v1/lost-items/'+item['id']),keys=LOST_KEYS)==item
    assert not {'publisher_id','password','password_hash','phone','token'} & set(item)


def test_TC_P02_missing_lost_at_is_required_and_never_defaulted(env,alice):
    before=database_state(env);body={k:v for k,v in LOST.items() if k!='lost_at'}
    error(env.client.post('/api/v1/lost-items',headers=alice.headers,json=body),400,'REQUIRED_FIELD','lost_at')
    assert database_state(env)==before


@pytest.mark.parametrize('value',[None,'','   ','invalid','2026-11-12','2026-11-12T11:20:00','2026-02-29T00:00:00Z','2026-11-12T25:00:00Z',
    '2026-11-12T11:20:60Z','2026-11-12T11:20:00+08:60','2026-11-12T11:20:00+24:00',123,True,[],{},'2026-11-12T11:20:00.123456Z'])
def test_TC_P03_invalid_time_has_no_writes(env,alice,value):
    before=database_state(env)
    error(env.client.post('/api/v1/lost-items',headers=alice.headers,json={**LOST,'lost_at':value}),400,'INVALID_FIELD','lost_at')
    assert database_state(env)==before


@pytest.mark.parametrize('value,expected',[('2026-11-12T00:00:00Z','2026-11-12T00:00:00.000Z'),('2026-11-12T00:00:00.123-05:30','2026-11-12T05:30:00.123Z'),
    ('2024-02-29T00:00:00+08:00','2024-02-28T16:00:00.000Z'),(' 2026-11-12T00:00:00.000Z ','2026-11-12T00:00:00.000Z')])
def test_timezone_forms_are_normalized_to_utc_milliseconds(env,alice,value,expected):
    assert publish(env,alice,lost_at=value)['lost_at']==expected


@pytest.mark.parametrize('field,value',[('name',''),('name','x'*81),('name',None),('description','  '),('description','x'*1001),('description',12),('location',''),('location','x'*121),('location',[]),('publisher_id','forged'),('status','claimed'),('created_at','2020-01-01T00:00:00Z')])
def test_publish_boundaries_and_server_controlled_fields(env,alice,field,value):
    before=database_state(env)
    error(env.client.post('/api/v1/lost-items',headers=alice.headers,json={**LOST,field:value}),400,'INVALID_FIELD',field)
    assert database_state(env)==before


@pytest.mark.parametrize('field',['name','description','location'])
def test_publish_required_fields(env,alice,field):
    body=LOST.copy();del body[field]
    error(env.client.post('/api/v1/lost-items',headers=alice.headers,json=body),400,'REQUIRED_FIELD',field)


def test_search_empty_literal_contains_intersection_and_exact_location(env,alice):
    a=publish(env,alice,name='A_100% [Item]',description='SilVER');b=publish(env,alice,name='a different',description='Other handle',location='图书馆东门')
    for values in [{},{'keyword':'','location':'   '}]:assert ok(env.client.get('/api/v1/lost-items',query_string=values))['total']==2
    for keyword in ['silVER','_100%','[Item]']:
        result=ok(env.client.get('/api/v1/lost-items',query_string={'keyword':keyword}));assert result['items']==[a]
    assert ok(env.client.get('/api/v1/lost-items',query_string={'keyword':'.*'}))['total']==0
    assert ok(env.client.get('/api/v1/lost-items',query_string={'keyword':"' OR 1=1 --"}))['items']==[]
    assert ok(env.client.get('/api/v1/lost-items',query_string={'keyword':'different','location':'图书馆'}))['items']==[]
    assert ok(env.client.get('/api/v1/lost-items',query_string={'location':'  图书馆  '}))['items']==[a]


def test_search_and_personal_paging_stable_order_empty_last_page_and_huge_page(env,alice):
    items=[publish(env,alice,name=str(i)) for i in range(3)]
    ordered=sorted(items,key=lambda x:(x['created_at'],x['id']),reverse=True)
    for path,headers in [('/api/v1/lost-items',{}),('/api/v1/me/lost-items',alice.headers)]:
        assert ok(env.client.get(path,headers=headers,query_string={'page':2,'page_size':1}))['items']==[ordered[1]]
        for page in ['4',str(10**30)]:
            result=ok(env.client.get(path,headers=headers,query_string={'page':page,'page_size':1}))
            assert result['items']==[] and result['total']==3 and result['page']==int(page)


@pytest.mark.parametrize('field,value',[('page','0'),('page','-1'),('page','1.5'),('page',''),('page','null'),('page','true'),('page_size','0'),('page_size','101'),('page_size','2.0'),('page_size','')])
def test_pagination_errors_apply_to_all_lists(env,alice,field,value):
    for path,headers in [('/api/v1/lost-items',{}),('/api/v1/me/lost-items',alice.headers),('/api/v1/me/claims',alice.headers)]:
        error(env.client.get(path,headers=headers,query_string={field:value}),400,'INVALID_FIELD',field)


def test_uuid_errors_and_absent_detail(env):
    error(env.client.get('/api/v1/lost-items/not-a-uuid'),400,'INVALID_FIELD','id')
    error(env.client.get('/api/v1/lost-items/00000000-0000-0000-0000-000000000001'),404,'NOT_FOUND')
