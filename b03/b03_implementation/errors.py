"""B03 领域错误类型；错误码与 HTTP 映射参照主文档 C1。"""


class B03Error(Exception):
    code = "INTERNAL_ERROR"
    http_status = 500


class VersionConflict(B03Error):
    """CAS 的期望版本与当前版本不一致。"""

    code = "VERSION_CONFLICT"
    http_status = 409


class LeaseConflict(B03Error):
    """资源已被有效租约占用。"""

    code = "LEASE_CONFLICT"
    http_status = 409


class StaleCallback(B03Error):
    """回调的 attempt/snapshot 与当前尝试不匹配。"""

    code = "STALE_CALLBACK"
    http_status = 409


class InvalidSnapshot(B03Error):
    """输入快照无效或不存在。"""

    code = "INVALID_SNAPSHOT"
    http_status = 409


class RequiredField(B03Error):
    code = "REQUIRED_FIELD"
    http_status = 400


class InvalidField(B03Error):
    code = "INVALID_FIELD"
    http_status = 400


class Unauthenticated(B03Error):
    code = "UNAUTHENTICATED"
    http_status = 401


class Forbidden(B03Error):
    code = "FORBIDDEN"
    http_status = 403


class NotFound(B03Error):
    code = "NOT_FOUND"
    http_status = 404


class DuplicateAccount(B03Error):
    code = "DUPLICATE_ACCOUNT"
    http_status = 409


class DuplicateClaim(B03Error):
    code = "DUPLICATE_CLAIM"
    http_status = 409


class InvalidState(B03Error):
    code = "INVALID_STATE"
    http_status = 409
