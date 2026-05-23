-- depends: 0004_file_type

ALTER TABLE files ADD COLUMN thumbnail_custom INTEGER NOT NULL DEFAULT 0
    CHECK (thumbnail_custom IN (0, 1));
