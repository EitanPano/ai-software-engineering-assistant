-- The source module owns `source`, `document` and `chunk`: a connected repository, its text files,
-- and the pieces of them that are embedded. `document` and `chunk` belong to their parent, so those
-- keys are real and cascade: clearing a source's earlier attempt is one delete.
-- No keyword column, no `pg_trgm` and no search index here: no query in this task needs them, so
-- they ship in the search task's migration. `vector` comes from 0004-vector-extension.sql.
create table source (
  id text primary key,
  -- GitHub's own spelling: https://github.com/<owner>/<repo>
  url text not null,
  -- The resolved ref: a requested one, or the repository's default branch.
  ref text not null,
  status text not null check (status in ('queued', 'indexing', 'ready', 'failed')),
  error_code text check (
    error_code is null
    or error_code in (
      'repository_unavailable',
      'repository_too_large',
      'embedding_unavailable',
      'interrupted',
      'internal'
    )
  ),
  -- The commit the last successful index read.
  indexed_commit text,
  document_count integer not null default 0,
  chunk_count integer not null default 0,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

-- One source per repository and ref: a second connect is a unique violation, which is a 409.
create unique index source_url_ref_idx on source (url, ref);

-- The list pages by (created_at, id), newest first.
create index source_created_at_id_idx on source (created_at, id);

-- The boot sweep's scan of sources a lost process left active.
create index source_active_status_idx on source (status) where status in ('queued', 'indexing');

create table document (
  id text primary key,
  source_id text not null references source (id) on delete cascade,
  -- The path from the repository root.
  path text not null,
  language text,
  created_at timestamptz not null
);

create unique index document_source_id_path_idx on document (source_id, path);

create table chunk (
  id text primary key,
  document_id text not null references document (id) on delete cascade,
  -- The definition the chunk is, when it is one.
  symbol text,
  start_line integer not null,
  end_line integer not null,
  content text not null,
  embedding halfvec(1024) not null,
  created_at timestamptz not null,
  check (start_line >= 1 and end_line >= start_line)
);

create index chunk_document_id_idx on chunk (document_id);
