"""幂等迁移工作室层级；保留旧项目 ID 与所有外键。"""
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone


def migrate(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        columns = {r['name'] for r in db.execute('PRAGMA table_info(projects)')}
        legacy_unique = any(
            [x['name'] for x in db.execute('PRAGMA index_info("'+r['name'].replace('"','""')+'")')] == ['name_key']
            for r in db.execute('PRAGMA index_list(projects)') if r['unique'])
        rebuild = 'studio_id' not in columns or legacy_unique
        if rebuild and db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
            backup = path.with_name(path.stem+'.before-studio-'+stamp+'-'+uuid.uuid4().hex[:6]+'.sqlite')
            with closing(sqlite3.connect(backup)) as target:
                db.backup(target)
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS studios (
            id TEXT PRIMARY KEY,name TEXT NOT NULL,name_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('''CREATE TABLE IF NOT EXISTS studio_memberships (
            studio_id TEXT NOT NULL REFERENCES studios(id),user_id TEXT NOT NULL,role TEXT NOT NULL,
            PRIMARY KEY(studio_id,user_id))''')
        default = db.execute('SELECT id FROM studios ORDER BY created_at,rowid LIMIT 1').fetchone()
        default_id = default['id'] if default else uuid.uuid4().hex
        if not default:
            db.execute('INSERT INTO studios(id,name,name_key) VALUES(?,?,?)',(default_id,'我的工作室','我的工作室'))
        db.execute('INSERT OR IGNORE INTO studio_memberships VALUES(?,?,?)',(default_id,'local','studio_owner'))
        if rebuild:
            db.execute('''CREATE TABLE studio_projects_migration (
                id TEXT PRIMARY KEY,name TEXT NOT NULL,name_key TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                studio_id TEXT NOT NULL REFERENCES studios(id),UNIQUE(studio_id,name_key))''')
            scope = 'COALESCE(studio_id,?)' if 'studio_id' in columns else '?'
            db.execute('INSERT INTO studio_projects_migration SELECT id,name,name_key,created_at,'+scope+' FROM projects',(default_id,))
            db.execute('DROP TABLE projects')
            db.execute('ALTER TABLE studio_projects_migration RENAME TO projects')
        db.execute('''CREATE TABLE IF NOT EXISTS user_preferences (
            user_id TEXT PRIMARY KEY,active_studio_id TEXT REFERENCES studios(id),
            active_role TEXT NOT NULL,default_workspace TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('''INSERT OR IGNORE INTO user_preferences(user_id,active_studio_id,active_role,default_workspace)
            VALUES(?,?,?,?)''',('local',default_id,'studio_owner','overview'))
        db.execute('''CREATE TABLE IF NOT EXISTS studio_visits (
            user_id TEXT NOT NULL,studio_id TEXT NOT NULL REFERENCES studios(id),
            project_id TEXT REFERENCES projects(id),PRIMARY KEY(user_id,studio_id))''')
        db.execute('''CREATE TABLE IF NOT EXISTS studio_workspaces (
            project_id TEXT NOT NULL REFERENCES projects(id),node TEXT NOT NULL,
            inputs TEXT NOT NULL DEFAULT '',skill TEXT,deliverable TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'not_started',revision INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(project_id,node))''')
        db.execute('''CREATE TABLE IF NOT EXISTS studio_events (
            id INTEGER PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),node TEXT NOT NULL,
            action TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        errors = db.execute('PRAGMA foreign_key_check').fetchall()
        if errors:
            raise ValueError('工作室迁移外键检查失败；原库事务已回滚')
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
