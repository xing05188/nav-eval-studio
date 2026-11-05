PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------- 版本 ----------
CREATE TABLE IF NOT EXISTS schema_version (
  version     INTEGER PRIMARY KEY,
  applied_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  description TEXT NOT NULL DEFAULT ''
);

-- ---------- 用户与审计 ----------
CREATE TABLE IF NOT EXISTS app_user (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE,
  display_name  TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL,
  password_salt TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'operator'
                CHECK (role IN ('admin','operator','viewer')),
  enabled       INTEGER NOT NULL DEFAULT 1,
  last_login_at TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS audit_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER REFERENCES app_user(id) ON DELETE SET NULL,
  username    TEXT NOT NULL DEFAULT '',
  action      TEXT NOT NULL,
  target_type TEXT NOT NULL DEFAULT '',
  target_id   TEXT NOT NULL DEFAULT '',
  detail_json TEXT NOT NULL DEFAULT '{}',
  client_ip   TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);

-- ---------- 数据集 ----------
CREATE TABLE IF NOT EXISTS dataset (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  name             TEXT NOT NULL,
  version          TEXT NOT NULL DEFAULT '',
  kind             TEXT NOT NULL
                   CHECK (kind IN ('r2r_ce','rxr_ce','custom')),
  root_path        TEXT NOT NULL,
  instruction_lang TEXT NOT NULL DEFAULT 'en',
  scene_count      INTEGER NOT NULL DEFAULT 0,
  episode_count    INTEGER NOT NULL DEFAULT 0,
  status           TEXT NOT NULL DEFAULT 'unknown'
                   CHECK (status IN ('ready','missing','invalid','unknown')),
  last_scan_at     TEXT,
  meta_json        TEXT NOT NULL DEFAULT '{}',
  created_at       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  UNIQUE (name, version)
);
CREATE INDEX IF NOT EXISTS idx_dataset_kind ON dataset(kind);

CREATE TABLE IF NOT EXISTS episode (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  dataset_id      INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
  episode_id      TEXT NOT NULL,
  scene_id        TEXT NOT NULL,
  instruction     TEXT NOT NULL DEFAULT '',
  instruction_len INTEGER NOT NULL DEFAULT 0,
  traj_len        REAL NOT NULL DEFAULT 0,
  duration_s      REAL NOT NULL DEFAULT 0,
  start_pose_json TEXT NOT NULL DEFAULT '[]',
  goal_pose_json  TEXT NOT NULL DEFAULT '[]',
  has_depth       INTEGER NOT NULL DEFAULT 0,
  meta_json       TEXT NOT NULL DEFAULT '{}',
  UNIQUE (dataset_id, episode_id)
);
CREATE INDEX IF NOT EXISTS idx_episode_scene ON episode(dataset_id, scene_id);
CREATE INDEX IF NOT EXISTS idx_episode_len   ON episode(dataset_id, traj_len);

-- ---------- 切分 ----------
CREATE TABLE IF NOT EXISTS split (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  dataset_id    INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  kind          TEXT NOT NULL CHECK (kind IN ('full','smoke','subset','custom')),
  base_split    TEXT NOT NULL DEFAULT 'val_unseen',
  seed          INTEGER NOT NULL DEFAULT 42,
  episode_count INTEGER NOT NULL DEFAULT 0,
  filter_json   TEXT NOT NULL DEFAULT '{}',
  created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  UNIQUE (dataset_id, name)
);

CREATE TABLE IF NOT EXISTS split_episode (
  split_id   INTEGER NOT NULL REFERENCES split(id) ON DELETE CASCADE,
  episode_id INTEGER NOT NULL REFERENCES episode(id) ON DELETE CASCADE,
  ordinal    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (split_id, episode_id)
);
CREATE INDEX IF NOT EXISTS idx_split_ep_ord ON split_episode(split_id, ordinal);

-- ---------- 配置模板 ----------
CREATE TABLE IF NOT EXISTS config_template (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL UNIQUE,
  modality      TEXT NOT NULL CHECK (modality IN ('vision','vision_geo','vision_geo_state')),
  memory_policy TEXT NOT NULL CHECK (memory_policy IN
                ('fixed_window','sliding_window','feature_cache','spatial_prune','hybrid')),
  params_json   TEXT NOT NULL DEFAULT '{}',
  description   TEXT NOT NULL DEFAULT '',
  builtin       INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- 模型档案 ----------
CREATE TABLE IF NOT EXISTS model_profile (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  name                TEXT NOT NULL UNIQUE,
  family              TEXT NOT NULL CHECK (family IN ('streamvln','mock','custom')),
  code_path           TEXT NOT NULL DEFAULT '',
  weights_path        TEXT NOT NULL DEFAULT '',
  entry               TEXT NOT NULL DEFAULT '',
  default_config_json TEXT NOT NULL DEFAULT '{}',
  needs_gpu           INTEGER NOT NULL DEFAULT 1,
  allowed_inputs      TEXT NOT NULL DEFAULT 'rgb,depth,pose,action',
  status              TEXT NOT NULL DEFAULT 'unknown'
                      CHECK (status IN ('available','missing','disabled','unknown')),
  description         TEXT NOT NULL DEFAULT '',
  created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at          TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- 评测任务 ----------
CREATE TABLE IF NOT EXISTS eval_task (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  name             TEXT NOT NULL,
  dataset_id       INTEGER NOT NULL REFERENCES dataset(id) ON DELETE RESTRICT,
  split_id         INTEGER NOT NULL REFERENCES split(id) ON DELETE RESTRICT,
  model_profile_id INTEGER NOT NULL REFERENCES model_profile(id) ON DELETE RESTRICT,
  config_json      TEXT NOT NULL DEFAULT '{}',
  status           TEXT NOT NULL DEFAULT 'queued'
                   CHECK (status IN ('queued','preparing','running','paused',
                                     'succeeded','failed','canceled')),
  priority         INTEGER NOT NULL DEFAULT 5,
  progress_done    INTEGER NOT NULL DEFAULT 0,
  progress_total   INTEGER NOT NULL DEFAULT 0,
  metrics_json     TEXT NOT NULL DEFAULT '{}',
  error_msg        TEXT NOT NULL DEFAULT '',
  gpu_ids          TEXT NOT NULL DEFAULT '',
  pid              INTEGER,
  created_by       INTEGER REFERENCES app_user(id) ON DELETE SET NULL,
  queued_at        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  started_at       TEXT,
  finished_at      TEXT,
  duration_s       REAL,
  note             TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_task_status ON eval_task(status, priority, queued_at);
CREATE INDEX IF NOT EXISTS idx_task_created ON eval_task(queued_at DESC);

CREATE TABLE IF NOT EXISTS task_episode (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id         INTEGER NOT NULL REFERENCES eval_task(id) ON DELETE CASCADE,
  episode_id      INTEGER NOT NULL REFERENCES episode(id) ON DELETE CASCADE,
  status          TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','running','success','failed','skipped','error')),
  success         INTEGER NOT NULL DEFAULT 0,
  spl             REAL NOT NULL DEFAULT 0,
  ne              REAL NOT NULL DEFAULT 0,
  os              REAL NOT NULL DEFAULT 0,
  ndtw            REAL NOT NULL DEFAULT 0,
  tl              REAL NOT NULL DEFAULT 0,
  steps           INTEGER NOT NULL DEFAULT 0,
  latency_avg_ms  REAL NOT NULL DEFAULT 0,
  latency_p95_ms  REAL NOT NULL DEFAULT 0,
  gpu_mem_peak_mb INTEGER NOT NULL DEFAULT 0,
  tokens_peak     INTEGER NOT NULL DEFAULT 0,
  ctx_len_peak    INTEGER NOT NULL DEFAULT 0,
  failure_reason  TEXT NOT NULL DEFAULT '',
  manual_reason   TEXT NOT NULL DEFAULT '',
  traj_path       TEXT NOT NULL DEFAULT '',
  log_path        TEXT NOT NULL DEFAULT '',
  updated_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  UNIQUE (task_id, episode_id)
);
CREATE INDEX IF NOT EXISTS idx_te_task_status ON task_episode(task_id, status);
CREATE INDEX IF NOT EXISTS idx_te_task_reason ON task_episode(task_id, failure_reason);

-- ---------- 资源采样 ----------
CREATE TABLE IF NOT EXISTS resource_sample (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id     INTEGER NOT NULL REFERENCES eval_task(id) ON DELETE CASCADE,
  ts          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  step        INTEGER NOT NULL DEFAULT 0,
  gpu_mem_mb  INTEGER NOT NULL DEFAULT 0,
  latency_ms  REAL NOT NULL DEFAULT 0,
  tokens      INTEGER NOT NULL DEFAULT 0,
  ctx_len     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sample_task ON resource_sample(task_id, id);

-- ---------- 产物 ----------
CREATE TABLE IF NOT EXISTS artifact (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id    INTEGER NOT NULL REFERENCES eval_task(id) ON DELETE CASCADE,
  episode_id INTEGER REFERENCES task_episode(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL CHECK (kind IN
             ('trajectory','video','figure','report','checkpoint','log','frame')),
  name       TEXT NOT NULL DEFAULT '',
  path       TEXT NOT NULL,
  size_bytes INTEGER NOT NULL DEFAULT 0,
  sha256     TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_artifact_task ON artifact(task_id, kind);

-- ---------- 系统设置 ----------
CREATE TABLE IF NOT EXISTS setting (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- ---------- 备份库导入索引 ----------
-- 既保存「已导入对象」的来源账本（幂等与变更检测），也保存各类资料文件的索引。
-- 大文件只登记路径与元信息，不复制到工作目录。
CREATE TABLE IF NOT EXISTS backup_asset (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  source_key   TEXT NOT NULL UNIQUE,
  root_path    TEXT NOT NULL DEFAULT '',
  rel_path     TEXT NOT NULL DEFAULT '',
  section      TEXT NOT NULL DEFAULT 'assets',
  kind         TEXT NOT NULL DEFAULT 'file',
  name         TEXT NOT NULL DEFAULT '',
  size_bytes   INTEGER NOT NULL DEFAULT 0,
  mtime        TEXT NOT NULL DEFAULT '',
  signature    TEXT NOT NULL DEFAULT '',
  entity_type  TEXT NOT NULL DEFAULT '',
  entity_id    INTEGER,
  status       TEXT NOT NULL DEFAULT 'new',
  message      TEXT NOT NULL DEFAULT '',
  meta_json    TEXT NOT NULL DEFAULT '{}',
  imported_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_backup_asset_section ON backup_asset(section, status);
CREATE INDEX IF NOT EXISTS idx_backup_asset_entity ON backup_asset(entity_type, entity_id);
