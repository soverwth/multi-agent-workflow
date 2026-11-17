"""T03: password authentication, token lifecycle, profile and own records."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import re
import secrets
from uuid import uuid4

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError

from .contracts import (ApiError, fields, text, account, password, stamp,
                        view, page_view, pagination, USER_FIELDS, LOST_FIELDS, CLAIM_FIELDS)
from .repository import DuplicateAccount, Repository


def token_hash(token: str):
    return hashlib.sha256(token.encode('ascii')).hexdigest()


@dataclass(frozen=True)
class Identity:
    user_id: str
    token_hash: str


class AuthProfile:
    def __init__(self, repository: Repository, clock):
        self.repository, self.clock = repository, clock
        self.hasher = PasswordHasher(time_cost=2, memory_cost=19*1024, parallelism=1, salt_len=16, hash_len=32, type=Type.ID)
        self.dummy_hash = self.hasher.hash(secrets.token_urlsafe(32))

    def register(self, body):
        fields(body, ('account', 'password', 'nickname'))
        normalized = account(body['account'])
        secret = password(body['password'])
        nickname = text(body['nickname'], 'nickname', 30)
        row = dict(id=str(uuid4()), account=normalized, password_hash=self.hasher.hash(secret), nickname=nickname, created_at=stamp(self.clock()))
        try:
            with self.repository.transaction(write=True) as tx:
                if tx.user_by_account(normalized):
                    raise ApiError('DUPLICATE_ACCOUNT', 'account')
                tx.add_user(row)
        except DuplicateAccount:
            raise ApiError('DUPLICATE_ACCOUNT', 'account') from None
        return view(row, USER_FIELDS)

    def login(self, body):
        fields(body, ('account', 'password'))
        normalized, secret = account(body['account']), password(body['password'])
        # Password verification is outside the write lock; the hash is rechecked
        # inside the session-creation transaction to avoid using a changed user.
        with self.repository.transaction() as tx:
            user = tx.user_by_account(normalized)
        try:
            self.hasher.verify(user['password_hash'] if user else self.dummy_hash, secret)
        except VerifyMismatchError:
            raise ApiError('UNAUTHENTICATED') from None
        if not user:
            raise ApiError('UNAUTHENTICATED')
        token = secrets.token_urlsafe(32)
        created = datetime.fromisoformat(stamp(self.clock()).replace('Z', '+00:00'))
        expires = stamp(created + timedelta(hours=24))
        with self.repository.transaction(write=True) as tx:
            current = tx.user(user['id'])
            if not current or current['password_hash'] != user['password_hash']:
                raise ApiError('UNAUTHENTICATED')
            public_user = view(current, USER_FIELDS)
            tx.add_session(dict(token_hash=token_hash(token), user_id=user['id'], created_at=stamp(created), expires_at=expires))
        return dict(token=token, expires_at=expires, user=public_user)

    def authenticate(self, authorization):
        if type(authorization) is not str:
            raise ApiError('UNAUTHENTICATED')
        match = re.fullmatch(r'(?i:Bearer) ([A-Za-z0-9_-]{43})', authorization)
        if not match:
            raise ApiError('UNAUTHENTICATED')
        hashed = token_hash(match.group(1))
        with self.repository.transaction() as tx:
            session = tx.session(hashed)
            if not session:
                raise ApiError('UNAUTHENTICATED')
            identity = Identity(session['user_id'], hashed)
            self.require_current(tx, identity)
        return identity

    def require_current(self, tx, identity):
        session = tx.session(identity.token_hash)
        if (not session or session['user_id'] != identity.user_id or session['revoked_at'] is not None
                or session['expires_at'] <= stamp(self.clock())):
            raise ApiError('UNAUTHENTICATED')
        user = tx.user(identity.user_id)
        if not user:
            raise ApiError('UNAUTHENTICATED')
        return user

    def logout(self, identity):
        with self.repository.transaction(write=True) as tx:
            self.require_current(tx, identity)
            tx.revoke_session(identity.token_hash, stamp(self.clock()))
        return None

    def get_me(self, identity):
        with self.repository.transaction() as tx:
            return view(self.require_current(tx, identity), USER_FIELDS)

    def update_me(self, identity, body):
        fields(body, ('nickname',))
        nickname = text(body['nickname'], 'nickname', 30)
        with self.repository.transaction(write=True) as tx:
            self.require_current(tx, identity)
            return view(tx.update_nickname(identity.user_id, nickname), USER_FIELDS)

    def list_my_posts(self, identity, values):
        page, size = pagination(values)
        with self.repository.transaction() as tx:
            self.require_current(tx, identity)
            rows, total = tx.list_lost(page, size, publisher_id=identity.user_id)
            return page_view(rows, page, size, total, LOST_FIELDS)

    def list_my_claims(self, identity, values):
        page, size = pagination(values)
        with self.repository.transaction() as tx:
            self.require_current(tx, identity)
            rows, total = tx.list_claims(identity.user_id, page, size)
            return page_view(rows, page, size, total, CLAIM_FIELDS)
