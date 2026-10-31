-- Hybrid search over `chunk`: full-text, trigram and vector search, fused by RRF in one statement
-- (`api/source/service.py › search_chunks`). Plan 004 left these to the search task.
create extension if not exists pg_trgm;

-- Stored, not virtual: Postgres 18 makes a generated column virtual by default and refuses an index
-- on one. `simple`, not `english`: stemming breaks an identifier.
alter table chunk
  add column keyword tsvector generated always as (to_tsvector('simple', content)) stored;

create index chunk_keyword_idx on chunk using gin (keyword);

-- Finds an identifier inside a dotted call, which full-text search reads as one other word.
create index chunk_content_trgm_idx on chunk using gin (content gin_trgm_ops);

create index chunk_embedding_idx on chunk using hnsw (embedding halfvec_cosine_ops);
