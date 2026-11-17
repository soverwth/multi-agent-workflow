"""T05: atomic claim eligibility, ownership and duplicate enforcement."""
from uuid import uuid4

from .contracts import ApiError, fields, text, uuid_field, stamp, view, CLAIM_FIELDS
from .repository import DuplicateClaim


class Claims:
    def __init__(self, repository, auth, clock):
        self.repository, self.auth, self.clock = repository, auth, clock

    def create(self, identity, item_id, body):
        fields(body, ('statement',))
        item_id = uuid_field(item_id)
        statement = text(body['statement'], 'statement', 500)
        row = dict(id=str(uuid4()), lost_item_id=item_id, applicant_id=identity.user_id,
                   statement=statement, status='pending', created_at=stamp(self.clock()))
        try:
            with self.repository.transaction(write=True) as tx:
                self.auth.require_current(tx, identity)
                item = tx.lost(item_id)
                if not item:
                    raise ApiError('NOT_FOUND')
                if item['publisher_id'] == identity.user_id:
                    raise ApiError('FORBIDDEN')
                if item['status'] != 'waiting':
                    raise ApiError('INVALID_STATE', 'status')
                if tx.claim(item_id, identity.user_id):
                    raise ApiError('DUPLICATE_CLAIM', 'lost_item_id')
                tx.add_claim(row)
        except DuplicateClaim:
            raise ApiError('DUPLICATE_CLAIM', 'lost_item_id') from None
        return view(row, CLAIM_FIELDS)
