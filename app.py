import os, sqlite3, secrets, json, io, base64, binascii
from urllib.parse import urlparse
from pathlib import Path
from functools import wraps
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request, session, jsonify, render_template, redirect, send_file
from werkzeug.security import generate_password_hash, check_password_hash

TOOLS = ['드라이버', '몽키 스패너', '펜치', '망치']
REASONS = ['신규 구매 및 추가', '폐기', '재고 정정', '파손']
ISSUE_TYPES = ['파손', '수리 필요']
PLANTS = ['원료','소결','제선','제강','연속주조','열연','냉연','도금(표면처리)','후판','선재']

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
        MAX_CONTENT_LENGTH=10 * 1024 * 1024)
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
        c.executescript('''
        CREATE TABLE IF NOT EXISTS reservations(
          id INTEGER PRIMARY KEY,
          token TEXT UNIQUE NOT NULL,
          user_id INTEGER NOT NULL REFERENCES users(id),
          mode TEXT NOT NULL,
          status TEXT NOT NULL,
          rent_start TEXT NOT NULL,
          rent_due TEXT NOT NULL,
          created TEXT NOT NULL,
          decided_at TEXT,
          decided_by INTEGER REFERENCES users(id),
          event_id INTEGER REFERENCES events(id)
        );
        CREATE TABLE IF NOT EXISTS reservation_lines(
          reservation_id INTEGER NOT NULL REFERENCES reservations(id),
          tool TEXT NOT NULL,
          qty INTEGER NOT NULL CHECK(qty>0)
        );
        ''')
        cols={r['name'] for r in c.execute('PRAGMA table_info(events)')}
        if 'rent_start' not in cols: c.execute('ALTER TABLE events ADD COLUMN rent_start TEXT')
        if 'rent_due' not in cols: c.execute('ALTER TABLE events ADD COLUMN rent_due TEXT')
        if 'reservation_id' not in cols: c.execute('ALTER TABLE events ADD COLUMN reservation_id INTEGER')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS damage_reports(
          id INTEGER PRIMARY KEY,
          event_id INTEGER NOT NULL REFERENCES events(id),
          user_id INTEGER NOT NULL REFERENCES users(id),
          mode TEXT NOT NULL,
          tool TEXT NOT NULL,
          qty INTEGER NOT NULL CHECK(qty>0),
          note TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL,
          created TEXT NOT NULL,
          processed_at TEXT,
          processed_by INTEGER REFERENCES users(id)
        );
        ''')
        dcols={r['name'] for r in c.execute('PRAGMA table_info(damage_reports)')}
        if 'issue' not in dcols:
            c.execute("ALTER TABLE damage_reports ADD COLUMN issue TEXT NOT NULL DEFAULT '파손'")
        if 'compare_event_id' not in {r['name'] for r in c.execute('PRAGMA table_info(events)')}:
            c.execute('ALTER TABLE events ADD COLUMN compare_event_id INTEGER')
        if 'plant' not in {r['name'] for r in c.execute('PRAGMA table_info(events)')}:
            c.execute('ALTER TABLE events ADD COLUMN plant TEXT')
        if 'plant' not in {r['name'] for r in c.execute('PRAGMA table_info(reservations)')}:
            c.execute('ALTER TABLE reservations ADD COLUMN plant TEXT')
    def now(): return datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')
    def today(): return datetime.now(ZoneInfo('Asia/Seoul')).date()
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
    def parse_day(value,label):
        if not isinstance(value,str) or not value.strip(): raise ValueError(f'{label}을(를) 입력하세요.')
        try: return date.fromisoformat(value.strip()[:10])
        except ValueError: raise ValueError(f'{label}은(는) YYYY-MM-DD 형식이어야 합니다. 예: 2026-11-09')
    def validate_period(start,due):
        if due<start: raise ValueError('반납 예정일은 대여 시작일 이후여야 합니다.')
        if (due-start).days>365: raise ValueError('대여 기간은 최대 365일까지 설정할 수 있습니다.')
    def parse_plant(value):
        if not isinstance(value,str) or value not in PLANTS:
            raise ValueError('사용 공정을 선택하세요.')
        return value
    def balance(c,mode,user=None):
        sql="SELECT l.tool,SUM(CASE WHEN e.kind='borrow' THEN l.qty ELSE -l.qty END) qty FROM lines l JOIN events e ON e.id=l.event_id WHERE e.mode=?"
        args=[mode]
        if user is not None: sql+=' AND e.user_id=?'; args.append(user)
        return {r['tool']:r['qty'] for r in c.execute(sql+' GROUP BY l.tool',args)}
    def reserved_balance(c,mode):
        """Approved/pending holds still blocking stock (not yet fulfilled as a borrow)."""
        day=today().isoformat()
        rows=c.execute(
            "SELECT l.tool,SUM(l.qty) qty FROM reservation_lines l JOIN reservations r ON r.id=l.reservation_id "
            "WHERE r.mode=? AND r.status IN ('pending','approved') AND r.rent_due>=? GROUP BY l.tool",(mode,day))
        return {r['tool']:r['qty'] for r in rows}
    def damaged_pending(c,mode):
        """Returned-as-damaged qty waiting for admin to remove from inventory."""
        rows=c.execute(
            "SELECT tool,SUM(qty) qty FROM damage_reports WHERE mode=? AND status='pending' GROUP BY tool",(mode,))
        return {r['tool']:r['qty'] for r in rows}

    def pick_compare_borrow(c,mode,user_id,items):
        """Oldest open borrow with a saved photo that overlaps returned tools."""
        for loan in open_loans_for(c,mode,user_id):
            if not any(tool in loan['items'] for tool in items): continue
            if photo_file(loan['id']).is_file(): return loan['id']
        return None
    def weekly_report(c,mode):
        day=today(); start=(day-timedelta(days=6)).isoformat(); end=day.isoformat()
        borrow_qty=c.execute(
            "SELECT COALESCE(SUM(l.qty),0) FROM lines l JOIN events e ON e.id=l.event_id "
            "WHERE e.mode=? AND e.kind='borrow' AND substr(e.created,1,10) BETWEEN ? AND ?",(mode,start,end)).fetchone()[0]
        return_qty=c.execute(
            "SELECT COALESCE(SUM(l.qty),0) FROM lines l JOIN events e ON e.id=l.event_id "
            "WHERE e.mode=? AND e.kind='return' AND substr(e.created,1,10) BETWEEN ? AND ?",(mode,start,end)).fetchone()[0]
        issue_rows=c.execute(
            "SELECT issue,COALESCE(SUM(qty),0) qty FROM damage_reports WHERE mode=? AND substr(created,1,10) BETWEEN ? AND ? GROUP BY issue",
            (mode,start,end)).fetchall()
        by_issue={r['issue']:r['qty'] for r in issue_rows}
        damaged_qty=by_issue.get('파손',0); repair_qty=by_issue.get('수리 필요',0); issue_qty=damaged_qty+repair_qty
        top=[dict(tool=r['tool'],qty=r['qty']) for r in c.execute(
            "SELECT l.tool,SUM(l.qty) qty FROM lines l JOIN events e ON e.id=l.event_id "
            "WHERE e.mode=? AND e.kind='borrow' AND substr(e.created,1,10) BETWEEN ? AND ? "
            "GROUP BY l.tool ORDER BY qty DESC,l.tool",(mode,start,end))]
        by_plant=[dict(plant=r['plant'] or '미지정',qty=r['qty']) for r in c.execute(
            "SELECT e.plant,SUM(l.qty) qty FROM lines l JOIN events e ON e.id=l.event_id "
            "WHERE e.mode=? AND e.kind='borrow' AND substr(e.created,1,10) BETWEEN ? AND ? "
            "GROUP BY e.plant ORDER BY qty DESC",(mode,start,end))]
        open_count=0; overdue_count=0
        for u in c.execute('SELECT id FROM users').fetchall():
            loans=open_loans_for(c,mode,u['id']); open_count+=len(loans); overdue_count+=sum(1 for l in loans if l['overdue'])
        return dict(
            period_start=start,period_end=end,
            borrow_qty=borrow_qty,return_qty=return_qty,
            issue_qty=issue_qty,damaged_qty=damaged_qty,repair_qty=repair_qty,
            overdue_open=overdue_count,open_loans=open_count,
            overdue_rate=round(overdue_count/open_count,3) if open_count else 0.0,
            damage_rate=round(issue_qty/return_qty,3) if return_qty else 0.0,
            top_tools=top,by_plant=by_plant,
        )
    def reservation_items(c,reservation_id):
        return {r['tool']:r['qty'] for r in c.execute('SELECT tool,qty FROM reservation_lines WHERE reservation_id=?',(reservation_id,))}
    def open_loans_for(c,mode,user_id):
        """FIFO remaining qty per borrow event; overdue when today >= due + 1 day."""
        borrows=c.execute(
            "SELECT e.id,e.rent_start,e.rent_due,e.created,e.plant FROM events e "
            "WHERE e.mode=? AND e.user_id=? AND e.kind='borrow' ORDER BY e.id",(mode,user_id)).fetchall()
        remaining={}
        meta={}
        for b in borrows:
            items={r['tool']:r['qty'] for r in c.execute('SELECT tool,qty FROM lines WHERE event_id=?',(b['id'],))}
            remaining[b['id']]=dict(items);meta[b['id']]=b
        returns=c.execute(
            "SELECT e.id FROM events e WHERE e.mode=? AND e.user_id=? AND e.kind='return' ORDER BY e.id",(mode,user_id)).fetchall()
        for ret in returns:
            for row in c.execute('SELECT tool,qty FROM lines WHERE event_id=?',(ret['id'],)):
                need=row['qty']
                for eid in list(remaining):
                    if need<=0: break
                    have=remaining[eid].get(row['tool'],0)
                    if have<=0: continue
                    take=min(have,need);remaining[eid][row['tool']]=have-take;need-=take
        day=today();loans=[]
        for eid,items in remaining.items():
            left={t:q for t,q in items.items() if q>0}
            if not left: continue
            b=meta[eid];due=date.fromisoformat(b['rent_due']) if b['rent_due'] else None
            start=b['rent_start'] or b['created'][:10]
            overdue=bool(due and day>=due+timedelta(days=1))
            loans.append(dict(id=eid,rent_start=start,rent_due=b['rent_due'],plant=b['plant'],items=left,
                              overdue=overdue,days_overdue=(day-due).days if overdue else 0))
        return loans
    def serialize_reservation(c,row):
        items=[dict(r) for r in c.execute('SELECT tool,qty FROM reservation_lines WHERE reservation_id=?',(row['id'],))]
        user=c.execute('SELECT name FROM users WHERE id=?',(row['user_id'],)).fetchone()
        due=date.fromisoformat(row['rent_due']);overdue_hold=today()>=due+timedelta(days=1) and row['status'] in ('pending','approved','active')
        return dict(id=row['id'],name=user['name'],status=row['status'],rent_start=row['rent_start'],rent_due=row['rent_due'],plant=row['plant'],
                    created=row['created'],event_id=row['event_id'],items=items,overdue=overdue_hold and row['status']=='active')
    photo_root = Path(app.config['DATABASE']).resolve().parent / 'event_photos'
    photo_root.mkdir(parents=True, exist_ok=True)
    def photo_file(event_id):
        return photo_root / f'{int(event_id)}.jpg'
    def store_event_photo(event_id, raw):
        from PIL import Image, ImageOps, UnidentifiedImageError
        if not raw: raise ValueError('촬영 이미지를 선택하세요.')
        if len(raw) > 7 * 1024 * 1024: raise ValueError('7MB 이하의 이미지를 선택하세요.')
        try:
            image = Image.open(io.BytesIO(raw)); image.verify()
            image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert('RGB')
        except (UnidentifiedImageError, OSError):
            raise ValueError('읽을 수 없는 이미지입니다. 다시 촬영하세요.')
        image.thumbnail((1280, 1280))
        out = photo_file(event_id)
        tmp = out.with_suffix('.tmp.jpg')
        image.save(tmp, format='JPEG', quality=85, optimize=True)
        tmp.replace(out)
    def decode_event_photo(value):
        if not isinstance(value,str) or not value.startswith('data:image/'):
            raise ValueError('반납하려면 촬영 사진이 반드시 필요합니다.')
        try:
            header,encoded=value.split(',',1)
            if ';base64' not in header: raise ValueError
            raw=base64.b64decode(encoded,validate=True)
        except (ValueError,binascii.Error):
            raise ValueError('반납 사진 형식이 올바르지 않습니다. 다시 촬영하세요.')
        if not raw: raise ValueError('반납하려면 촬영 사진이 반드시 필요합니다.')
        return raw
        return out
    def can_view_event(row):
        return row and (session['role'] == 'admin' or row['user_id'] == session['uid'])
    @app.before_request
    def validate_json():
        if request.method == 'POST' and request.path.startswith('/api/'):
            if request.path == '/api/recognize' or request.path.endswith('/photo'):
                return None
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
        url=os.environ.get('STBM_PUBLIC_URL','https://sanghyeopkim.pythonanywhere.com/')
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
            public_url=os.environ.get('STBM_PUBLIC_URL','https://sanghyeopkim.pythonanywhere.com/'),
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
            borrowed=balance(c,mode); mine=balance(c,mode,session['uid']); reserved=reserved_balance(c,mode); damaged=damaged_pending(c,mode)
            stocks=[dict(r,borrowed=borrowed.get(r['tool'],0),reserved=reserved.get(r['tool'],0),damaged=damaged.get(r['tool'],0),
                         available=r['total']-borrowed.get(r['tool'],0)-reserved.get(r['tool'],0)-damaged.get(r['tool'],0),
                         mine=mine.get(r['tool'],0))
                    for r in c.execute('SELECT tool,total,version FROM stock WHERE mode=? ORDER BY rowid',(mode,))]
            where='e.mode=?';args=[mode]
            if session['role']!='admin': where+=' AND e.user_id=?';args.append(session['uid'])
            events=[dict(r) for r in c.execute('SELECT e.id,u.name,e.kind,e.created,e.rent_start,e.rent_due,e.plant,l.tool,l.qty FROM events e JOIN users u ON u.id=e.user_id JOIN lines l ON l.event_id=e.id WHERE '+where+' ORDER BY e.id DESC LIMIT 200',args)]
            holders=[];plant_holders=[];adjustments=[]
            if session['role']=='admin':
                holders=[dict(r) for r in c.execute("SELECT u.name,l.tool,SUM(CASE WHEN e.kind='borrow' THEN l.qty ELSE -l.qty END) qty FROM events e JOIN lines l ON l.event_id=e.id JOIN users u ON u.id=e.user_id WHERE e.mode=? GROUP BY u.id,l.tool HAVING qty>0",(mode,))]
                plant_holders=[dict(r) for r in c.execute("SELECT e.plant,l.tool,SUM(CASE WHEN e.kind='borrow' THEN l.qty ELSE -l.qty END) qty FROM events e JOIN lines l ON l.event_id=e.id WHERE e.mode=? AND e.plant IS NOT NULL GROUP BY e.plant,l.tool HAVING qty>0 ORDER BY e.plant,l.tool",(mode,))]
                adjustments=[dict(r) for r in c.execute('SELECT a.id,u.name,a.tool,a.before_qty,a.after_qty,a.reason,a.created FROM adjustments a JOIN users u ON u.id=a.user_id WHERE a.mode=? ORDER BY a.id DESC LIMIT 50',(mode,))]
            return_count=c.execute("SELECT count(*) FROM events e WHERE "+where+" AND e.kind='return'",args).fetchone()[0]
            movement=[dict(r) for r in c.execute("SELECT l.tool,SUM(CASE WHEN e.kind='borrow' THEN l.qty ELSE 0 END) borrowed,SUM(CASE WHEN e.kind='return' THEN l.qty ELSE 0 END) returned FROM events e JOIN lines l ON l.event_id=e.id WHERE "+where+" GROUP BY l.tool",args)]
            groups=[dict(r) for r in c.execute('SELECT e.id,u.name,e.kind,e.created,e.status,e.rent_start,e.rent_due,e.compare_event_id,e.plant FROM events e JOIN users u ON u.id=e.user_id WHERE '+where+' ORDER BY e.id DESC LIMIT 200',args)]
            for group in groups:
                group['items']=[dict(r) for r in c.execute('SELECT tool,qty FROM lines WHERE event_id=?',(group['id'],))]
                group['status']='완료' if group['status']=='completed' else group['status']
                group['has_photo']=photo_file(group['id']).is_file()
                cid=group.get('compare_event_id')
                group['has_compare_photo']=bool(cid and photo_file(cid).is_file())
                group['loan_rent_start']=group['loan_rent_due']=None
                if group['kind']=='return' and cid:
                    linked=c.execute('SELECT rent_start,rent_due FROM events WHERE id=?',(cid,)).fetchone()
                    if linked:
                        group['loan_rent_start']=linked['rent_start'];group['loan_rent_due']=linked['rent_due']
            users=[dict(r) for r in c.execute('SELECT id,name,role FROM users ORDER BY id')] if session['role']=='admin' else []
            if session['role']=='admin':
                res_rows=c.execute('SELECT * FROM reservations WHERE mode=? ORDER BY id DESC LIMIT 100',(mode,)).fetchall()
            else:
                res_rows=c.execute('SELECT * FROM reservations WHERE mode=? AND user_id=? ORDER BY id DESC LIMIT 100',(mode,session['uid'])).fetchall()
            reservations=[serialize_reservation(c,r) for r in res_rows]
            loans=open_loans_for(c,mode,session['uid'])
            overdue=[x for x in loans if x['overdue']]
            active_loans=[]
            damages=[]
            if session['role']=='admin':
                overdue=[];active_loans=[]
                for u in c.execute('SELECT id,name FROM users').fetchall():
                    for loan in open_loans_for(c,mode,u['id']):
                        row=dict(loan,name=u['name'])
                        active_loans.append(row)
                        if loan['overdue']: overdue.append(row)
                for d in c.execute(
                    "SELECT d.id,d.event_id,d.tool,d.qty,d.note,d.status,d.created,d.issue,u.name FROM damage_reports d "
                    "JOIN users u ON u.id=d.user_id WHERE d.mode=? ORDER BY CASE d.status WHEN 'pending' THEN 0 ELSE 1 END, d.id DESC LIMIT 100",(mode,)):
                    damages.append(dict(d))
            else:
                for d in c.execute(
                    "SELECT d.id,d.event_id,d.tool,d.qty,d.note,d.status,d.created,d.issue,u.name FROM damage_reports d "
                    "JOIN users u ON u.id=d.user_id WHERE d.mode=? AND d.user_id=? ORDER BY d.id DESC LIMIT 50",(mode,session['uid'])):
                    damages.append(dict(d))
            borrow_photos=[]
            for loan in loans:
                if photo_file(loan['id']).is_file():
                    borrow_photos.append(dict(id=loan['id'],rent_start=loan['rent_start'],rent_due=loan['rent_due'],items=loan['items'],overdue=loan['overdue'],plant=loan.get('plant')))
            report=weekly_report(c,mode) if session['role']=='admin' else None
        return jsonify(stock=stocks,events=events,holders=holders,plant_holders=plant_holders,adjustments=adjustments,return_count=return_count,
                       movement=movement,groups=groups,users=users,reservations=reservations,loans=loans,overdue=overdue,
                       active_loans=active_loans,damages=damages,borrow_photos=borrow_photos,report=report,plants=PLANTS)
    @app.post('/api/reservations')
    @auth()
    def create_reservation():
        if session['role']=='admin':
            return jsonify(error='장기 대여 예약 신청은 작업자 계정만 가능합니다.'),403
        data=request.get_json() or {};mode=mode_of(data);token=data.get('token');items=data.get('items')
        if not isinstance(token,str) or not 16<=len(token)<=100: raise ValueError('처리 식별자가 필요합니다.')
        if not isinstance(items,dict) or not items or any(t not in TOOLS for t in items): raise ValueError('공구를 선택하세요.')
        items={t:integer(q,1) for t,q in items.items()}
        start=parse_day(data.get('rent_start'),'대여 시작일');due=parse_day(data.get('rent_due'),'반납 예정일');validate_period(start,due)
        plant=parse_plant(data.get('plant'))
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM reservations WHERE token=?',(token,)).fetchone()
            if old:
                same=(old['user_id']==session['uid'] and old['mode']==mode and old['rent_start']==start.isoformat()
                      and old['rent_due']==due.isoformat() and old['plant']==plant and reservation_items(c,old['id'])==items)
                if not same: raise ValueError('이미 다른 처리에 사용된 식별자입니다.')
                return jsonify(ok=True,id=old['id'],duplicate=True,status=old['status'],plant=old['plant']),200
            borrowed=balance(c,mode);reserved=reserved_balance(c,mode);damaged=damaged_pending(c,mode)
            for tool,qty in items.items():
                total=c.execute('SELECT total FROM stock WHERE mode=? AND tool=?',(mode,tool)).fetchone()['total']
                free=total-borrowed.get(tool,0)-reserved.get(tool,0)-damaged.get(tool,0)
                if qty>free: raise ValueError(f'{tool}: 예약 가능 수량(대여중·예약·파손대기 제외)을 초과했습니다. 가능 {max(free,0)}개')
            cur=c.execute(
                "INSERT INTO reservations(token,user_id,mode,status,rent_start,rent_due,created,plant) VALUES(?,?,?,?,?,?,?,?)",
                (token,session['uid'],mode,'pending',start.isoformat(),due.isoformat(),now(),plant))
            rid=cur.lastrowid
            for tool,qty in items.items(): c.execute('INSERT INTO reservation_lines VALUES(?,?,?)',(rid,tool,qty))
        return jsonify(ok=True,id=rid,status='pending',rent_start=start.isoformat(),rent_due=due.isoformat(),plant=plant),201
    @app.post('/api/reservations/<int:rid>/<action>')
    @auth()
    def decide_reservation(rid,action):
        if action not in ['approve','reject','cancel']: raise ValueError('처리할 수 없는 요청입니다.')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM reservations WHERE id=?',(rid,)).fetchone()
            if not row: return jsonify(error='예약을 찾을 수 없습니다.'),404
            if action=='cancel':
                if row['user_id']!=session['uid'] and session['role']!='admin': return jsonify(error='본인 예약만 취소할 수 있습니다.'),403
                if row['status'] not in ('pending','approved'): raise ValueError('이미 처리된 예약은 취소할 수 없습니다.')
                c.execute("UPDATE reservations SET status='cancelled',decided_at=?,decided_by=? WHERE id=?",(now(),session['uid'],rid))
                return jsonify(ok=True,status='cancelled')
            if session['role']!='admin': return jsonify(error='관리자만 승인/거절할 수 있습니다.'),403
            if row['status']!='pending': raise ValueError('대기 중 예약만 승인·거절할 수 있습니다.')
            status='approved' if action=='approve' else 'rejected'
            if action=='approve':
                borrowed=balance(c,row['mode']);reserved=reserved_balance(c,row['mode']);damaged=damaged_pending(c,row['mode'])
                # pending already counted in reserved; temporarily ignore this reservation by subtracting its items
                mine_items=reservation_items(c,rid)
                for tool,qty in mine_items.items():
                    total=c.execute('SELECT total FROM stock WHERE mode=? AND tool=?',(row['mode'],tool)).fetchone()['total']
                    held=reserved.get(tool,0)-qty
                    free=total-borrowed.get(tool,0)-max(held,0)-damaged.get(tool,0)
                    if qty>free: raise ValueError(f'{tool}: 승인 시점 가용 수량이 부족합니다.')
            c.execute('UPDATE reservations SET status=?,decided_at=?,decided_by=? WHERE id=?',(status,now(),session['uid'],rid))
        return jsonify(ok=True,status=status)
    @app.post('/api/events')
    @auth()
    def event():
        data=request.get_json() or {};mode=mode_of(data);kind=data.get('kind');token=data.get('token');items=data.get('items')
        if kind not in ['borrow','return']: raise ValueError('대여 또는 반납을 선택하세요.')
        if not isinstance(token,str) or not 16<=len(token)<=100: raise ValueError('처리 식별자가 필요합니다.')
        if not isinstance(items,dict) or not items or any(t not in TOOLS for t in items): raise ValueError('공구를 선택하세요.')
        items={t:integer(q,1) for t,q in items.items()}
        reservation_id=data.get('reservation_id')
        rent_start=rent_due=None
        plant=None
        damage={}
        damage_note=''
        if kind=='borrow':
            if reservation_id is not None and type(reservation_id) is not int: raise ValueError('예약 선택이 올바르지 않습니다.')
            start=parse_day(data.get('rent_start'),'대여 시작일');due=parse_day(data.get('rent_due'),'반납 예정일');validate_period(start,due)
            rent_start,rent_due=start.isoformat(),due.isoformat()
            plant=parse_plant(data.get('plant'))
        issues={}
        return_photo=None
        if kind=='return':
            return_photo=decode_event_photo(data.get('photo_data'))
            raw_damage=data.get('damage') or {}
            raw_issues=data.get('issues') or {}
            if not isinstance(raw_damage,dict) or not isinstance(raw_issues,dict): raise ValueError('파손/수리 정보가 올바르지 않습니다.')
            for tool,qty in items.items():
                dmg=raw_damage.get(tool,0)
                if dmg in (None,''): dmg=0
                if type(dmg) is not int or dmg<0: raise ValueError(f'{tool}: 이상 수량은 0 이상 정수여야 합니다.')
                if dmg>qty: raise ValueError(f'{tool}: 이상 수량은 반납 수량을 초과할 수 없습니다.')
                if not dmg: continue
                issue=raw_issues.get(tool,'파손')
                if issue not in ISSUE_TYPES: raise ValueError(f'{tool}: 상태는 파손 또는 수리 필요만 가능합니다.')
                damage[tool]=dmg;issues[tool]=issue
            note=data.get('damage_note','')
            if note is None: note=''
            if not isinstance(note,str): raise ValueError('파손/수리 메모 형식이 올바르지 않습니다.')
            damage_note=note.strip()[:200]
            if damage and not damage_note: damage_note='반납 시 이상 신고'
        payload=json.dumps([mode,kind,items,rent_start,rent_due,reservation_id,plant,damage,issues,damage_note],sort_keys=True)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM events WHERE token=?',(token,)).fetchone()
            if old:
                if old['user_id']!=session['uid'] or old['payload']!=payload: raise ValueError('이미 다른 처리에 사용된 식별자입니다.')
                return jsonify(ok=True,id=old['id'],duplicate=True,created=old['created'],name=session['name'],kind=kind,items=items,
                               rent_start=old['rent_start'],rent_due=old['rent_due'],plant=old['plant'],damage=damage,issues=issues,
                               compare_event_id=old['compare_event_id'],has_photo=photo_file(old['id']).is_file())
            borrowed=balance(c,mode);mine=balance(c,mode,session['uid']);reserved=reserved_balance(c,mode);damaged=damaged_pending(c,mode)
            linked=None;compare_id=None
            if kind=='borrow' and reservation_id is not None:
                linked=c.execute('SELECT * FROM reservations WHERE id=?',(reservation_id,)).fetchone()
                if not linked or linked['user_id']!=session['uid'] or linked['mode']!=mode:
                    raise ValueError('연결할 예약을 찾을 수 없습니다.')
                if linked['status']!='approved': raise ValueError('승인된 예약만 실제 대여로 전환할 수 있습니다.')
                if linked['rent_start']!=rent_start or linked['rent_due']!=rent_due:
                    raise ValueError('예약된 대여 기간과 입력한 기간이 다릅니다.')
                if (linked['plant'] or '')!=plant: raise ValueError('예약된 사용 공정과 입력한 공정이 다릅니다.')
                booked=reservation_items(c,reservation_id)
                if items!=booked: raise ValueError('예약된 공구·수량과 동일하게 대여해야 합니다.')
            if kind=='return':
                compare_id=pick_compare_borrow(c,mode,session['uid'],items)
            for tool,qty in items.items():
                total=c.execute('SELECT total FROM stock WHERE mode=? AND tool=?',(mode,tool)).fetchone()['total']
                if kind=='borrow':
                    hold=reserved.get(tool,0)-(booked.get(tool,0) if linked else 0)
                    pending_dmg=damaged.get(tool,0)
                    if qty>total-borrowed.get(tool,0)-max(hold,0)-pending_dmg: raise ValueError(tool+': 대여 가능 수량을 초과했습니다.')
                if kind=='return' and qty>mine.get(tool,0): raise ValueError(tool+': 본인의 대여 수량을 초과했습니다.')
            c_time=now()
            cur=c.execute(
                'INSERT INTO events(token,user_id,mode,kind,created,payload,rent_start,rent_due,reservation_id,compare_event_id,plant) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (token,session['uid'],mode,kind,c_time,payload,rent_start,rent_due,reservation_id,compare_id,plant))
            event_id=cur.lastrowid
            for tool,qty in items.items(): c.execute('INSERT INTO lines VALUES(?,?,?)',(event_id,tool,qty))
            if linked:
                c.execute("UPDATE reservations SET status='active',event_id=? WHERE id=?",(event_id,reservation_id))
            if kind=='return':
                for tool,qty in damage.items():
                    c.execute(
                        "INSERT INTO damage_reports(event_id,user_id,mode,tool,qty,note,status,created,issue) VALUES(?,?,?,?,?,?,?,?,?)",
                        (event_id,session['uid'],mode,tool,qty,damage_note,'pending',c_time,issues[tool]))
                open_ids={l['id'] for l in open_loans_for(c,mode,session['uid'])}
                for row in c.execute("SELECT id,event_id FROM reservations WHERE user_id=? AND mode=? AND status='active'",(session['uid'],mode)):
                    if row['event_id'] and row['event_id'] not in open_ids:
                        c.execute("UPDATE reservations SET status='returned' WHERE id=?",(row['id'],))
                store_event_photo(event_id,return_photo)
        return jsonify(ok=True,id=event_id,created=c_time,name=session['name'],kind=kind,items=items,
                       rent_start=rent_start,rent_due=rent_due,plant=plant,damage=damage,issues=issues,
                       compare_event_id=compare_id,has_photo=kind=='return'),201
    @app.post('/api/events/<int:event_id>/photo')
    @auth()
    def upload_event_photo(event_id):
        with db() as c:
            row=c.execute('SELECT id,user_id FROM events WHERE id=?',(event_id,)).fetchone()
        if not can_view_event(row): return jsonify(error='기록을 찾을 수 없습니다.'),404
        if row['user_id']!=session['uid'] and session['role']!='admin':
            return jsonify(error='본인 기록에만 사진을 추가할 수 있습니다.'),403
        image=request.files.get('image')
        if image is None: raise ValueError('촬영 이미지를 선택하세요.')
        store_event_photo(event_id, image.read())
        return jsonify(ok=True,id=event_id,has_photo=True)
    @app.get('/api/events/<int:event_id>/photo')
    @auth()
    def get_event_photo(event_id):
        with db() as c:
            row=c.execute('SELECT id,user_id FROM events WHERE id=?',(event_id,)).fetchone()
        if not can_view_event(row): return jsonify(error='기록을 찾을 수 없습니다.'),404
        path=photo_file(event_id)
        if not path.is_file(): return jsonify(error='저장된 사진이 없습니다.'),404
        return send_file(path, mimetype='image/jpeg', max_age=3600)
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
            held=balance(c,mode).get(tool,0)+damaged_pending(c,mode).get(tool,0)
            if total<held: raise ValueError('전체 보유 수량은 대여 중·파손 대기 수량보다 작을 수 없습니다.')
            if total==row['total']: raise ValueError('변경된 수량이 없습니다.')
            if reason=='신규 구매 및 추가' and total<row['total']: raise ValueError('신규 구매는 수량이 증가해야 합니다.')
            if reason in ('폐기','파손') and total>row['total']: raise ValueError('폐기·파손은 수량이 감소해야 합니다.')
            c.execute('UPDATE stock SET total=?,version=version+1 WHERE mode=? AND tool=?',(total,mode,tool))
            c.execute('INSERT INTO adjustments(token,user_id,mode,tool,before_qty,after_qty,reason,created) VALUES(?,?,?,?,?,?,?,?)',(token,session['uid'],mode,tool,row['total'],total,reason,now()))
        return jsonify(ok=True)
    @app.post('/api/damages/<int:did>/<action>')
    @auth(admin=True)
    def decide_damage(did,action):
        if action not in ['process','dismiss','repair']: raise ValueError('처리할 수 없는 요청입니다.')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM damage_reports WHERE id=?',(did,)).fetchone()
            if not row: return jsonify(error='파손/수리 신고를 찾을 수 없습니다.'),404
            if row['status']!='pending': raise ValueError('이미 처리된 신고입니다.')
            if action=='dismiss':
                c.execute("UPDATE damage_reports SET status='dismissed',processed_at=?,processed_by=? WHERE id=?",(now(),session['uid'],did))
                return jsonify(ok=True,status='dismissed')
            if action=='repair':
                if row['issue']!='수리 필요': raise ValueError('수리 필요 신고만 수리 완료 처리할 수 있습니다.')
                c.execute("UPDATE damage_reports SET status='repaired',processed_at=?,processed_by=? WHERE id=?",(now(),session['uid'],did))
                return jsonify(ok=True,status='repaired')
            stock_row=c.execute('SELECT * FROM stock WHERE mode=? AND tool=?',(row['mode'],row['tool'])).fetchone()
            borrowed=balance(c,row['mode']).get(row['tool'],0)
            pending=damaged_pending(c,row['mode']).get(row['tool'],0)
            after_total=stock_row['total']-row['qty']
            remaining_pending=pending-row['qty']
            if after_total<borrowed+remaining_pending:
                raise ValueError('재고에서 제외하면 대여 중 수량보다 보유가 적어집니다.')
            if after_total<0: raise ValueError('재고 수량이 부족합니다.')
            reason='파손' if row['issue']=='파손' else '폐기'
            c.execute('UPDATE stock SET total=?,version=version+1 WHERE mode=? AND tool=?',(after_total,row['mode'],row['tool']))
            token=f'damage-{did}-{secrets.token_hex(8)}'
            c.execute('INSERT INTO adjustments(token,user_id,mode,tool,before_qty,after_qty,reason,created) VALUES(?,?,?,?,?,?,?,?)',
                      (token,session['uid'],row['mode'],row['tool'],stock_row['total'],after_total,reason,now()))
            c.execute("UPDATE damage_reports SET status='processed',processed_at=?,processed_by=? WHERE id=?",(now(),session['uid'],did))
        return jsonify(ok=True,status='processed',tool=row['tool'],before=stock_row['total'],after=after_total,issue=row['issue'])
    return app

if __name__=='__main__': create_app().run(host='127.0.0.1',port=int(os.environ.get('PORT','8001')),debug=False)
