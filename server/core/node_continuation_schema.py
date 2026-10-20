"""Additive continuation state; never rewrites existing workspace or task evidence."""
def migrate(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS node_continuation_configs (
            project_id TEXT NOT NULL REFERENCES projects(id),department TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0,edges TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY(project_id,department));
        CREATE TABLE IF NOT EXISTS node_continuation_events (
            id INTEGER PRIMARY KEY,studio_id TEXT NOT NULL,project_id TEXT NOT NULL REFERENCES projects(id),
            source TEXT NOT NULL,target TEXT NOT NULL,task_id TEXT NOT NULL DEFAULT '',
            source_revision INTEGER NOT NULL,target_revision INTEGER NOT NULL,skill_sha256 TEXT NOT NULL,
            edge_revision INTEGER NOT NULL,topology_revision INTEGER NOT NULL,actor TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',detail TEXT NOT NULL DEFAULT '',job_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id,source,task_id,source_revision));
    ''')
