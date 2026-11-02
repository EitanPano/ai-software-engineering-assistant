-- The template's reference `module` table is gone with its API; dropping the table drops its index.
-- Nothing reads its rows. Forward-only: recreate it from 0001-init.sql's text if it is ever needed.
drop table module;
