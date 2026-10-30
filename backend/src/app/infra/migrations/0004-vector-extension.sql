-- pgvector for the retrieval tasks. `if not exists` lets a managed database's privileged role
-- create the extension first; the bundled `app` role is a superuser.
create extension if not exists vector;
