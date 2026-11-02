-- GitHub's official MCP server as the second `mcp_server`, and the pin that makes a third party's
-- tools an admin's decision. Additive: the column is nullable and the old code ignores it.

-- What an admin accepted (`accept_mcp_server`): the tools a third-party server may offer, each with
-- the description and schema the admin read. `tool_definition` stays the last listing. Null until
-- an accept; every server but `knowledge` offers nothing while it is null.
alter table mcp_server add column pinned_tool_definition jsonb;

-- A server with no address of its own is `knowledge` or `github`, whose addresses are environment
-- variables (a row's url would be a second place to set them). Rebuilt under the same name.
alter table mcp_server drop constraint mcp_server_url_check;
alter table mcp_server add constraint mcp_server_url_check
  check (name in ('knowledge', 'github') or url is not null);

-- Disabled and unpinned, so nothing is listed or offered until a person runs `accept_mcp_server
-- github`. A run for an install with no GitHub token behaves as it did.
insert into mcp_server (id, name, url, enabled, tool_definition, pinned_tool_definition, created_at, updated_at)
values ('github', 'github', null, false, null, null, now(), now());

-- Reads run at once, the two writes wait for a person's approval. A tool of the server that is not
-- named here has no row, which is a deny. No policy is edited by hand.
insert into tool_policy (id, mcp_server_id, tool_name, effect, created_at, updated_at)
values
  ('github-get_file_contents', 'github', 'get_file_contents', 'allow', now(), now()),
  ('github-issue_read', 'github', 'issue_read', 'allow', now(), now()),
  ('github-list_issues', 'github', 'list_issues', 'allow', now(), now()),
  ('github-pull_request_read', 'github', 'pull_request_read', 'allow', now(), now()),
  ('github-list_pull_requests', 'github', 'list_pull_requests', 'allow', now(), now()),
  ('github-issue_write', 'github', 'issue_write', 'ask', now(), now()),
  ('github-add_issue_comment', 'github', 'add_issue_comment', 'ask', now(), now());
