-- depends: 0002_soft_delete

ALTER TABLE users ADD COLUMN token_issued_at TEXT;
