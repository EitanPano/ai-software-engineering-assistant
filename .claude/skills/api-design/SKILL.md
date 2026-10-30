---
name: api-design
description: Add or change an API endpoint, its request schemas, or the generated OpenAPI contract. Use when a plan has a Contract section, when adding a server module, when choosing a path, method, status code or response shape, when a list needs pagination, when an endpoint needs the caller, or when the frontend needs new types. Covers REST conventions, the module shape, validation and gates in the router, and crossing a module boundary.
---

# API Design

The rules are in `AGENTS.md`; the layer map, the import table, the worked example and the
engine seam are in the server package's `AGENTS.md` (`backend/AGENTS.md` in a generated
project); this skill is the procedure.

## Conventions

- Resource paths are singular and flat: `/api/post`, `/api/post/{id}`,
  `/api/post/{id}/comment`. No verbs in paths; an action that is not CRUD is a sub-resource
  (`POST /api/order/{id}/cancellation`).
- Methods: `GET` (read, idempotent), `POST` (create or non-idempotent action), `PATCH`
  (partial update), `PUT` (full replace, rarely), `DELETE`.
- Status: `200` read/update, `201` create (body is the created entity), `204` delete with
  no body, and the error table from the `error-handling` skill.
- JSON only. Timestamps are ISO 8601 strings in UTC, converted from the stored date value
  by the layer that maps records to responses. Ids are strings.
- Lists return `{ items: T[], nextCursor: string | null }` and accept `?cursor=&limit=`
  (`limit` 1-100, default 20) through the package's pagination helpers. No offset
  pagination. The data layer decodes and encodes the cursor, because what it holds is its
  decision: the sort key and the id, fetched as `limit + 1` rows after the cursor so the
  extra row proves there is a next page. A bad cursor is a validation failure. The index
  behind it is in the `database` skill.
- Validation is declared once, from the module's schema: a `validate` middleware in the
  router (Express) or the handler's typed parameters (FastAPI). It parses the request parts
  the endpoint reads, and the handler reads them typed. A failure is always the same 400
  envelope, naming the part (`invalid body`) and the fields. `backend/AGENTS.md › Adding a
  module` shows the spelling.
- Rate limits are declared in the router, ahead of validation, so a 429 does not wait for
  parsing. Each endpoint has its own entry in the package's policy constants (never
  literals in a router) and so never shares another endpoint's bucket. The subject of the
  limit is hashed into the store key, never stored in clear.
- Every endpoint's errors are declared in its OpenAPI registration, so the frontend's
  generated types know them.

## Module shape

A module is a directory under the server package's `api/`, singular name, mounted at
`/api/<name>`. It has the files it needs:

- `routes`: the router. The gates (rate limit, auth, roles; middleware in Express,
  dependencies in FastAPI) are declared here and nowhere else, and so is Express's
  `validate` middleware (FastAPI validates from the handler's typed parameters); each
  endpoint is one line naming its handler. No logic.
- `controller`: the handlers and the exported rules that are the module's only public API.
  A handler reads typed input, applies the rules, maps records to response shapes and
  sends the status. A rule is a typed function with no request or response in it.
- `schema`: the leaf. It validates requests, types responses and registers the contract.
  A schema for a shape declared in `models/` is held to that type by the type checker.
- `service`: the private queries, only when the module has data of its own.

Order of work: types in `models/<name>/` → `schema` → test, red → `service` → `controller`
→ `routes` → the mount line and the registration line → `contract` → `check`. Start by
copying the shipped reference module and its `models/` directory and renaming `module` →
`<name>`; drop the files the module does not need.

The file names, the helpers and the worked example are in `backend/AGENTS.md › Adding a
module`. Logic in a `routes` file beyond declaring gates, validating and naming the
handler is a review finding; business logic belongs in the controller, queries in the
service.

## Crossing a module boundary

A module's public API is the rules its controller exports. Another module, a job, a
subscriber or a script calls those and nothing else of the module: never its service,
router or storage mapping. The language's tool refuses the import; a flow that spans modules
composes controllers.

- Signatures: a scalar identifier is positional (`getPost(id)`); anything else is one
  object with named parts (`listPost({ query })`, `createPost({ input, caller })`), so
  adding a part never changes an operation's shape.
- Types cross everywhere, behaviour only through controllers: any module file may import
  another module's schema as a type; only a controller or a schema imports it as a value.
- A rule forwards the caller it received to every rule it calls; each callee authorizes. A
  public operation simply takes no caller. An operation that skips the authorization a
  caller would get (a job; a webhook after its adapter verified the signature) is a
  separate, named system operation, never a fallback for a missing caller.
- Each rule call is its own unit of work, so a cross-module flow is not atomic. A flow that
  must be atomic lives inside one module: a transaction belongs to that module's
  controller, which calls its service inside it.
- No cycles: `auth → user → auth` is forbidden. Lift the shared operation into one of the
  two modules or a third. A module calling two or more other modules' controllers is a
  prompt to look.
- A controller propagates a callee's error unchanged and may raise its own for a
  composition rule (a `conflict` between two modules' answers). Neither a controller nor a
  router builds an error body: the error handler does.
- Events are published from a controller; handlers run detached, so a test that observes a
  reaction waits for them to drain (`writing-tests` skill).

## Auth and the caller

A server template ships authentication behind its `auth` flag; a product starts from it.
`.doc/architecture.md` (Auth) states the model and `backend/AGENTS.md` (Authentication)
says where its rules live. When that section says Auth: none, every endpoint is public, no
caller or role exists, and the rules below apply once a plan adds accounts. The gate and
helper names are in `backend/AGENTS.md › Adding a module`.

- The route gate is declarative and fails fast: no valid credentials is 401, a wrong role
  is 403 (a role gate authenticates first). An optional-auth endpoint mounts the resolver
  that never rejects and leaves no caller when credentials are absent or invalid.
- The handler still checks the caller, so an endpoint mounted without its gate fails
  closed. A rule that takes a caller acts only on that caller's own data; authorization
  failures are `forbidden`, and ownership compares the caller with the record.
- An operation without a caller is a system operation and is named so. Only other
  modules, jobs and scripts call it; no router does.
- Access tokens are short-lived and stateless, valid until expiry even after logout.
  Refresh tokens are kept as a hash in a session record and rotated on every use; the
  replay of the previous token within a short grace window is a concurrent retry and
  receives the token the first rotation issued; any other replay revokes every session of
  the user. The model is recorded in `.doc/architecture.md`; it changes only by plan.
- A new unauthenticated write endpoint gets its own rate-limit entry.
- Every protected endpoint has a test that answers 401 without credentials and, for a role
  gate, 403 with the wrong role. In a multi-tenant product the controller passes the owner
  scope into every data-layer call; the data layer never guesses it.

## Contract flow

1. The plan's Contract table is the agreement.
2. The backend implements it, mounts and registers the module in the one place the package
   names, and runs the server's `contract` command, which produces the OpenAPI document (a
   test fails when it is stale).
3. The frontend runs its `contract` command, which regenerates its types from that
   document. A read goes in the entity's loader (`entity/<noun>/server/<noun>.ts` in Next,
   `entity/<noun>/api/<noun>.ts` in an SPA) and a mutation in the feature
   (`feature/<action>/server/action.ts`, or `api/` in an SPA); both call the typed client in
   `shared/api/generated/` through `call`, so the result is typed, including the error
   envelope. A form schema extends the generated zod schema (`zod.gen`); a limit is never
   copied from the backend. The frontend never hand-writes an API type.
4. Both generated files are committed in the same task. A breaking change to a response
   shape is a new plan, not a silent edit.
