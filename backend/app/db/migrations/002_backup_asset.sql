-- 备份库自动导入：来源账本与资料文件索引（版本 2）
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
