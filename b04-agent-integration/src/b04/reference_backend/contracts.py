"""C1 validation and public projections. No persistence or workflow state."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from uuid import UUID


ERROR_STATUS = {
    'REQUIRED_FIELD': 400, 'INVALID_FIELD': 400, 'UNAUTHENTICATED': 401,
    'FORBIDDEN': 403, 'NOT_FOUND': 404, 'DUPLICATE_ACCOUNT': 409,
    'DUPLICATE_CLAIM': 409, 'INVALID_STATE': 409, 'INTERNAL_ERROR': 500,
}
MESSAGES = {
    'REQUIRED_FIELD': '缺少必填字段', 'INVALID_FIELD': '字段或请求格式无效',
    'UNAUTHENTICATED': '身份凭据无效', 'FORBIDDEN': '无权执行此操作',
    'NOT_FOUND': '对象不存在', 'DUPLICATE_ACCOUNT': '账号已存在',
    'DUPLICATE_CLAIM': '已申请认领此失物', 'INVALID_STATE': '失物当前不可认领',
    'INTERNAL_ERROR': '服务内部错误',
}
USER_FIELDS = ('id', 'account', 'nickname', 'created_at')
LOST_FIELDS = ('id', 'name', 'description', 'location', 'lost_at', 'status', 'created_at')
CLAIM_FIELDS = ('id', 'lost_item_id', 'statement', 'status', 'created_at')


class ApiError(Exception):
    def __init__(self, code: str, field: str | None = None):
        super().__init__(code)
        self.code, self.field, self.status = code, field, ERROR_STATUS[code]

    def response(self):
        return {'ok': False, 'error': {'code': self.code, 'field': self.field, 'message': MESSAGES[self.code]}}


def fields(body: dict, required: tuple[str, ...]):
    if type(body) is not dict:
        raise ApiError('INVALID_FIELD')
    for key in body:
        if key not in required:
            try:
                key.encode('utf-8')
            except (UnicodeError, AttributeError):
                raise ApiError('INVALID_FIELD') from None
            raise ApiError('INVALID_FIELD', key)
    for key in required:
        if key not in body:
            raise ApiError('REQUIRED_FIELD', key)


def text(value, field: str, maximum: int, minimum: int = 1, *, trim=True):
    if type(value) is not str:
        raise ApiError('INVALID_FIELD', field)
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise ApiError('INVALID_FIELD', field) from None
    value = value.strip() if trim else value
    if not minimum <= len(value) <= maximum:
        raise ApiError('INVALID_FIELD', field)
    return value


def account(value):
    value = text(value, 'account', 64, 3)
    if not re.fullmatch('[A-Za-z0-9_]+', value):
        raise ApiError('INVALID_FIELD', 'account')
    return value.lower()


def password(value):
    return text(value, 'password', 128, 8, trim=False)


def uuid_field(value, field='id'):
    if type(value) is not str or not re.fullmatch(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}', value):
        raise ApiError('INVALID_FIELD', field)
    return str(UUID(value))


def utc_now():
    return datetime.now(timezone.utc)


def stamp(value: datetime):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Clock must return an aware datetime')
    return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def lost_time(value):
    value = value.strip() if type(value) is str else value
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?(?:Z|[+-]\d{2}:\d{2})', value, flags=re.ASCII):
        raise ApiError('INVALID_FIELD', 'lost_at')
    try:
        # datetime.fromisoformat normalizes e.g. +08:60; reject those first.
        if value[-1] != 'Z' and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
            raise ValueError('Offset')
        return stamp(datetime.fromisoformat(value.replace('Z', '+00:00')))
    except (ValueError, OverflowError):
        raise ApiError('INVALID_FIELD', 'lost_at') from None


def query(query_values: dict[str, list[str]], allowed):
    result = {}
    for key, values in query_values.items():
        if key not in allowed or len(values) != 1:
            raise ApiError('INVALID_FIELD', key)
        result[key] = values[0]
    return result


def pagination(values):
    result = []
    for key, default, maximum in [('page', 1, None), ('page_size', 20, 100)]:
        value = values.get(key, str(default))
        if type(value) is not str or not re.fullmatch('[0-9]+', value.strip()):
            raise ApiError('INVALID_FIELD', key)
        try:
            number = int(value)
        except ValueError:
            raise ApiError('INVALID_FIELD', key) from None
        if number < 1 or maximum is not None and number > maximum:
            raise ApiError('INVALID_FIELD', key)
        result.append(number)
    return tuple(result)


def filters(values):
    # Search text is a literal substring, not a regex/LIKE pattern.
    return {k: values.get(k, '').strip() for k in ['keyword', 'location']}


def view(row, names):
    return {key: row[key] for key in names}


def page_view(rows, page, page_size, total, names):
    return {'items': [view(row, names) for row in rows], 'page': page, 'page_size': page_size, 'total': total}
