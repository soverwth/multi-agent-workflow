import json
from pathlib import Path
from jsonschema import Draft202012Validator
from .support import LOST,publish


CONTRACT=json.loads(Path(__file__).with_name('c1_contract.json').read_text(encoding='utf-8'))


def test_all_eleven_c1_http_responses_against_frozen_independent_schemas(env,alice,bob):
    item=publish(env,alice)
    client=env.client
    login=client.post('/api/v1/auth/login',json={'account':'bob_02','password':'test pass 123'})
    responses={
        'register':client.post('/api/v1/auth/register',json={'account':'charlie_03','password':'test pass','nickname':'Charlie'}),
        'login':login,
        'get_me':client.get('/api/v1/me',headers=bob.headers),
        'update_me':client.patch('/api/v1/me',headers=bob.headers,json={'nickname':'Bob'}),
        'publish_lost':client.post('/api/v1/lost-items',headers=bob.headers,json=LOST),
        'get_lost':client.get('/api/v1/lost-items/'+item['id']),
        'search_lost':client.get('/api/v1/lost-items'),
        'create_claim':client.post(f"/api/v1/lost-items/{item['id']}/claims",headers=bob.headers,json={'statement':'mine'}),
        'list_my_posts':client.get('/api/v1/me/lost-items',headers=bob.headers),
        'list_my_claims':client.get('/api/v1/me/claims',headers=bob.headers),
        'logout':client.post('/api/v1/auth/logout',headers={'Authorization':'Bearer '+login.get_json()['data']['token']}),
    }
    assert set(responses)=={op['name'] for op in CONTRACT['operations']}
    for op in CONTRACT['operations']:
        response=responses[op['name']]
        assert response.status_code==op['status'],(op,response.get_json())
        schema={'type':'object','additionalProperties':False,'required':['ok','data'],
                'properties':{'ok':{'const':True},'data':{'$ref':'#/$defs/'+op['data']}},'$defs':CONTRACT['$defs']}
        Draft202012Validator(schema).validate(response.get_json())


def test_c1_route_and_error_mapping_inventory_matches_implementation(env):
    from b04.reference_backend.contracts import ERROR_STATUS
    assert ERROR_STATUS==CONTRACT['errors']
    expected={(op['method'],op['path']) for op in CONTRACT['operations']}
    actual={(method,str(rule).replace('<item_id>','{id}')) for rule in env.app.url_map.iter_rules() for method in rule.methods-{'HEAD','OPTIONS'}}
    assert actual==expected
