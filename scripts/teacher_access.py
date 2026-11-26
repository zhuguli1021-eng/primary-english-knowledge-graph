"""Per-teacher access to the web homework bank. Offline teacher copies use OS file access."""
import base64
import getpass
import hashlib
import hmac
import json
import os
import pathlib
import secrets
import tempfile

ENV = 'CPP_TEACHER_ACCOUNTS'
ITERATIONS = 600000


def authorized(header, accounts):
    if not header.startswith('Basic '):
        return False
    try:
        raw=base64.b64decode(header[6:],validate=True).decode()
        user,password=raw.split(':',1)
        record=accounts.get(user)
        if not record:return False
        digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(record['salt']),ITERATIONS)
        return hmac.compare_digest(digest.hex(),record['hash'])
    except (ValueError,KeyError,TypeError):
        return False


def add_teacher(user):
    filename=os.getenv(ENV)
    if not filename or not user.strip() or ':' in user:raise SystemExit('请指定外部 CPP_TEACHER_ACCOUNTS 路径和教师用户名。')
    path=pathlib.Path(filename).expanduser().resolve()
    if path.is_relative_to(pathlib.Path(__file__).resolve().parents[1]):
        raise SystemExit('教师账号文件应放在仓库外。')
    password=getpass.getpass('教师密码：')
    if not password:raise SystemExit('密码不能为空。')
    accounts=json.loads(path.read_text()) if path.exists() else {}
    salt=secrets.token_bytes(16)
    accounts[user]={'salt':salt.hex(),'hash':hashlib.pbkdf2_hmac('sha256',password.encode(),salt,ITERATIONS).hex()}
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as f:
        json.dump(accounts,f);tmp=f.name
    os.replace(tmp,path)


def serve_bank(handler, bank):
    filename=os.getenv(ENV)
    try:
        accounts=json.loads(pathlib.Path(filename).expanduser().read_text()) if filename else {}
    except (OSError,ValueError):
        accounts={}
    if not isinstance(accounts,dict) or not accounts:return handler.send_json(503,{'error':'机构教师账号尚未配置'})
    if not authorized(handler.headers.get('Authorization',''),accounts):
        handler.send_response(401)
        handler.send_header('WWW-Authenticate','Basic realm="CPP teachers", charset="UTF-8"')
        handler.send_header('Cache-Control','no-store');handler.end_headers()
        return
    handler.send_json(200,bank())
