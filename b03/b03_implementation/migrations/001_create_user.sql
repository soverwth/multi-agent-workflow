-- 案例 T02 迁移 001：User
-- 约束来源：主文档 2.2.2 / 2.2.3
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    account       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    nickname      TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
