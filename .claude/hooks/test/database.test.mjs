// Destructive database operations: MongoDB, SQL clients, Redis, and the container exec path
// through which this harness reaches its database (`docker compose exec db …`).
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { shellVerdict } from './harness.mjs'

const label = options => (options?.tool ? ` [${options.tool}]` : '')

const blocks = (command, options) =>
  test(`blocks: ${command}${label(options)}`, () => {
    const verdict = shellVerdict(command, options)
    assert.equal(verdict.blocked, true, 'expected a block')
    assert.equal(verdict.hook, 'block-destructive-bash.mjs', `blocked by ${verdict.hook}: ${verdict.stderr}`)
  })

const passes = (command, options) =>
  test(`passes: ${command}${label(options)}`, () => {
    const verdict = shellVerdict(command, options)
    assert.equal(verdict.blocked, false, `unexpected block by ${verdict.hook}: ${verdict.stderr}`)
  })

// MongoDB: dropping a database or a collection, in method and command spelling.
for (const command of [
  'mongosh --eval "db.dropDatabase()"',
  'mongosh --eval "db.getSiblingDB(\'app\').dropDatabase()"',
  'mongo app --eval "db.dropDatabase()"',
  'mongosh --eval "db.adminCommand({ dropDatabase: 1 })"',
  'mongosh --eval "db.runCommand({ \\"dropDatabase\\": 1 })"',
  'mongosh --eval "db.post.drop()"',
  'mongosh --eval "db.getCollection(\'post\').drop()"',
  'mongosh --eval "db[\'post\'].drop ()"',
  'mongosh --eval "db.runCommand({ drop: \'post\' })"',
  'mongosh --eval "db.runCommand({drop:\'post\'})"',
  'mongosh --eval "db.runCommand({ \\"drop\\": \\"post\\" })"',
  'mongosh --eval "db.dropCollection(\'post\')"',
  'echo "db.post.drop()" | mongosh mongodb://localhost/app'
]) {
  blocks(command)
}

// MongoDB: deleting or overwriting every document (an empty or missing filter).
for (const command of [
  'mongosh --eval "db.post.deleteMany({})"',
  'mongosh --eval "db.post.deleteMany()"',
  'mongosh --eval "db.post.deleteMany( { } )"',
  'mongosh --eval "db.post.deleteMany({}, { writeConcern: { w: 1 } })"',
  'mongosh --eval "db.post.remove({})"',
  'mongosh --eval "db.post.updateMany({}, { $set: { archived: true } })"',
  'mongosh --eval "db.post.replaceOne({}, { title: \'x\' })"'
]) {
  blocks(command)
}

// MongoDB tools whose --drop flag drops the target before writing into it.
for (const command of [
  'mongorestore --drop dump/',
  'mongorestore --drop --uri mongodb://localhost/app dump/',
  'mongoimport --drop -c post data.json',
  'mongoimport --db app --collection post --drop --file data.json'
]) {
  blocks(command)
}

// MongoDB: reads, filtered writes and non-destructive admin stay allowed.
for (const command of [
  'mongosh --eval "db.post.find({})"',
  'mongosh --eval "db.post.countDocuments()"',
  'mongosh --eval "db.post.deleteMany({ status: \'draft\' })"',
  'mongosh --eval "db.post.deleteOne({ _id: 1 })"',
  'mongosh --eval "db.post.remove({ _id: 1 })"',
  'mongosh --eval "db.post.updateMany({ status: \'draft\' }, { $set: { archived: true } })"',
  'mongosh --eval "db.post.updateOne({}, { $set: { seen: true } })"',
  'mongosh --eval "db.post.insertOne({ title: \'x\' })"',
  'mongosh --eval "db.post.createIndex({ slug: 1 })"',
  'mongosh --eval "db.post.dropIndex(\'slug_1\')"',
  'mongosh --eval "db.stats()"',
  'mongosh --eval "db.post.find({ dropped: true })"',
  'mongodump --out dump/',
  'mongorestore dump/',
  'mongoimport -c post data.json',
  'grep -rn "deleteMany({})" backend/src',
  'git commit -m "fix(post): guard deleteMany({}) in the service"',
  'echo "db.post.drop()"'
]) {
  passes(command)
}

// SQL: every statement is judged on its own, so a WHERE elsewhere in the command does not
// excuse a DELETE or UPDATE that has none. A mass UPDATE overwrites every row.
for (const command of [
  'psql -c "DELETE FROM post; SELECT 1 WHERE true"',
  'psql -c "DELETE FROM post" -c "SELECT 1 WHERE true"',
  'psql -c "UPDATE post SET title = \'x\'"',
  'psql -c "update post set title = \'x\'; select 1 where true"',
  'mysql -e "TRUNCATE post"',
  'mysql -e "DROP DATABASE IF EXISTS app"',
  'psql -c "DROP SCHEMA public CASCADE"',
  'cqlsh -e "DROP KEYSPACE app"',
  'cqlsh -e "TRUNCATE post"',
  'duckdb app.db "DROP TABLE post"',
  'dropdb app',
  'dropdb --if-exists app',
  'mysqladmin drop app',
  'mysqladmin -u root drop app'
]) {
  blocks(command)
}

for (const command of [
  'psql -c "UPDATE post SET title = \'x\' WHERE id = 1"',
  'psql -c "DELETE FROM post WHERE id = 1; SELECT 1"',
  'psql -c "SELECT * FROM post WHERE title = \'DELETE FROM\'"',
  'psql -c "INSERT INTO post (id, title) VALUES (1, \'x\') ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title"',
  'psql -c "CREATE TABLE tag (post_id int REFERENCES post ON DELETE CASCADE ON UPDATE SET NULL)"',
  'psql -c "SELECT id FROM post FOR UPDATE"',
  'mysql -e "SELECT TRUNCATE(1.5, 0)"',
  'duckdb app.db "SELECT 1"',
  'createdb app',
  'mysqladmin status',
  'pg_dump app > dump.sql',
  'grep -rn "UPDATE post SET" backend/src'
]) {
  passes(command)
}

// Containers: the program a container runs is judged like a program on the host. This is the
// path to the database in this harness (`docker compose up -d --wait db`, then exec).
for (const command of [
  'docker compose exec db psql -U app -c "DROP TABLE post"',
  'docker compose exec -T db psql -c "TRUNCATE post"',
  'docker compose exec -e PGPASSWORD=x -u postgres db psql -c "DELETE FROM post"',
  'docker exec -it db psql -c "DROP TABLE post"',
  'docker compose run --rm db psql -c "DELETE FROM post"',
  'docker run --rm --network host postgres:17 psql -h localhost -c "DROP DATABASE app"',
  'docker-compose exec db psql -c "DROP TABLE post"',
  'docker compose exec mongo mongosh --eval "db.post.deleteMany({})"',
  'docker compose exec mongo mongosh --eval "db.dropDatabase()"',
  'docker compose exec cache redis-cli FLUSHALL',
  'docker run --rm redis redis-cli -h db flushdb',
  'docker compose exec db dropdb app',
  'docker compose exec mongo mongorestore --drop /dump',
  'docker compose exec backend rm -rf dist',
  'docker compose exec db bash -c "psql -c \'DROP TABLE post\'"',
  'docker compose exec backend bun run sh -c "rm -rf dist"',
  'bun run sh -c "rm -rf dist"',
  'podman exec db psql -c "DROP TABLE post"',
  'kubectl exec db-0 -- psql -c "DROP TABLE post"',
  'kubectl exec -n app -it db-0 -- mongosh --eval "db.post.drop()"'
]) {
  blocks(command)
}
blocks('docker compose exec db psql -c "DROP TABLE post"', { tool: 'PowerShell' })

for (const command of [
  'docker compose exec db psql -U app -c "SELECT 1"',
  'docker compose exec db psql -c "DELETE FROM post WHERE id = 1"',
  'docker compose exec db pg_dump app',
  'docker compose exec db pg_isready',
  'docker compose exec mongo mongosh --eval "db.post.find({})"',
  'docker compose exec cache redis-cli PING',
  'docker compose exec backend bun run check',
  'docker compose run --rm backend bun run migrate',
  'docker exec -it backend sh',
  'docker compose up -d --wait db',
  'docker compose logs db',
  'docker compose ps',
  'docker compose down',
  'kubectl exec db-0 -- psql -c "SELECT 1"',
  'kubectl get pods'
]) {
  passes(command)
}
