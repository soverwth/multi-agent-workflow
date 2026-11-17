-- 案例 T02 迁移 003：ClaimApplication
CREATE TABLE IF NOT EXISTS claim_applications (
    id           TEXT PRIMARY KEY,
    lost_item_id TEXT NOT NULL REFERENCES lost_items(id),
    applicant_id TEXT NOT NULL REFERENCES users(id),
    statement    TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('pending')),
    created_at   TEXT NOT NULL,
    UNIQUE (lost_item_id, applicant_id)
);
