-- The eval module owns `eval_case` and `eval_run`: the labelled questions retrieval is measured on,
-- and one row per measurement. A label is never a chunk id (every index mints new ones): it is
-- lines of a file at a pinned commit, and a case runs only against a `ready` source indexed at
-- that commit. A run stores ranks, cosines, its questions, its corpus and its settings, never a
-- hit's content.
create table eval_case (
  id text primary key,
  -- The full commit the expected chunks' lines hold at.
  pinned_commit text not null check (pinned_commit ~ '^[0-9a-f]{40}$'),
  kind text not null check (kind in ('identifier', 'paraphrase', 'no_answer')),
  question text not null,
  -- A JSON array of { path, startLine, endLine }: empty exactly for a no_answer case.
  expected_chunk jsonb not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  check (jsonb_typeof(expected_chunk) = 'array'),
  check ((kind = 'no_answer') = (jsonb_array_length(expected_chunk) = 0))
);

-- A seed upserts on this, so two seeds of one file cannot collide.
create unique index eval_case_pinned_commit_question_idx on eval_case (pinned_commit, question);

create table eval_run (
  id text primary key,
  status text not null check (status in ('queued', 'running', 'completed', 'failed')),
  error_code text check (
    error_code is null
    or error_code in ('no_runnable_case', 'search_unavailable', 'interrupted', 'internal')
  ),
  case_count integer not null default 0,
  skipped_case_count integer not null default 0,
  incomplete_case_count integer not null default 0,
  -- Empty until the run completes.
  scores jsonb not null default '[]',
  case_result jsonb not null default '[]',
  -- Null until the run completes.
  cosine jsonb,
  -- Written when the run starts: the ready sources it searched and the settings it searched with.
  corpus jsonb not null default '[]',
  settings jsonb,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

-- The list pages by (created_at, id), newest first.
create index eval_run_created_at_id_idx on eval_run (created_at, id);

-- One run at a time: a second active row violates this, which the error handler answers as a 409.
-- The same index serves the boot sweep's scan of runs a lost process left active.
create unique index eval_run_one_active_idx on eval_run ((true))
  where status in ('queued', 'running');
