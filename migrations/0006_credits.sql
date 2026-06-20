-- depends: 0005_thumbnail_custom

ALTER TABLE users ADD COLUMN credits INTEGER NOT NULL DEFAULT 0
    CHECK (credits >= 0);
