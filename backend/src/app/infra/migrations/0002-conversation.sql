-- The conversation module owns `conversation` and `message`, the run module `run` and `run_event`.
-- No foreign keys between modules (modules stay independent); `run_event` and `message` belong to
-- their own module's parent, so those keys are real.
create table conversation (
  id text primary key,
  user_id text not null,
  title text,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

-- The list pages by latest activity: (updated_at, id) among one user's conversations.
create index conversation_user_id_updated_at_id_idx on conversation (user_id, updated_at, id);

-- One row per API turn. `position` is the insertion order, so an assistant turn and its
-- tool_result turn written together never tie; `blocks` are the turn's content blocks as the API
-- returned them, and `text` is what the wire shows (text blocks only).
create table message (
  id text primary key,
  position bigint generated always as identity,
  conversation_id text not null references conversation (id) on delete cascade,
  run_id text,
  role text not null check (role in ('user', 'assistant', 'tool_result')),
  blocks jsonb not null,
  text text not null,
  created_at timestamptz not null
);

create unique index message_conversation_id_position_idx on message (conversation_id, position);

create table run (
  id text primary key,
  conversation_id text not null,
  user_id text not null,
  status text not null check (status in ('queued', 'running', 'completed', 'failed')),
  error_code text,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

-- One active run per conversation: a second send is a unique violation, which is a 409.
create unique index run_active_conversation_idx on run (conversation_id)
  where status in ('queued', 'running');

-- The latest run of a conversation, and the boot sweep's scan of active runs.
create index run_conversation_id_created_at_idx on run (conversation_id, created_at);
create index run_status_idx on run (status) where status in ('queued', 'running');

create table run_event (
  run_id text not null references run (id) on delete cascade,
  sequence integer not null,
  type text not null,
  payload jsonb not null,
  created_at timestamptz not null,
  primary key (run_id, sequence)
);
