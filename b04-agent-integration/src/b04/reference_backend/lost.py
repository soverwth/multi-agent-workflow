"""T04: publish, search and public details under the C1 product contract."""
from uuid import uuid4

from .contracts import (ApiError, fields, text, lost_time, uuid_field, stamp,
                        pagination, filters, view, page_view, LOST_FIELDS)


class LostItems:
    def __init__(self, repository, auth, clock):
        self.repository, self.auth, self.clock = repository, auth, clock

    def publish(self, identity, body):
        fields(body, ('name', 'description', 'location', 'lost_at'))
        row = dict(id=str(uuid4()), publisher_id=identity.user_id, name=text(body['name'], 'name', 80),
                   description=text(body['description'], 'description', 1000), location=text(body['location'], 'location', 120),
                   lost_at=lost_time(body['lost_at']), status='waiting', created_at=stamp(self.clock()))
        with self.repository.transaction(write=True) as tx:
            self.auth.require_current(tx, identity)
            tx.add_lost(row)
        return view(row, LOST_FIELDS)

    def search(self, values):
        page, size = pagination(values)
        with self.repository.transaction() as tx:
            rows, total = tx.list_lost(page, size, **filters(values))
        return page_view(rows, page, size, total, LOST_FIELDS)

    def get(self, item_id):
        item_id = uuid_field(item_id)
        with self.repository.transaction() as tx:
            row = tx.lost(item_id)
            if not row:
                raise ApiError('NOT_FOUND')
        return view(row, LOST_FIELDS)
