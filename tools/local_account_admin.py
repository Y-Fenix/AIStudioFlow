"""Physical server recovery with interactive password input, never a web endpoint."""
import argparse
import getpass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.core.local_accounts import LocalAccounts, normalize_username
from server.store import Store


def recover_password(store, username, password):
    username = normalize_username(username)
    with store.connection() as db:
        row = db.execute('SELECT user_id FROM local_credentials WHERE username=?', (username,)).fetchone()
    if not row:
        raise ValueError('本地账号不存在；本工具不会创建负责人或修改审批状态')
    return LocalAccounts(store)._reset(row['user_id'], password, 'server-console')


def main():
    parser = argparse.ArgumentParser(description='在服务器本机重置已有账号密码；不会创建账号或授予权限。')
    parser.add_argument('--database', default=str(Path(__file__).resolve().parents[1] / 'data/platform.sqlite'))
    parser.add_argument('--username', required=True)
    args = parser.parse_args()
    if not Path(args.database).is_file():
        parser.exit(1, '数据库不存在，请指定当前服务实际使用的数据库。\n')
    try:
        password = getpass.getpass('新密码（10–128 个字符，不回显）：')
        if password != getpass.getpass('再次输入新密码：'):
            raise ValueError('两次输入的密码不一致')
        recover_password(Store(args.database), args.username, password)
    except (ValueError, EOFError, KeyboardInterrupt) as error:
        parser.exit(1, str(error) + '\n')
    print('密码已重置，该账号原有会话已撤销。请用新密码登录。')


if __name__ == '__main__':
    main()
