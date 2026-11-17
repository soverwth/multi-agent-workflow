-- 案例 T02 迁移 002：LostItem
CREATE TABLE IF NOT EXISTS lost_items (
    id          TEXT PRIMARY KEY,
    publisher_id TEXT NOT NULL REFERENCES users(id),
    name        TEXT NOT NULL,
    description TEXT NOT NULL,
    location    TEXT NOT NULL,
    lost_at     TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('waiting')),
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lost_location ON lost_items(location);
