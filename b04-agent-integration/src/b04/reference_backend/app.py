"""C1 HTTP adapter. Authentication precedes parsing on every protected route."""
from __future__ import annotations

import json
from types import SimpleNamespace

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .auth_profile import AuthProfile
from .claims import Claims
from .contracts import ApiError, query, utc_now
from .lost import LostItems
from .repository import SQLiteRepository


class C1Flask(Flask):
    def trap_http_exception(self, error):
        # Flask normally returns code-less proxy HTTPExceptions verbatim,
        # potentially as HTML/200. Unexpected port failures must remain C1 JSON.
        # Leave normal routing redirects and coded exception dispatch intact.
        return error.code is None or super().trap_http_exception(error)


def _json_body():
    if not request.is_json:
        raise ApiError('INVALID_FIELD')
    def pairs(values):
        result = {}
        for key, value in values:
            try:
                key.encode('utf-8')
            except UnicodeError:
                raise ApiError('INVALID_FIELD') from None
            if key in result:
                raise ApiError('INVALID_FIELD', key)
            result[key] = value
        return result
    try:
        body = json.loads(request.get_data().decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError):
        raise ApiError('INVALID_FIELD') from None
    if type(body) is not dict:
        raise ApiError('INVALID_FIELD')
    return body


def _query(allowed=()):
    return query(request.args.to_dict(flat=False), allowed)


def _no_body():
    if request.get_data():
        raise ApiError('INVALID_FIELD')


def _reply(data, status=200):
    return jsonify(ok=True, data=data), status


def create_app(*, database_path=':memory:', repository=None, clock=utc_now):
    app = C1Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False
    app.config['MAX_CONTENT_LENGTH'] = 64 * 1024
    repo = repository if repository is not None else SQLiteRepository(database_path)
    auth = AuthProfile(repo, clock)
    lost, claims = LostItems(repo, auth, clock), Claims(repo, auth, clock)
    app.extensions['b04_reference_backend'] = SimpleNamespace(repository=repo, auth=auth, lost=lost, claims=claims)

    def identity():
        return auth.authenticate(request.headers.get('Authorization'))

    @app.errorhandler(ApiError)
    def api_error(error):
        return jsonify(error.response()), error.status

    @app.errorhandler(HTTPException)
    def transport_error(error):
        # Only known request/auth/routing errors have a C1 client meaning.
        # A generic HTTP conflict cannot identify which C1 domain conflict
        # occurred; adapters must raise the corresponding ApiError instead.
        client_errors = {
            400: 'INVALID_FIELD', 401: 'UNAUTHENTICATED', 403: 'FORBIDDEN',
            404: 'NOT_FOUND', 405: 'INVALID_FIELD',
            413: 'INVALID_FIELD', 415: 'INVALID_FIELD',
        }
        fault = ApiError(client_errors.get(error.code, 'INTERNAL_ERROR'))
        return jsonify(fault.response()), fault.status

    @app.errorhandler(Exception)
    def unexpected(error):
        # Transactions roll back in Repository; neither credentials nor stack
        # traces are included in client JSON, even when a downstream port fails.
        fault = ApiError('INTERNAL_ERROR')
        return jsonify(fault.response()), fault.status

    @app.post('/api/v1/auth/register')
    def register():
        _query()
        return _reply(auth.register(_json_body()), 201)

    @app.post('/api/v1/auth/login')
    def login():
        _query()
        return _reply(auth.login(_json_body()))

    @app.post('/api/v1/auth/logout')
    def logout():
        actor = identity()
        _query(); _no_body()
        return _reply(auth.logout(actor))

    @app.get('/api/v1/me')
    def get_me():
        actor = identity()
        _query(); _no_body()
        return _reply(auth.get_me(actor))

    @app.patch('/api/v1/me')
    def update_me():
        actor = identity()
        _query()
        return _reply(auth.update_me(actor, _json_body()))

    @app.get('/api/v1/me/lost-items')
    def list_my_posts():
        actor = identity()
        values = _query(('page', 'page_size')); _no_body()
        return _reply(auth.list_my_posts(actor, values))

    @app.get('/api/v1/me/claims')
    def list_my_claims():
        actor = identity()
        values = _query(('page', 'page_size')); _no_body()
        return _reply(auth.list_my_claims(actor, values))

    @app.post('/api/v1/lost-items')
    def publish_lost():
        actor = identity()
        _query()
        return _reply(lost.publish(actor, _json_body()), 201)

    @app.get('/api/v1/lost-items')
    def search_lost():
        values = _query(('keyword', 'location', 'page', 'page_size')); _no_body()
        return _reply(lost.search(values))

    @app.get('/api/v1/lost-items/<item_id>')
    def get_lost(item_id):
        _query(); _no_body()
        return _reply(lost.get(item_id))

    @app.post('/api/v1/lost-items/<item_id>/claims')
    def create_claim(item_id):
        actor = identity()
        _query()
        return _reply(claims.create(actor, item_id, _json_body()), 201)

    return app
