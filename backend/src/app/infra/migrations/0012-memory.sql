-- The memory module owns `memory`: a durable fact a person stated, extracted after a completed run
-- and recalled by the agent for that person alone. Additive: a new table and one policy row the old
-- code ignores.
-- `user_id` and `conversation_id` are plain text, not references: modules are independent, and what
-- becomes of a memory when its conversation is deleted is the conversation-delete task's decision.
create table memory (
  id text primary key,
  user_id text not null,
  conversation_id text not null,
  content text not null,
  embedding halfvec(1024) not null,
  created_at timestamptz not null
);

-- The list pages by (created_at, id), newest first, one person's rows; recall scans the same rows.
-- There is no vector index on purpose: an exact scan of at most `MEMORY.max_per_user` rows is
-- complete, and an HNSW graph spans every person and filters after.
create index memory_user_created_at_id_idx on memory (user_id, created_at, id);

-- A fact already stored is not stored again (the insert is `on conflict do nothing`). The key is
-- the lowercased text; `MEMORY.fact_max_chars` keeps it far below a btree row's limit.
create unique index memory_user_content_idx on memory (user_id, lower(content));

-- Recall runs at once; it reads only the caller's rows and writes nothing. A tool of the server
-- that is not named here has no row, which is a deny.
insert into tool_policy (id, mcp_server_id, tool_name, effect, created_at, updated_at)
values ('knowledge-recall', 'knowledge', 'recall', 'allow', now(), now());
