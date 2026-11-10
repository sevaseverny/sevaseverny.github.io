#!/usr/bin/env python3
"""Локальная админка портфолио.

Запуск:   python3 tools/admin_server.py            (сайт и админка на http://127.0.0.1:8800/admin/)
Пароль:   python3 tools/admin_server.py --set-password   (хеш лежит в admin.config.json, в git не попадает)

Сервер слушает только 127.0.0.1. Все /api/* требуют входа по паролю (cookie-сессия).
Сохранение пишет data/portfolio.json и запускает tools/build_gallery.py.
"""
import os, sys, io, re, json, time, shutil, hmac, hashlib, secrets, getpass, subprocess, argparse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

try:
    from PIL import Image, ImageOps
except ImportError:
    sys.exit('Нужен Pillow: python3 -m pip install Pillow')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.environ.get('ADMIN_CONFIG') or os.path.join(ROOT, 'admin.config.json')
DATA = os.path.join(ROOT, 'data', 'portfolio.json')
BACKUPS = os.path.join(ROOT, 'data', 'backups')
IMAGES = os.path.join(ROOT, 'images')
JPEG_QUALITY = 77
MAX_UPLOAD = 80 * 1024 * 1024
MAX_JSON = 2 * 1024 * 1024
SESSION_TTL = 12 * 3600
IMG_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
SRC_RE = re.compile(r'^images/[A-Za-z0-9._-]+$')

sessions = {}            # token -> expires
fails = {}               # ip -> [timestamps]
lock_until = {}          # ip -> time


# ---------- пароль ----------
def hash_pw(password, salt):
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)

def set_password():
    pw = os.environ.get('ADMIN_NEW_PASSWORD') or getpass.getpass('Новый пароль (минимум 8 символов): ')
    if len(pw) < 8:
        sys.exit('Слишком короткий пароль.')
    if not os.environ.get('ADMIN_NEW_PASSWORD') and pw != getpass.getpass('Ещё раз: '):
        sys.exit('Пароли не совпали.')
    salt = secrets.token_bytes(16)
    with open(CONFIG, 'w') as f:
        json.dump({'salt': salt.hex(), 'hash': hash_pw(pw, salt).hex()}, f)
    os.chmod(CONFIG, 0o600)
    print('Пароль сохранён в', CONFIG)

def check_password(pw):
    try:
        cfg = json.load(open(CONFIG))
        salt = bytes.fromhex(cfg['salt']); good = bytes.fromhex(cfg['hash'])
    except Exception:
        return False
    return hmac.compare_digest(hash_pw(pw, salt), good)


# ---------- картинки ----------
def img_dims(path):
    with Image.open(path) as im:
        w, h = im.size
        if im.getexif().get(0x0112) in (5, 6, 7, 8):
            w, h = h, w
    return w, h

def safe_name(name):
    name = os.path.basename(name or 'image.jpg')
    base, ext = os.path.splitext(name)
    base = re.sub(r'[^A-Za-z0-9._-]+', '-', base).strip('.-_') or 'image'
    ext = ext.lower()
    if ext not in IMG_EXT:
        raise ValueError('Допустимы JPG, PNG, GIF, WebP')
    if ext == '.jpeg':
        ext = '.jpg'
    n, cand = 1, base + ext
    while os.path.exists(os.path.join(IMAGES, cand)):
        n += 1; cand = '%s-%d%s' % (base, n, ext)
    return cand

def store_image(name, data):
    fname = safe_name(name)
    path = os.path.join(IMAGES, fname)
    try:
        im = Image.open(io.BytesIO(data)); im.load()
    except Exception:
        raise ValueError('Файл не похож на изображение')
    if fname.endswith('.jpg'):
        im = ImageOps.exif_transpose(im)
        icc = im.info.get('icc_profile')
        if im.mode not in ('RGB', 'L'):
            im = im.convert('RGB')
        kw = {'quality': JPEG_QUALITY, 'optimize': True, 'progressive': True}
        if icc:
            kw['icc_profile'] = icc
        im.save(path, 'JPEG', **kw)
    else:
        with open(path, 'wb') as f:
            f.write(data)
    w, h = img_dims(path)
    return {'src': 'images/' + fname, 'w': w, 'h': h, 'bytes': os.path.getsize(path)}


# ---------- данные ----------
def clean_image(it):
    if not isinstance(it, dict) or not isinstance(it.get('src'), str) or not SRC_RE.match(it['src']):
        raise ValueError('Некорректный путь картинки')
    if os.path.splitext(it['src'])[1].lower() not in IMG_EXT:
        raise ValueError('Некорректный тип картинки')
    path = os.path.join(ROOT, it['src'])
    if not os.path.isfile(path):
        raise ValueError('Нет файла ' + it['src'])
    w, h = img_dims(path)
    out = {'src': it['src'], 'w': w, 'h': h}
    if isinstance(it.get('id'), str) and re.match(r'^[A-Za-z][A-Za-z0-9_-]*$', it['id']):
        out['id'] = it['id']
    return out

def clean_data(d):
    if not isinstance(d, dict):
        raise ValueError('Некорректные данные')
    contacts = []
    for c in d.get('contacts', []):
        text = str(c.get('text', '')).strip()
        href = str(c.get('href', '')).strip()
        if not text:
            continue
        if href and not re.match(r'^(https?://|tel:|mailto:)', href):
            raise ValueError('Ссылка должна начинаться с http(s)://, tel: или mailto: — «%s»' % href)
        contacts.append({'text': text[:200], 'href': href[:300]})
    rows, seen = [], set()
    for r in d.get('rows', []):
        if not isinstance(r, list) or not 1 <= len(r) <= 3:
            raise ValueError('В блоке должно быть от 1 до 3 элементов')
        row = []
        for it in r:
            if isinstance(it, dict) and 'stack' in it:
                st = [clean_image(i) for i in it['stack']]
                if not 2 <= len(st) <= 3:
                    raise ValueError('В стопке должно быть 2–3 картинки')
                row.append({'stack': st})
            else:
                row.append(clean_image(it))
        rows.append(row)
    for r in rows:
        for it in r:
            for i in (it['stack'] if 'stack' in it else [it]):
                if 'id' in i:
                    if i['id'] in seen:
                        del i['id']
                    else:
                        seen.add(i['id'])
    return {'contacts': contacts, 'rows': rows}

def save_data(d):
    d = clean_data(d)
    os.makedirs(BACKUPS, exist_ok=True)
    if os.path.exists(DATA):
        shutil.copy2(DATA, os.path.join(BACKUPS, 'portfolio-%s.json' % time.strftime('%Y%m%d-%H%M%S')))
        for old in sorted(os.listdir(BACKUPS))[:-30]:
            os.remove(os.path.join(BACKUPS, old))
    tmp = DATA + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DATA)
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'build_gallery.py')], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError('Сборка не удалась: ' + (r.stderr or r.stdout)[-300:])
    return d


# ---------- HTTP ----------
DENY = ('admin.config', 'tools', '__pycache__')

class Handler(SimpleHTTPRequestHandler):
    server_version = 'PortfolioAdmin'

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, fmt, *args):
        if self.path.startswith('/api/'):
            sys.stderr.write('%s %s\n' % (self.address_string(), fmt % args))

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()

    # --- helpers
    def json(self, obj, code=200, headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def host_ok(self):
        host = (self.headers.get('Host') or '').lower()
        port = self.server.server_address[1]
        return host in ('127.0.0.1:%d' % port, 'localhost:%d' % port)

    def authed(self):
        c = self.headers.get('Cookie') or ''
        m = re.search(r'(?:^|;\s*)admin_session=([0-9a-f]{64})', c)
        t = m.group(1) if m else None
        exp = sessions.get(t)
        if exp and exp > time.time():
            return True
        sessions.pop(t, None)
        return False

    def body(self, limit):
        n = int(self.headers.get('Content-Length') or 0)
        if n > limit:
            raise ValueError('Слишком большой файл (больше %d МБ)' % (limit // 1024 // 1024))
        return self.rfile.read(n)

    # --- routing
    def do_GET(self):
        p = urlparse(self.path)
        if p.path.startswith('/api/'):
            return self.api('GET', p)
        parts = [x for x in unquote(p.path).split('/') if x]
        if any(x.startswith('.') or x.startswith(DENY) for x in parts):
            return self.send_error(404)
        if p.path == '/admin':
            self.send_response(301); self.send_header('Location', '/admin/'); self.end_headers(); return
        return super().do_GET()

    def do_HEAD(self):
        return self.do_GET()

    def do_POST(self):
        p = urlparse(self.path)
        if not p.path.startswith('/api/'):
            return self.send_error(404)
        return self.api('POST', p)

    def api(self, method, p):
        try:
            if not self.host_ok():
                return self.json({'error': 'bad host'}, 403)
            if method == 'POST' and self.headers.get('X-Requested-With') != 'admin':
                return self.json({'error': 'bad request'}, 403)
            ip = self.client_address[0]
            path = p.path

            if path == '/api/session' and method == 'GET':
                return self.json({'ok': self.authed()})

            if path == '/api/login' and method == 'POST':
                if lock_until.get(ip, 0) > time.time():
                    return self.json({'error': 'Слишком много попыток. Подождите минуту.'}, 429)
                pw = (json.loads(self.body(4096) or b'{}')).get('password', '')
                if check_password(str(pw)):
                    fails.pop(ip, None)
                    tok = secrets.token_hex(32)
                    sessions[tok] = time.time() + SESSION_TTL
                    return self.json({'ok': True}, headers={
                        'Set-Cookie': 'admin_session=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=%d' % (tok, SESSION_TTL)})
                f = [t for t in fails.get(ip, []) if t > time.time() - 300] + [time.time()]
                fails[ip] = f
                if len(f) >= 5:
                    lock_until[ip] = time.time() + 60; fails[ip] = []
                time.sleep(0.5)
                return self.json({'error': 'Неверный пароль'}, 401)

            if not self.authed():
                return self.json({'error': 'auth'}, 401)

            if path == '/api/logout' and method == 'POST':
                return self.json({'ok': True}, headers={'Set-Cookie': 'admin_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'})

            if path == '/api/data' and method == 'GET':
                return self.json(json.load(open(DATA, encoding='utf-8')))

            if path == '/api/save' and method == 'POST':
                d = save_data(json.loads(self.body(MAX_JSON)))
                return self.json({'ok': True, 'rows': len(d['rows']), 'data': d})

            if path == '/api/upload' and method == 'POST':
                name = parse_qs(p.query).get('name', ['image.jpg'])[0]
                return self.json(store_image(name, self.body(MAX_UPLOAD)))

            return self.json({'error': 'not found'}, 404)
        except ValueError as e:
            return self.json({'error': str(e)}, 400)
        except Exception as e:
            sys.stderr.write('ERROR %r\n' % (e,))
            return self.json({'error': 'Ошибка сервера: %s' % e}, 500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8800)
    ap.add_argument('--set-password', action='store_true')
    a = ap.parse_args()
    if a.set_password:
        return set_password()
    if not os.path.exists(CONFIG):
        sys.exit('Пароль ещё не задан. Выполните: python3 tools/admin_server.py --set-password')
    srv = ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
    print('Админка: http://127.0.0.1:%d/admin/   (Ctrl+C — остановить)' % a.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
