"""Additive public metadata and local connector state, separate from workspaces."""
def migrate(store):
    with store.connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS public_versions (
          id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),name TEXT NOT NULL,
          created_by TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(project_id,name));
        CREATE TABLE IF NOT EXISTS public_items (
          id TEXT PRIMARY KEY,studio_id TEXT NOT NULL,project_id TEXT NOT NULL,author_id TEXT NOT NULL,
          department TEXT NOT NULL,node TEXT NOT NULL,kind TEXT NOT NULL,revision INTEGER NOT NULL,
          withdrawn INTEGER NOT NULL DEFAULT 0,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS public_revisions (
          item_id TEXT NOT NULL REFERENCES public_items(id),revision INTEGER NOT NULL,
          version_id TEXT NOT NULL REFERENCES public_versions(id),title TEXT NOT NULL,description TEXT NOT NULL,
          package TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(item_id,revision));
        CREATE TABLE IF NOT EXISTS public_operations (
          actor TEXT NOT NULL,operation_id TEXT NOT NULL,studio_id TEXT NOT NULL,project_id TEXT NOT NULL,
          package TEXT,sha256 TEXT NOT NULL,publication_id TEXT NOT NULL,expected_revision INTEGER NOT NULL,
          result TEXT,expires REAL NOT NULL,PRIMARY KEY(actor,operation_id));
        CREATE TABLE IF NOT EXISTS public_connections (
          actor TEXT PRIMARY KEY,server_url TEXT NOT NULL,session TEXT NOT NULL,remote_user TEXT NOT NULL,
          allow_lan_http INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS public_bindings (
          actor TEXT NOT NULL,project_id TEXT NOT NULL,server_url TEXT NOT NULL,
          studio_id TEXT NOT NULL,remote_project_id TEXT NOT NULL,version_id TEXT NOT NULL,
          PRIMARY KEY(actor,project_id));
        CREATE TABLE IF NOT EXISTS public_drafts (
          id TEXT PRIMARY KEY,actor TEXT NOT NULL,project_id TEXT NOT NULL,server_url TEXT NOT NULL,
          binding TEXT NOT NULL,source TEXT NOT NULL,source_hash TEXT NOT NULL,package TEXT NOT NULL,
          publication_id TEXT NOT NULL DEFAULT '',expected_revision INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'draft',result TEXT,error TEXT NOT NULL DEFAULT '',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS public_copies (
          id TEXT PRIMARY KEY,actor TEXT NOT NULL,project_id TEXT NOT NULL,server_url TEXT NOT NULL,
          publication_id TEXT NOT NULL,revision INTEGER NOT NULL,package TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
