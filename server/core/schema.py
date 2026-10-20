"""Additive, idempotent team schema. Existing test tasks are not rewritten."""

def migrate(store):
    with store.connection() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,tenant_key TEXT NOT NULL,open_id TEXT NOT NULL,
                name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
                global_role TEXT NOT NULL DEFAULT 'member',created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_key,open_id));
            CREATE TABLE IF NOT EXISTS team_members (
                user_id TEXT NOT NULL REFERENCES users(id),studio_id TEXT NOT NULL REFERENCES studios(id),
                project_id TEXT NOT NULL DEFAULT '',department TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',PRIMARY KEY(user_id,studio_id,project_id,department));
            CREATE TABLE IF NOT EXISTS permission_rules (
                id TEXT PRIMARY KEY,subject_type TEXT NOT NULL,subject_id TEXT NOT NULL,
                studio_id TEXT NOT NULL DEFAULT '',project_id TEXT NOT NULL DEFAULT '',
                department TEXT NOT NULL DEFAULT '',node TEXT NOT NULL DEFAULT '',resource TEXT NOT NULL,
                action TEXT NOT NULL,effect TEXT NOT NULL,created_by TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS team_audit (
                id INTEGER PRIMARY KEY,actor TEXT NOT NULL,studio_id TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),
                expires REAL NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS project_connections (
                project_id TEXT PRIMARY KEY REFERENCES projects(id),repository TEXT NOT NULL DEFAULT '',
                updated_by TEXT NOT NULL,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS auth_states (
                state_hash TEXT PRIMARY KEY,browser_hash TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS local_credentials (
                user_id TEXT PRIMARY KEY REFERENCES users(id),username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS auth_rate_limits (
                bucket TEXT PRIMARY KEY,count INTEGER NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS department_jobs (
                id TEXT PRIMARY KEY,studio_id TEXT NOT NULL,project_id TEXT NOT NULL,node TEXT NOT NULL,
                actor TEXT NOT NULL,revision INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'queued',
                result TEXT,error TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS codex_handoffs (
                token_hash TEXT PRIMARY KEY,actor_id TEXT NOT NULL,studio_id TEXT NOT NULL,
                project_id TEXT NOT NULL,node TEXT NOT NULL,prompt TEXT NOT NULL,origin TEXT NOT NULL,
                expires REAL NOT NULL,consumed REAL);
            CREATE UNIQUE INDEX IF NOT EXISTS active_department_job ON department_jobs(project_id,node)
                WHERE status IN ('queued','running');
            CREATE TABLE IF NOT EXISTS project_node_configs (
                project_id TEXT NOT NULL REFERENCES projects(id),department TEXT NOT NULL,
                revision INTEGER NOT NULL,nodes TEXT NOT NULL,
                PRIMARY KEY(project_id,department));
            CREATE TABLE IF NOT EXISTS skill_library (
                id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),node TEXT NOT NULL,
                task_id TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'active',
                revision INTEGER NOT NULL DEFAULT 0,skill TEXT,uploader_id TEXT,updated_at REAL,
                deleted_at REAL,deleted_by TEXT);
            CREATE TABLE IF NOT EXISTS skill_bindings (
                project_id TEXT NOT NULL,node TEXT NOT NULL,task_id TEXT NOT NULL DEFAULT '',
                skill_id TEXT NOT NULL REFERENCES skill_library(id),PRIMARY KEY(project_id,node,task_id));
            CREATE TABLE IF NOT EXISTS skill_versions (
                skill_id TEXT NOT NULL REFERENCES skill_library(id),version INTEGER NOT NULL,
                skill TEXT NOT NULL,uploader_id TEXT,changed_at REAL,note TEXT NOT NULL,
                PRIMARY KEY(skill_id,version));
            CREATE TABLE IF NOT EXISTS project_content_configs (
                project_id TEXT PRIMARY KEY REFERENCES projects(id),revision INTEGER NOT NULL,
                items TEXT NOT NULL,disabled_departments TEXT NOT NULL);
        ''')
        if 'workflow_nodes' not in {r['name'] for r in db.execute('PRAGMA table_info(tasks)')}:
            db.execute("ALTER TABLE tasks ADD COLUMN workflow_nodes TEXT NOT NULL DEFAULT '{}'")
        for table in ('studios','projects'):
            if 'archived' not in {r['name'] for r in db.execute('PRAGMA table_info('+table+')')}:
                db.execute('ALTER TABLE '+table+' ADD COLUMN archived INTEGER NOT NULL DEFAULT 0')
        if 'actor' not in {r['name'] for r in db.execute('PRAGMA table_info(jobs)')}:
            db.execute("ALTER TABLE jobs ADD COLUMN actor TEXT NOT NULL DEFAULT ''")
        # Never turn an old, unattributed queue entry into a platform-owner job.
        # Completed history is kept; only unfinished work needs explicit retry.
        db.execute("""UPDATE jobs SET status='failed',error='任务缺少创建者身份，请重新提交；未自动执行',
            updated_at=CURRENT_TIMESTAMP WHERE actor='' AND status IN ('queued','running')""")
        db.execute("INSERT OR IGNORE INTO users(id,tenant_key,open_id,name,status,global_role) VALUES('local','local','local','本机负责人','active','project_lead')")

    from server.core.node_continuation_schema import migrate as migrate_continuation
    with store.connection() as db:
        migrate_continuation(db)
