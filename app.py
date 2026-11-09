import os, sqlite3, secrets, json, io
from urllib.parse import urlparse
from pathlib import Path
from functools import wraps
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, session, jsonify, render_template, redirect, send_file
from werkzeug.security import generate_password_hash, check_password_hash

TOOLS = ['드라이버', '몽키 스패너', '펜치', '망치']
REASONS = ['신규 구매 및 추가', '폐기', '재고 정정']

def create_app(database=None):
    app = Flask(__name__)
    folder = Path(__file__).parent / 'instance'
    folder.mkdir(exist_ok=True)
    secret_file = folder / 'session.key'
    if not secret_file.exists():
        try:
            with secret_file.open('x') as f: f.write(secrets.token_hex(32))
            secret_file.chmod(0o600)
        except FileExistsError: pass
    app.config.update(SECRET_KEY=os.environ.get('STBM_SECRET_KEY') or secret_file.read_text(),
        DATABASE=str(database or folder / 'stbm.sqlite3'), SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('STBM_HTTPS') == '1',
        MAX_CONTENT_LENGTH=8 * 1024 * 1024)
    @contextmanager
    def db():
        c = sqlite3.connect(app.config['DATABASE'], timeout=10)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c: yield c
        finally: c.close()
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS stock(mode TEXT NOT NULL, tool TEXT NOT NULL, total INTEGER NOT NULL CHECK(total>=0), version INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(mode,tool));
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, token TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id), mode TEXT NOT NULL, kind TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS lines(event_id INTEGER REFERENCES events(id), tool TEXT NOT NULL, qty INTEGER NOT NULL CHECK(qty>0));
        CREATE TABLE IF NOT EXISTS adjustments(id INTEGER PRIMARY KEY, token TEXT UNIQUE NOT NULL, user_id INTEGER REFERENCES users(id), mode TEXT NOT NULL, tool TEXT NOT NULL, before_qty INTEGER NOT NULL, after_qty INTEGER NOT NULL, reason TEXT NOT NULL, created TEXT NOT NULL);
        ''')
        if 'status' not in {r['name'] for r in c.execute('PRAGMA table_info(events)')}:
            c.execute("ALTER TABLE events ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'")
        for name in ['관리자','김상협','강라온','박회승','이수민','최인승']:
            if not c.execute('SELECT 1 FROM users WHERE name=?',(name,)).fetchone():
                c.execute('INSERT INTO users(name,password,role) VALUES(?,?,?)',(name,generate_password_hash('1234'),'admin' if name=='관리자' else 'worker'))
        for mode in ['test','demo','operation']:
            for tool in TOOLS: c.execute('INSERT OR IGNORE INTO stock(mode,tool,total) VALUES(?,?,0)',(mode,tool))
        # Rename legacy display label 렌치 → 몽키 스패너 without losing stock/history.
        for mode in ['test','demo','operation']:
            old=c.execute("SELECT * FROM stock WHERE mode=? AND tool='렌치'",(mode,)).fetchone()
            if not old: continue
            cur=c.execute("SELECT * FROM stock WHERE mode=? AND tool='몽키 스패너'",(mode,)).fetchone()
            if cur:
                if cur['total']==0 and old['total']>0:
                    c.execute('UPDATE stock SET total=?,version=? WHERE mode=? AND tool=?',(old['total'],old['version'],mode,'몽키 스패너'))
                c.execute("DELETE FROM stock WHERE mode=? AND tool='렌치'",(mode,))
            else:
                c.execute("UPDATE stock SET tool='몽키 스패너' WHERE mode=? AND tool='렌치'",(mode,))
        c.execute("UPDATE lines SET tool='몽키 스패너' WHERE tool='렌치'")
        c.execute("UPDATE adjustments SET tool='몽키 스패너' WHERE tool='렌치'")
        c.execute("UPDATE events SET payload=REPLACE(payload,'렌치','몽키 스패너') WHERE payload LIKE '%렌치%'")
    def now(): return datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')
    def auth(admin=False):
        def decorate(fn):
            @wraps(fn)
            def wrapped(*a,**kw):
                if 'uid' not in session: return jsonify(error='로그인이 필요합니다.'),401
                if admin and session['role']!='admin': return jsonify(error='관리자만 사용할 수 있습니다.'),403
                if request.method!='GET' and request.headers.get('X-CSRF-Token')!=session['csrf']:
                    return jsonify(error='보안 확인에 실패했습니다. 다시 로그인하세요.'),403
                return fn(*a,**kw)
            return wrapped
        return decorate
    def mode_of(data):
        mode=data.get('mode','test')
        if mode not in ['test','demo','operation']: raise ValueError('기록 구분이 올바르지 않습니다.')
        return mode
    def integer(value, minimum=0):
        if type(value) is not int or not minimum<=value<=100000: raise ValueError('수량은 허용 범위 내 정수로 입력하세요.')
        return value
    def balance(c,mode,user=None):
        sql="SELECT l.tool,SUM(CASE WHEN e.kind='borrow' THEN l.qty ELSE -l.qty END) qty FROM lines l JOIN events e ON e.id=l.event_id WHERE e.mode=?"
        args=[mode]
        if user is not None: sql+=' AND e.user_id=?'; args.append(user)
        return {r['tool']:r['qty'] for r in c.execute(sql+' GROUP BY l.tool',args)}
    @app.before_request
    def validate_json():
        if request.method == 'POST' and request.path.startswith('/api/') and request.path != '/api/recognize':
            if not request.is_json or not isinstance(request.get_json(silent=True), dict):
                return jsonify(error='올바른 요청 형식이 아닙니다.'),400
    @app.errorhandler(ValueError)
    def invalid(e): return jsonify(error=str(e)),400
    @app.errorhandler(sqlite3.Error)
    def storage_error(e):
        app.logger.exception('Database operation failed')
        return jsonify(error='저장소 처리에 실패했습니다. 저장 결과를 확인한 뒤 다시 시도하세요.'),503
    @app.get('/')
    def home(): return render_template('index.html')
    @app.get('/dashboard')
    def dashboard():
        if 'uid' not in session: return redirect('/')
        return render_template('index.html')
    @app.get('/admin')
    def admin_page():
        if 'uid' not in session: return redirect('/')
        if session['role'] != 'admin': return '관리자만 접근할 수 있습니다.',403
        return render_template('index.html')
    @app.get('/api/health')
    def health(): return jsonify(service='stbm',version=2)
    @app.get('/api/qr')
    @auth(admin=True)
    def qr():
        import qrcode
        import qrcode.image.svg
        url=os.environ.get('STBM_PUBLIC_URL','http://127.0.0.1:8001/')
        if urlparse(url).scheme not in ['https','http'] or not urlparse(url).netloc:
            raise ValueError('STBM_PUBLIC_URL에 올바른 웹 주소를 설정하세요.')
        image=qrcode.make(url,image_factory=qrcode.image.svg.SvgPathImage)
        output=io.BytesIO(); image.save(output);output.seek(0)
        return send_file(output,mimetype='image/svg+xml')
    @app.get('/api/config')
    @auth()
    def config():
        from recognition import model_available
        from model_config import FINAL_MODEL_NAME, FINAL_IMGSZ, FINAL_CONF
        return jsonify(
            ai_ready=model_available(),
            model=FINAL_MODEL_NAME if model_available() else None,
            imgsz=int(os.environ.get('STBM_MODEL_IMGSZ', FINAL_IMGSZ)),
            conf=float(os.environ.get('STBM_MODEL_CONF', FINAL_CONF)),
            public_url=os.environ.get('STBM_PUBLIC_URL','http://127.0.0.1:8001/'),
        )
    @app.post('/api/recognize')
    @auth()
    def recognize():
        from recognition import recognize_image
        image=request.files.get('image')
        if image is None: raise ValueError('촬영 이미지를 선택하세요.')
        try: return jsonify(recognize_image(image.read()))
        except RuntimeError as e: return jsonify(error=str(e)),503
    @app.post('/api/login')
    def login():
        if request.headers.get('X-STBM-Request')!='1': return jsonify(error='잘못된 요청입니다.'),403
        data=request.get_json() or {}
        if not isinstance(data.get('name'),str) or not isinstance(data.get('password'),str): raise ValueError('아이디와 비밀번호를 입력하세요.')
        with db() as c: user=c.execute('SELECT * FROM users WHERE name=?',(data['name'],)).fetchone()
        if not user or not check_password_hash(user['password'],data['password']): return jsonify(error='아이디 또는 비밀번호가 올바르지 않습니다.'),401
        session.clear();session.update(uid=user['id'],name=user['name'],role=user['role'],csrf=secrets.token_hex(24))
        return jsonify(name=user['name'],role=user['role'],csrf=session['csrf'])
    @app.get('/api/me')
    @auth()
    def me(): return jsonify(name=session['name'],role=session['role'],csrf=session['csrf'])
    @app.post('/api/logout')
    @auth()
    def logout(): session.clear();return jsonify(ok=True)
    @app.get('/api/state')
    @auth()
    def state():
        mode=mode_of(request.args)
        with db() as c:
            borrowed=balance(c,mode); mine=balance(c,mode,session['uid'])
            stocks=[dict(r,borrowed=borrowed.get(r['tool'],0),available=r['total']-borrowed.get(r['tool'],0),mine=mine.get(r['tool'],0)) for r in c.execute('SELECT tool,total,version FROM stock WHERE mode=? ORDER BY rowid',(mode,))]
            where='e.mode=?';args=[mode]
            if session['role']!='admin': where+=' AND e.user_id=?';args.append(session['uid'])
            events=[dict(r) for r in c.execute('SELECT e.id,u.name,e.kind,e.created,l.tool,l.qty FROM events e JOIN users u ON u.id=e.user_id JOIN lines l ON l.event_id=e.id WHERE '+where+' ORDER BY e.id DESC LIMIT 200',args)]
            holders=[];adjustments=[]
            if session['role']=='admin':
                holders=[dict(r) for r in c.execute("SELECT u.name,l.tool,SUM(CASE WHEN e.kind='borrow' THEN l.qty ELSE -l.qty END) qty FROM events e JOIN lines l ON l.event_id=e.id JOIN users u ON u.id=e.user_id WHERE e.mode=? GROUP BY u.id,l.tool HAVING qty>0",(mode,))]
                adjustments=[dict(r) for r in c.execute('SELECT a.id,u.name,a.tool,a.before_qty,a.after_qty,a.reason,a.created FROM adjustments a JOIN users u ON u.id=a.user_id WHERE a.mode=? ORDER BY a.id DESC LIMIT 50',(mode,))]
            return_count=c.execute("SELECT count(*) FROM events e WHERE "+where+" AND e.kind='return'",args).fetchone()[0]
            movement=[dict(r) for r in c.execute("SELECT l.tool,SUM(CASE WHEN e.kind='borrow' THEN l.qty ELSE 0 END) borrowed,SUM(CASE WHEN e.kind='return' THEN l.qty ELSE 0 END) returned FROM events e JOIN lines l ON l.event_id=e.id WHERE "+where+" GROUP BY l.tool",args)]
            groups=[dict(r) for r in c.execute('SELECT e.id,u.name,e.kind,e.created,e.status FROM events e JOIN users u ON u.id=e.user_id WHERE '+where+' ORDER BY e.id DESC LIMIT 200',args)]
            for group in groups:
                group['items']=[dict(r) for r in c.execute('SELECT tool,qty FROM lines WHERE event_id=?',(group['id'],))]
                group['status']='완료' if group['status']=='completed' else group['status']
            users=[dict(r) for r in c.execute('SELECT id,name,role FROM users ORDER BY id')] if session['role']=='admin' else []
        return jsonify(stock=stocks,events=events,holders=holders,adjustments=adjustments,return_count=return_count,movement=movement,groups=groups,users=users)
    @app.post('/api/events')
    @auth()
    def event():
        data=request.get_json() or {};mode=mode_of(data);kind=data.get('kind');token=data.get('token');items=data.get('items')
        if kind not in ['borrow','return']: raise ValueError('대여 또는 반납을 선택하세요.')
        if not isinstance(token,str) or not 16<=len(token)<=100: raise ValueError('처리 식별자가 필요합니다.')
        if not isinstance(items,dict) or not items or any(t not in TOOLS for t in items): raise ValueError('공구를 선택하세요.')
        items={t:integer(q,1) for t,q in items.items()};payload=json.dumps([mode,kind,items],sort_keys=True)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM events WHERE token=?',(token,)).fetchone()
            if old:
                if old['user_id']!=session['uid'] or old['payload']!=payload: raise ValueError('이미 다른 처리에 사용된 식별자입니다.')
                return jsonify(ok=True,id=old['id'],duplicate=True,created=old['created'],name=session['name'],kind=kind,items=items)
            borrowed=balance(c,mode);mine=balance(c,mode,session['uid'])
            for tool,qty in items.items():
                total=c.execute('SELECT total FROM stock WHERE mode=? AND tool=?',(mode,tool)).fetchone()['total']
                if kind=='borrow' and qty>total-borrowed.get(tool,0): raise ValueError(tool+': 대여 가능 수량을 초과했습니다.')
                if kind=='return' and qty>mine.get(tool,0): raise ValueError(tool+': 본인의 대여 수량을 초과했습니다.')
            c_time=now()
            cur=c.execute('INSERT INTO events(token,user_id,mode,kind,created,payload) VALUES(?,?,?,?,?,?)',(token,session['uid'],mode,kind,c_time,payload))
            for tool,qty in items.items(): c.execute('INSERT INTO lines VALUES(?,?,?)',(cur.lastrowid,tool,qty))
            event_id=cur.lastrowid
        return jsonify(ok=True,id=event_id,created=c_time,name=session['name'],kind=kind,items=items),201
    @app.post('/api/stock')
    @auth(admin=True)
    def stock():
        data=request.get_json() or {};mode=mode_of(data);tool=data.get('tool');reason=data.get('reason');token=data.get('token')
        total=integer(data.get('total'));version=integer(data.get('version'))
        if tool not in TOOLS or reason not in REASONS: raise ValueError('공구와 변경 이유를 선택하세요.')
        if not isinstance(token,str) or not 16<=len(token)<=100: raise ValueError('처리 식별자가 필요합니다.')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM adjustments WHERE token=?',(token,)).fetchone()
            if old:
                if (old['user_id'],old['mode'],old['tool'],old['after_qty'],old['reason'])!=(session['uid'],mode,tool,total,reason): raise ValueError('이미 다른 처리에 사용된 식별자입니다.')
                return jsonify(ok=True,duplicate=True)
            row=c.execute('SELECT * FROM stock WHERE mode=? AND tool=?',(mode,tool)).fetchone()
            if row['version']!=version: return jsonify(error='다른 변경이 있습니다. 새로고침 후 다시 입력하세요.'),409
            if total<balance(c,mode).get(tool,0): raise ValueError('전체 보유 수량은 대여 중 수량보다 작을 수 없습니다.')
            if total==row['total']: raise ValueError('변경된 수량이 없습니다.')
            if reason=='신규 구매 및 추가' and total<row['total']: raise ValueError('신규 구매는 수량이 증가해야 합니다.')
            if reason=='폐기' and total>row['total']: raise ValueError('폐기는 수량이 감소해야 합니다.')
            c.execute('UPDATE stock SET total=?,version=version+1 WHERE mode=? AND tool=?',(total,mode,tool))
            c.execute('INSERT INTO adjustments(token,user_id,mode,tool,before_qty,after_qty,reason,created) VALUES(?,?,?,?,?,?,?,?)',(token,session['uid'],mode,tool,row['total'],total,reason,now()))
        return jsonify(ok=True)
    return app

if __name__=='__main__': create_app().run(host='127.0.0.1',port=int(os.environ.get('PORT','8001')),debug=False)
