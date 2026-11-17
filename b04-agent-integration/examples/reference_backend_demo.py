"""TC-FLOW using the C1 WSGI endpoints and a temporary reference database."""
from pathlib import Path
import json
import tempfile

from b04.reference_backend import create_app


def main():
    with tempfile.TemporaryDirectory(prefix='b04-c1-demo-') as root:
        app = create_app(database_path=Path(root)/'reference.sqlite3')
        client = app.test_client()
        def call(method, path, status=200, token=None, **kwargs):
            headers = {'Authorization':'Bearer '+token} if token else {}
            response = client.open('/api/v1'+path, method=method, headers=headers, **kwargs)
            assert response.status_code == status, response.get_json()
            return response.get_json()['data']
        try:
            users = []
            for account in ['publisher_01', 'applicant_02']:
                call('POST','/auth/register',201,json=dict(account=account,password='demo password',nickname=account))
                users.append(call('POST','/auth/login',json=dict(account=account,password='demo password')))
            publisher, applicant = [u['token'] for u in users]
            item = call('POST','/lost-items',201,token=publisher,json=dict(name='Umbrella',description='Demo item',location='Library',lost_at='2026-11-12T11:20:00+08:00'))
            assert call('GET','/lost-items?keyword=UMBRELLA')['items'] == [item]
            application = call('POST',f"/lost-items/{item['id']}/claims",201,token=applicant,json={'statement':'Demo ownership statement'})
            assert call('GET','/me/claims',token=applicant)['items'] == [application]
            assert call('GET','/me/lost-items',token=publisher)['items'] == [item]
            call('PATCH','/me',token=applicant,json={'nickname':'Updated nickname'})
            call('POST','/auth/logout',token=applicant)
            print(json.dumps(dict(contract='C1',tasks=['T03','T04','T05'],transport='in-process WSGI',persistence='actual temporary SQLite',
                                  lost_at=item['lost_at'],lost_status=item['status'],claim_status=application['status'],result='passed'),indent=2))
        finally:
            app.extensions['b04_reference_backend'].repository.close()


if __name__ == '__main__':
    main()
