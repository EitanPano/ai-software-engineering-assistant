-- A tool call whose policy says `ask` stops its run at `awaiting_approval` with no process waiting.
-- The run keeps the assistant turn and the results already known in `pending_turn` (never in
-- `message`: a stored `tool_use` is promised its result, and history is never edited). Each
-- waiting call is a `tool_call` row at `awaiting_approval` (`result` is '' until it ends) and an
-- `approval` row that binds a person's decision to the SHA-256 of the call's exact arguments.

-- `awaiting_approval` is an active status: the conversation's one active run still holds its
-- slot, so a send during a pause is the 409. The index is rebuilt under the same name.
alter table run drop constraint run_status_check;
alter table run add constraint run_status_check
  check (status in ('queued', 'running', 'awaiting_approval', 'completed', 'failed'));

drop index run_active_conversation_idx;
create unique index run_active_conversation_idx on run (conversation_id)
  where status in ('queued', 'running', 'awaiting_approval');

alter table run add column pending_turn jsonb;

alter table tool_call drop constraint tool_call_status_check;
alter table tool_call add constraint tool_call_status_check
  check (status in ('awaiting_approval', 'succeeded', 'failed', 'denied'));

-- One row per waiting call; `decision` is null until a person decides. A person's words are not
-- stored: a rejection reaches the model as a fixed text.
create table approval (
  id text primary key,
  run_id text not null references run (id) on delete cascade,
  tool_call_id text not null references tool_call (id) on delete cascade,
  user_id text not null,
  arguments_digest text not null,
  decision text check (decision in ('approved', 'rejected')),
  created_at timestamptz not null,
  decided_at timestamptz,
  constraint approval_tool_call_key unique (tool_call_id)
);

-- What still waits on a run: the last decision counts these.
create index approval_run_undecided_idx on approval (run_id) where decision is null;
