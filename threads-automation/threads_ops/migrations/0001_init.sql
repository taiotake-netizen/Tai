-- Initial schema. All timestamps are UTC ISO-8601 strings ("YYYY-MM-DDTHH:MM:SS.ffffffZ").

CREATE TABLE accounts (
  id              TEXT PRIMARY KEY,
  platform        TEXT NOT NULL DEFAULT 'threads',
  display_name    TEXT NOT NULL,
  external_user_id TEXT,                 -- Threads user id (not a secret)
  token_env       TEXT,                  -- NAME of env var holding the access token (never the value)
  data_scope      TEXT NOT NULL DEFAULT 'live' CHECK (data_scope IN ('live','demo','test')),
  connection_status TEXT NOT NULL DEFAULT 'not_configured'
                  CHECK (connection_status IN ('not_configured','connected','error','expired')),
  connection_checked_at TEXT,
  connection_error TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);

CREATE TABLE account_settings (
  account_id  TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
  settings_json TEXT NOT NULL,
  version     INTEGER NOT NULL DEFAULT 1,   -- optimistic concurrency
  updated_at  TEXT NOT NULL,
  updated_by  TEXT NOT NULL
);

CREATE TABLE policy_versions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id  TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  version     INTEGER NOT NULL,
  parent_version INTEGER,
  policy_json TEXT NOT NULL,
  source      TEXT NOT NULL CHECK (source IN ('initial','auto','manual','rollback')),
  reason      TEXT NOT NULL,
  is_active   INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  created_by  TEXT NOT NULL,
  UNIQUE (account_id, version)
);
CREATE UNIQUE INDEX one_active_policy ON policy_versions(account_id) WHERE is_active = 1;

CREATE TABLE experiments (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id  TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  variable    TEXT NOT NULL,
  hypothesis  TEXT NOT NULL,
  control_value TEXT NOT NULL,
  treatment_value TEXT NOT NULL,
  base_policy_version INTEGER NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('running','adopted','rejected','inconclusive','stopped')),
  result_json TEXT,
  started_at  TEXT NOT NULL,
  ended_at    TEXT,
  adopted_policy_version INTEGER
);
CREATE UNIQUE INDEX one_running_experiment ON experiments(account_id) WHERE status = 'running';

CREATE TABLE ideas (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id  TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  theme       TEXT NOT NULL,
  pain        TEXT NOT NULL DEFAULT '',
  appeal      TEXT NOT NULL DEFAULT '',
  angle       TEXT NOT NULL DEFAULT '',
  notes       TEXT NOT NULL DEFAULT '',
  parent_idea_id INTEGER REFERENCES ideas(id),
  source_post_id INTEGER REFERENCES posts(id),
  origin      TEXT NOT NULL DEFAULT 'manual' CHECK (origin IN ('manual','ai_refill','derived','seed')),
  status      TEXT NOT NULL DEFAULT 'ready' CHECK (status IN ('draft','ready','reserved','used','held','retired')),
  reserved_by_post_id INTEGER,
  reserved_at TEXT,
  use_count   INTEGER NOT NULL DEFAULT 0,
  last_used_at TEXT,
  last_post_id INTEGER,
  is_test     INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX ideas_account_status ON ideas(account_id, status);

CREATE TABLE posts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id  TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  slot_at     TEXT NOT NULL,              -- planned publish time (UTC)
  status      TEXT NOT NULL CHECK (status IN (
                'planned','generating','awaiting_approval','scheduled','publishing',
                'published','unknown','failed','skipped','cancelled')),
  idea_id     INTEGER REFERENCES ideas(id),
  policy_version INTEGER,
  experiment_id INTEGER REFERENCES experiments(id),
  experiment_arm TEXT CHECK (experiment_arm IN ('control','treatment')),
  theme       TEXT,
  hook_style  TEXT,
  cta_key     TEXT,
  appeal      TEXT,
  length_target TEXT,
  structure   TEXT,
  text        TEXT,
  check_json  TEXT,
  generation_attempts INTEGER NOT NULL DEFAULT 0,
  external_container_id TEXT,
  external_post_id TEXT,
  permalink   TEXT,
  published_at TEXT,
  last_error  TEXT,
  origin      TEXT NOT NULL DEFAULT 'schedule' CHECK (origin IN ('schedule','assistant','manual')),
  is_test     INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX posts_slot_unique ON posts(account_id, slot_at) WHERE origin = 'schedule';
CREATE UNIQUE INDEX posts_external_unique ON posts(external_post_id) WHERE external_post_id IS NOT NULL;
CREATE INDEX posts_account_slot ON posts(account_id, slot_at);

CREATE TABLE post_attempts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,             -- generate | check | publish | reconcile
  outcome     TEXT NOT NULL,             -- ok | rejected | error | unknown
  detail      TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX post_attempts_post ON post_attempts(post_id);

CREATE TABLE metrics (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  account_id  TEXT NOT NULL,
  bucket_hours INTEGER NOT NULL,         -- observation point: hours after publish
  status      TEXT NOT NULL CHECK (status IN ('ok','failed','unavailable')),
  views       INTEGER,
  likes       INTEGER,
  replies     INTEGER,
  reposts     INTEGER,
  quotes      INTEGER,
  shares      INTEGER,
  error       TEXT,
  observed_at TEXT NOT NULL,
  is_test     INTEGER NOT NULL DEFAULT 0,
  UNIQUE (post_id, bucket_hours)
);

CREATE TABLE jobs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id  TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  status      TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled','cancel_requested')),
  run_at      TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  post_id     INTEGER REFERENCES posts(id),
  attempts    INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  lease_owner TEXT,
  lease_until TEXT,
  last_error  TEXT,
  result_json TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  started_at  TEXT,
  finished_at TEXT
);
CREATE INDEX jobs_ready ON jobs(status, run_at);
CREATE INDEX jobs_account ON jobs(account_id, created_at);

CREATE TABLE events (
  seq         INTEGER PRIMARY KEY AUTOINCREMENT,   -- monotonic cursor for clients
  event_id    TEXT NOT NULL UNIQUE,
  account_id  TEXT NOT NULL,
  source_system TEXT NOT NULL,
  event_type  TEXT NOT NULL,
  severity    TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('info','success','warning','error')),
  occurred_at TEXT NOT NULL,
  received_at TEXT NOT NULL,
  job_id      INTEGER,
  post_id     INTEGER,
  message     TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX events_account_seq ON events(account_id, seq);

CREATE TABLE reports (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id  TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL CHECK (kind IN ('daily','weekly')),
  period_start TEXT NOT NULL,
  period_end  TEXT NOT NULL,
  version     INTEGER NOT NULL,
  is_current  INTEGER NOT NULL DEFAULT 1,
  data_json   TEXT NOT NULL,
  summary_text TEXT,
  summary_status TEXT NOT NULL CHECK (summary_status IN ('ok','skipped_no_ai','skipped_budget','failed')),
  data_as_of  TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  generated_by TEXT NOT NULL,
  UNIQUE (account_id, kind, period_start, version)
);
CREATE UNIQUE INDEX reports_one_current ON reports(account_id, kind, period_start) WHERE is_current = 1;

CREATE TABLE ai_usage (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id  TEXT NOT NULL,
  purpose     TEXT NOT NULL,
  provider    TEXT NOT NULL,
  model       TEXT NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('reserved','committed','released','failed')),
  reserved_usd REAL NOT NULL DEFAULT 0,
  cost_usd    REAL,
  cost_kind   TEXT NOT NULL CHECK (cost_kind IN ('measured_tokens_estimated_price','estimated','unknown','none')),
  input_tokens INTEGER,
  output_tokens INTEGER,
  job_id      INTEGER,
  error       TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX ai_usage_account_time ON ai_usage(account_id, created_at);

CREATE TABLE assistant_runs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id  TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL CHECK (kind IN ('summary','draft','improvement')),
  input_json  TEXT NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','unavailable')),
  output_json TEXT,
  error       TEXT,
  usage_id    INTEGER,
  draft_post_id INTEGER,
  created_by  TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE audit_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id  TEXT,
  actor       TEXT NOT NULL,
  action      TEXT NOT NULL,
  target      TEXT,
  detail_json TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX audit_account_time ON audit_log(account_id, created_at);

CREATE TABLE runtime_state (
  key         TEXT PRIMARY KEY,
  value_json  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
