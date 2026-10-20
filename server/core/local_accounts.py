"""Server-owned password accounts; registration never grants resource access."""
import hashlib
import re
import secrets
import sqlite3
import time
import uuid

from server.core.auth import Authentication, AuthenticationRequired, digest
from server.core.identity import user_id
from server.core.permissions import Policy


class LoginThrottled(ValueError):
    pass


def normalize_username(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{2,31}', value):
        raise ValueError('账号需为 3–32 位英文字母、数字、点、下划线或连字符')
    return value.lower()


def validate_password(value):
    if not isinstance(value, str) or not 10 <= len(value) <= 128 or len(value.encode('utf-8')) > 1024:
        raise ValueError('密码长度需为 10–128 个字符')
    return value


def hash_password(password):
    validate_password(password)
    salt = secrets.token_bytes(32)
    value = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return 'scrypt-v1$' + salt.hex() + '$' + value.hex()


_DUMMY_HASH = 'scrypt-v1$' + '00' * 32 + '$' + hashlib.scrypt(
    b'unused-timing-reference', salt=bytes(32), n=16384, r=8, p=1, dklen=32).hex()


def verify_password(password, encoded):
    if not isinstance(password, str) or len(password) > 128 or len(password.encode('utf-8')) > 1024:
        return False
    try:
        scheme, salt, expected = encoded.split('$')
        if scheme != 'scrypt-v1' or len(salt) != 64 or len(expected) != 64:
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
        return secrets.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


class LocalAccounts:
    def __init__(self, store):
        self.store = store

    def require_mode(self):
        if Authentication(self.store).config()['mode'] != 'password':
            raise ValueError('请先启用本地账号登录')

    def setup_required(self):
        with self.store.connection() as db:
            return not db.execute("SELECT 1 FROM local_credentials WHERE user_id='local'").fetchone()

    def limit(self, operation, peer, username=''):
        now = time.time()
        # Trust the socket peer only. Client-supplied forwarding headers cannot reset limits.
        buckets = [(digest(operation + '|peer|' + peer), 60)]
        if username:
            buckets.append((digest(operation + '|account|' + peer + '|' + username[:128].lower()), 10))
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM auth_rate_limits WHERE expires<=?', (now,))
            for bucket, maximum in buckets:
                row = db.execute('SELECT count FROM auth_rate_limits WHERE bucket=?', (bucket,)).fetchone()
                if row and row['count'] >= maximum:
                    raise LoginThrottled('操作过于频繁，请一分钟后重试')
            for bucket, _ in buckets:
                db.execute('''INSERT INTO auth_rate_limits VALUES(?,1,?) ON CONFLICT(bucket)
                    DO UPDATE SET count=count+1''', (bucket, now + 60))

    def fields(self, body):
        username = normalize_username(body.get('username'))
        password = validate_password(body.get('password'))
        name = body.get('name')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError('请填写 1–80 个字符的姓名或昵称')
        return username, password, name.strip()

    def new_session(self, db, actor):
        token = secrets.token_urlsafe(48)
        db.execute('DELETE FROM auth_sessions WHERE expires<=?', (time.time(),))
        db.execute('INSERT INTO auth_sessions(token_hash,user_id,expires) VALUES(?,?,?)',
                   (digest(token), actor, time.time() + 43200))
        return token

    def setup(self, body, headers, peer):
        self.require_mode()
        if not Authentication.direct_loopback(headers, peer):
            raise PermissionError('首次设置负责人须在服务器本机使用回环地址打开页面，不能经由代理访问')
        self.limit('setup', peer)
        username, password, name = self.fields(body)
        encoded = hash_password(password)
        self.store.path.chmod(0o600)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM local_credentials WHERE user_id='local'").fetchone():
                raise ValueError('负责人账号已设置，请直接登录')
            try:
                db.execute('INSERT INTO local_credentials(user_id,username,password_hash) VALUES(?,?,?)',
                           ('local', username, encoded))
            except sqlite3.IntegrityError:
                raise ValueError('账号已被使用') from None
            db.execute("UPDATE users SET name=? WHERE id='local'", (name,))
            db.execute('DELETE FROM auth_sessions')
            token = self.new_session(db, 'local')
            db.execute("INSERT INTO team_audit(actor,action,detail) VALUES('local','local_owner_initialized','服务器本机设置负责人账号')")
        return token, 'local'

    def register(self, body, peer):
        self.require_mode()
        self.limit('register', peer)
        if Authentication(self.store).config().get('registration_open', True) is not True:
            raise PermissionError('当前暂未开放注册，请联系负责人')
        if self.setup_required():
            raise ValueError('请等待服务器本机完成负责人账号设置')
        username, password, name = self.fields(body)
        encoded, actor = hash_password(password), uuid.uuid4().hex
        self.store.path.chmod(0o600)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM local_credentials WHERE username=?', (username,)).fetchone():
                raise ValueError('账号已被使用')
            db.execute("INSERT INTO users(id,tenant_key,open_id,name) VALUES(?,'password',?,?)", (actor, username, name))
            db.execute('INSERT INTO local_credentials(user_id,username,password_hash) VALUES(?,?,?)', (actor, username, encoded))
            db.execute("INSERT INTO user_preferences(user_id,active_role,default_workspace) VALUES(?,'qa','testing')", (actor,))
            db.execute("INSERT INTO team_audit(actor,action,detail) VALUES(?,'local_registered','本地账号注册；等待审批')", (actor,))
        return Authentication(self.store).session(actor)

    def login(self, body, peer):
        self.require_mode()
        raw = body.get('username')
        self.limit('login', peer, raw if isinstance(raw, str) else '<invalid>')
        try:
            username = normalize_username(raw)
        except ValueError:
            username = ''
        with self.store.connection() as db:
            row = db.execute('''SELECT c.*,u.status FROM local_credentials c JOIN users u ON u.id=c.user_id
                WHERE c.username=?''', (username,)).fetchone()
        valid = verify_password(body.get('password'), row['password_hash'] if row else _DUMMY_HASH)
        if not row or not valid or row['status'] == 'disabled':
            raise AuthenticationRequired('账号或密码错误，或账号已禁用')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('''SELECT c.password_hash,u.status FROM local_credentials c
                JOIN users u ON u.id=c.user_id WHERE c.user_id=?''', (row['user_id'],)).fetchone()
            if not current or current['status'] == 'disabled' or current['password_hash'] != row['password_hash']:
                raise AuthenticationRequired('账号信息已变化，请重新登录')
            token = self.new_session(db, row['user_id'])
            db.execute("INSERT INTO team_audit(actor,action,detail) VALUES(?,'local_login','本地账号登录')", (row['user_id'],))
        return token, row['user_id']

    def change_password(self, body, peer):
        self.require_mode()
        actor = user_id()
        self.limit('change-password', peer, actor)
        with self.store.connection() as db:
            row = db.execute('SELECT password_hash FROM local_credentials WHERE user_id=?', (actor,)).fetchone()
        if not row or not verify_password(body.get('current_password'), row['password_hash']):
            raise AuthenticationRequired('当前密码不正确')
        encoded = hash_password(body.get('password'))
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            result = db.execute('UPDATE local_credentials SET password_hash=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=? AND password_hash=?',
                                (encoded, actor, row['password_hash']))
            if result.rowcount != 1:
                raise ValueError('密码已变化，请重新登录')
            db.execute('DELETE FROM auth_sessions WHERE user_id=?', (actor,))
            db.execute("INSERT INTO team_audit(actor,action,detail) VALUES(?,'local_password_changed','修改密码；已撤销全部登录会话')", (actor,))
        return {'ok': True}

    def reset_password(self, body):
        Policy(self.store).require('platform', 'manage')
        actor = body.get('user_id')
        if not isinstance(actor, str) or actor == user_id():
            raise ValueError('修改自己的密码请使用用户设置')
        return self._reset(actor, body.get('password'), user_id())

    def _reset(self, actor, password, auditor):
        encoded = hash_password(password)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('UPDATE local_credentials SET password_hash=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?',
                          (encoded, actor)).rowcount != 1:
                raise ValueError('该用户尚未设置本地账号密码')
            db.execute('DELETE FROM auth_sessions WHERE user_id=?', (actor,))
            db.execute("INSERT INTO team_audit(actor,action,detail) VALUES(?,'local_password_reset',?)",
                       (auditor, '本地账号密码已重置；目标用户 ID：' + actor))
        return {'ok': True}
