-- A small table never reaches autovacuum's threshold (50 changes), so `source` and `document` keep
-- no statistics, and the planner then reads every chunk through `chunk_document_id_idx` to find the
-- `ready` ones: 9 s at 100,000 chunks, against 40 to 350 ms with statistics. `index_source` now
-- analyzes the three tables when a source ends `ready`; this does it once for an install that
-- indexed before 0006.
analyze source, document, chunk;
