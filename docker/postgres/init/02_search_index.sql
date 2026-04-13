CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS rag;

CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE TEXT SEARCH CONFIGURATION simple_unaccent (COPY = simple);
ALTER TEXT SEARCH CONFIGURATION simple_unaccent
    ALTER MAPPING FOR hword, hword_part, word
    WITH unaccent, simple;

CREATE TABLE rag.procedure_search_index (
    ma_thu_tuc      VARCHAR(50) PRIMARY KEY
                    REFERENCES rag.thu_tuc(ma_thu_tuc)
                    ON DELETE CASCADE,
    ten_thu_tuc     TEXT NOT NULL,
    search_text     TEXT NOT NULL,
    search_tsv      TSVECTOR NOT NULL
                    GENERATED ALWAYS AS (
                        setweight(to_tsvector('simple_unaccent', coalesce(ten_thu_tuc, '')), 'A') ||
                        setweight(to_tsvector('simple_unaccent', coalesce(search_text, '')), 'B')
                    ) STORED,
    embedding       vector(768) NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);