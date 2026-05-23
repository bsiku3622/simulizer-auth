-- depends: 0003_token_invalidation

ALTER TABLE files ADD COLUMN type TEXT NOT NULL DEFAULT 'blockfile'
    CHECK (type IN ('blockfile', 'clangfile'));
