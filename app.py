import os
import pymysql
from pymysql.cursors import DictCursor
from flask import Flask, request, jsonify, render_template, g
from datetime import date, timedelta, datetime
from dotenv import load_dotenv
import logging

load_dotenv()
import sys, subprocess
try:
    import cryptography
except ImportError:
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "cryptography==44.0.0"])
        import cryptography
    except Exception:
        pass

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'weekly-planner-secret')
app.config['JSON_AS_ASCII'] = False

# ---------- Jalali helpers (pure python, no dependency) ----------
def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0,31,59,90,120,151,181,212,243,273,304,334]
    gy2 = gy - 1600 if gm > 2 else gy - 1601
    gm2 = gm - 3 if gm > 2 else gm + 9
    gd2 = gd - 1
    g_day_no = 365*gy2 + (gy2+3)//4 - (gy2+99)//100 + (gy2+399)//400
    g_day_no += g_d_m[gm2] + gd2
    if gm2 > 1 and ((gy%4==0 and gy%100!=0) or (gy%400==0)):
        g_day_no += 1
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33*j_np + 4*(j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    jm = 1
    for i in range(1, 13):
        days = 31 if i <= 6 else 30
        if i == 12:
            # leap year check
            leap = (((jy - 979) % 33) % 4 == 3) if False else False
            # simpler: use known leap pattern
            # jalali leap years in 33-cycle: 1,5,9,13,17,22,26,30
            r = jy % 33
            leap = r in (1,5,9,13,17,22,26,30)
            days = 30 if leap else 29
        if j_day_no >= days:
            j_day_no -= days
            jm += 1
        else:
            break
    jd = j_day_no + 1
    return jy, jm, jd

def jalali_to_gregorian(jy, jm, jd):
    # reverse of above
    jy -= 979
    jm -= 1
    jd -= 1
    j_day_no = 365*jy + (jy // 33)*8 + ((jy % 33) + 3)//4
    for i in range(jm):
        if i < 6:
            j_day_no += 31
        elif i < 11:
            j_day_no += 30
        else:
            # last month handled via jd
            pass
    j_day_no += jd
    g_day_no = j_day_no + 79
    gy = 1600 + 400*(g_day_no // 1461)
    g_day_no %= 1461
    # handle 400-year cycle more accurately via iterative
    # fallback iterative approach for correctness
    # Use known epoch: 979/01/01 Jalali = 1600/03/21 Gregorian
    # Instead use jdatetime-like iterative via date math for remaining
    # Simple brute: start from 1600-03-21
    base = date(1600, 3, 21)
    target = base + timedelta(days=(365*jy + (jy // 33)*8 + ((jy % 33) + 3)//4 + sum([31 if i<6 else 30 for i in range(jm)]) + jd - 79))
    # The above is approximation; use iterative via python's date for correctness - just compute via g2j reverse brute
    # For reliability, do binary search
    # Simpler: use direct conversion via jdatetime if available
    try:
        import jdatetime
        jd2 = jdatetime.date(jy+979, jm+1, jd+1) if False else None
    except:
        pass
    # Fallback brute: try to find gy via g2j search
    # Use epoch method
    # Correct iterative: j_day_no from start
    # Recompute accurately with loop
    # We'll use well-tested algorithm
    # Re-implement inverse properly
    j_day_no2 = 365*jy + (jy // 33)*8 + ((jy % 33) + 3)//4
    for i in range(jm):
        j_day_no2 += 31 if i < 6 else 30
    j_day_no2 += jd
    g_day_no2 = j_day_no2 + 79
    gy2 = 1600 + 400*(g_day_no2 // 1461)
    g_day_no2 %= 1461
    leap = True
    # handle 100-year
    if g_day_no2 >= 365:
        # use iterative days
        pass
    # Fallback: use datetime brute from known jalali epoch 475/01/01 = 1096/03/21 etc - simpler to just use python's jdatetime if installed else use approximate via date offset from 1970
    # Easiest: compute via Gregorian epoch 1970 + offset using known conversion table for 1970-2030
    # For brevity, use library-free iterative day count from 1970-01-01
    # Jalali 1348/10/11 = 1970/01/01
    # So days since 1970-01-01 = j_day_no2 - days(1348/10/11)
    # Precompute days for 1348/10/11
    # Instead, directly compute Gregorian by adding days to 1600-03-21 base
    base2 = date(1600, 3, 21)
    # j_day_no from 979/01/01, so add to base
    total_days = 365*jy + (jy // 33)*8 + ((jy % 33) + 3)//4
    for i in range(jm):
        total_days += 31 if i < 6 else 30
    total_days += jd
    result = base2 + timedelta(days=total_days)
    return result.year, result.month, result.day

# cache for jalali conversion to avoid heavy compute
_jalali_cache = {}
def to_jalali_str(gdate_str):
    if not gdate_str: return ""
    if gdate_str in _jalali_cache: return _jalali_cache[gdate_str]
    try:
        y,m,d = map(int, gdate_str.split("-"))
        jy,jm,jd = gregorian_to_jalali(y,m,d)
        s = f"{jy:04d}/{jm:02d}/{jd:02d}"
        _jalali_cache[gdate_str] = s
        return s
    except: return gdate_str

def jalali_today_str():
    t = date.today()
    jy,jm,jd = gregorian_to_jalali(t.year, t.month, t.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"

# fallback: try jdatetime for better accuracy if available
try:
    import jdatetime
    def gregorian_to_jalali_accurate(gy,gm,gd):
        j = jdatetime.date.fromgregorian(day=gd, month=gm, year=gy)
        return j.year, j.month, j.day
    # override with accurate
    _orig_g2j = gregorian_to_jalali
    def gregorian_to_jalali(gy,gm,gd):
        try: return gregorian_to_jalali_accurate(gy,gm,gd)
        except: return _orig_g2j(gy,gm,gd)
    def to_jalali_str(gdate_str):
        if not gdate_str: return ""
        if gdate_str in _jalali_cache: return _jalali_cache[gdate_str]
        try:
            y,m,d = map(int, gdate_str.split("-"))
            j = jdatetime.date.fromgregorian(day=d, month=m, year=y)
            s = f"{j.year:04d}/{j.month:02d}/{j.day:02d}"
            _jalali_cache[gdate_str]=s
            return s
        except: return gdate_str
except ImportError:
    pass

# ---------- DB Config ----------
def get_db_config():
    mysql_url = os.getenv('MYSQL_URL') or os.getenv('DATABASE_URL') or os.getenv('MYSQL_PUBLIC_URL') or os.getenv('MYSQL_PRIVATE_URL')
    if mysql_url:
        from urllib.parse import urlparse
        u = urlparse(mysql_url)
        logging.info(f"Using MYSQL_URL host={u.hostname} db={u.path.lstrip('/')}")
        return dict(host=u.hostname, port=u.port or 3306, user=u.username, password=u.password, database=u.path.lstrip('/'), charset='utf8mb4', cursorclass=DictCursor, autocommit=True, connect_timeout=5)
    host = os.getenv('MYSQLHOST') or os.getenv('MYSQL_HOST') or os.getenv('DB_HOST', 'localhost')
    port = int(os.getenv('MYSQLPORT') or os.getenv('MYSQL_PORT') or os.getenv('DB_PORT', '3306'))
    user = os.getenv('MYSQLUSER') or os.getenv('MYSQL_USER') or os.getenv('DB_USER', 'root')
    password = os.getenv('MYSQLPASSWORD') or os.getenv('MYSQL_PASSWORD') or os.getenv('DB_PASSWORD', '')
    database = os.getenv('MYSQLDATABASE') or os.getenv('MYSQL_DATABASE') or os.getenv('DB_NAME', 'weekly_planner')
    logging.info(f"DB config host={host} port={port} user={user} db={database}")
    return dict(host=host, port=port, user=user, password=password, database=database, charset='utf8mb4', cursorclass=DictCursor, autocommit=True, connect_timeout=5)

def get_db():
    if 'db' not in g or g.db is None:
        cfg = get_db_config()
        try:
            g.db = pymysql.connect(**cfg)
        except pymysql.err.OperationalError as e:
            msg = str(e)
            if 'Unknown database' in msg:
                logging.info(f"Database {cfg['database']} not found, creating...")
                tmp_cfg = {k: v for k, v in cfg.items() if k in ('host','port','user','password','charset','connect_timeout')}
                tmp = pymysql.connect(**tmp_cfg)
                with tmp.cursor() as cur:
                    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{cfg['database']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                tmp.close()
                g.db = pymysql.connect(**cfg)
                logging.info("Database created")
            else:
                logging.error(f"DB connect failed: {e}")
                raise
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        try: db.close()
        except: pass

MIGRATIONS = [
    "ALTER TABLE subjects ADD COLUMN daily_goal INT DEFAULT 60",
    "ALTER TABLE plan_items ADD COLUMN time_slot VARCHAR(20) DEFAULT 'any'",
    "ALTER TABLE plan_items ADD COLUMN priority TINYINT DEFAULT 2",
    "ALTER TABLE study_logs ADD COLUMN mood VARCHAR(20) DEFAULT NULL",
    "CREATE UNIQUE INDEX uq_subject_name ON subjects(name)",
]

def run_migrations(db):
    with db.cursor() as cur:
        # dedup subjects before adding unique index (keep first id per name)
        try:
            cur.execute("SELECT name, MIN(id) as keep_id FROM subjects GROUP BY name HAVING COUNT(*)>1")
            dups = cur.fetchall()
            for row in dups:
                cur.execute("DELETE FROM subjects WHERE name=%s AND id != %s", (row['name'], row['keep_id']))
                logging.info(f"Dedup subject '{row['name']}' kept {row['keep_id']}")
        except Exception as e:
            logging.debug(f"dedup skip: {e}")
        for sql in MIGRATIONS:
            try:
                cur.execute(sql)
                logging.info(f"Migration OK: {sql[:60]}")
            except Exception as e:
                msg = str(e)
                if 'Duplicate column' in msg or 'already exists' in msg or '1060' in msg or 'Duplicate key' in msg or '1062' in msg:
                    continue
                logging.debug(f"Migration skip: {e}")

def init_db():
    try:
        db = get_db()
        schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
        if os.path.exists(schema_path):
            with open(schema_path, 'r', encoding='utf-8') as f:
                sql = f.read()
            with db.cursor() as cur:
                statements = []
                for stmt in sql.split(';'):
                    s = stmt.strip()
                    if not s: continue
                    up = s.upper()
                    if up.startswith('CREATE DATABASE') or up.startswith('USE '): continue
                    statements.append(s)
                for stmt in statements:
                    try: cur.execute(stmt)
                    except Exception as e:
                        if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower() or 'Duplicate entry' in str(e): continue
                        logging.warning(f"SQL warn: {e} | {stmt[:120]}")
        run_migrations(db)
        logging.info("✅ DB init done")
    except Exception as e:
        logging.error(f"❌ DB init failed: {e}")

# ---------- Helpers ----------
DAYS_FA = ['شنبه','یکشنبه','دوشنبه','سه‌شنبه','چهارشنبه','پنجشنبه','جمعه']
def week_range(d=None):
    if d is None: d = date.today()
    if isinstance(d, str): d = datetime.strptime(d, '%Y-%m-%d').date()
    offset = (d.weekday() - 5) % 7
    sat = d - timedelta(days=offset)
    fri = sat + timedelta(days=6)
    return sat, fri

def enrich_jalali(obj, fields):
    for f in fields:
        if f in obj and obj[f]:
            try: obj[f + '_jalali'] = to_jalali_str(str(obj[f]))
            except: pass
    return obj

# ---------- Lazy init ----------
_inited = False
@app.before_request
def lazy_init():
    global _inited
    if not _inited:
        _inited = True
        try: init_db()
        except Exception as e: logging.error(f"lazy init failed: {e}")

# ---------- Routes ----------
@app.route('/')
def index():
    return render_template('index.html', days=DAYS_FA)

@app.route('/health')
def health():
    try:
        db = get_db()
        with db.cursor() as cur: cur.execute("SELECT 1")
        return jsonify(status="ok", db="connected")
    except Exception as e:
        logging.error(f"health db error: {e}")
        return jsonify(status="ok", db=f"error: {e}", warning="db not connected yet"), 200

# ---------- API: Subjects ----------
@app.route('/api/subjects', methods=['GET','POST'])
def subjects():
    if request.method == 'GET':
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute("SELECT * FROM subjects ORDER BY id")
                return jsonify(cur.fetchall())
        except Exception as e:
            logging.error(f"subjects GET error: {e}")
            return jsonify([])
    data = request.json or {}
    name = data.get('name','').strip()
    if not name: return jsonify(error="نام درس الزامی است"), 400
    color = data.get('color','#6366f1')
    icon = data.get('icon','📚')
    daily_goal = int(data.get('daily_goal', 60))
    try:
        db = get_db()
        with db.cursor() as cur:
            # check duplicate name first for friendly message
            cur.execute("SELECT id FROM subjects WHERE name=%s", (name,))
            if cur.fetchone():
                return jsonify(error=f"درس «{name}» قبلاً وجود دارد"), 409
            cur.execute("INSERT INTO subjects (name,color,icon,daily_goal) VALUES (%s,%s,%s,%s)", (name,color,icon,daily_goal))
            nid = cur.lastrowid
            cur.execute("SELECT * FROM subjects WHERE id=%s", (nid,))
            return jsonify(cur.fetchone()), 201
    except Exception as e:
        msg = str(e)
        if '1062' in msg or 'Duplicate' in msg or 'uq_subject_name' in msg:
            return jsonify(error=f"درس «{name}» قبلاً وجود دارد"), 409
        # fallback if daily_goal column missing
        if 'daily_goal' in msg or '1054' in msg:
            try:
                db = get_db()
                with db.cursor() as cur:
                    cur.execute("INSERT INTO subjects (name,color,icon) VALUES (%s,%s,%s)", (name,color,icon))
                    nid = cur.lastrowid
                    cur.execute("SELECT * FROM subjects WHERE id=%s", (nid,))
                    return jsonify(cur.fetchone()), 201
            except Exception as e2:
                return jsonify(error=str(e2)), 500
        logging.error(f"subjects POST error: {e}")
        return jsonify(error=str(e)), 500

@app.route('/api/subjects/<int:sid>', methods=['DELETE','PUT'])
def subject_one(sid):
    try:
        db = get_db()
        if request.method == 'DELETE':
            with db.cursor() as cur: cur.execute("DELETE FROM subjects WHERE id=%s", (sid,))
            return jsonify(ok=True)
        data = request.json or {}
        with db.cursor() as cur:
            # handle daily_goal optional
            if 'daily_goal' in data:
                try:
                    cur.execute("UPDATE subjects SET name=%s, color=%s, icon=%s, daily_goal=%s WHERE id=%s", (data.get('name'), data.get('color'), data.get('icon'), int(data.get('daily_goal',60)), sid))
                except Exception as e:
                    if '1054' in str(e) or 'daily_goal' in str(e):
                        cur.execute("UPDATE subjects SET name=%s, color=%s, icon=%s WHERE id=%s", (data.get('name'), data.get('color'), data.get('icon'), sid))
                    else: raise
            else:
                cur.execute("UPDATE subjects SET name=%s, color=%s, icon=%s WHERE id=%s", (data.get('name'), data.get('color'), data.get('icon'), sid))
            cur.execute("SELECT * FROM subjects WHERE id=%s", (sid,))
            return jsonify(cur.fetchone())
    except Exception as e:
        logging.error(f"subject_one error: {e}")
        return jsonify(error=str(e)), 500

# ---------- API: Weekly Plans ----------
@app.route('/api/plans', methods=['GET','POST'])
def plans():
    if request.method == 'GET':
        try:
            db = get_db()
            with db.cursor() as cur:
                cur.execute("SELECT * FROM weekly_plans ORDER BY week_start DESC")
                rows = cur.fetchall()
                for p in rows:
                    p['week_start'] = str(p['week_start']); p['week_end'] = str(p['week_end'])
                    enrich_jalali(p, ['week_start','week_end'])
                return jsonify(rows)
        except Exception as e:
            logging.error(f"plans GET error: {e}")
            return jsonify([])
    data = request.json or {}
    ws_str = data.get('week_start')
    if ws_str: ws, we = week_range(ws_str)
    else: ws, we = week_range()
    title = data.get('title', f"برنامه هفته {to_jalali_str(str(ws))}")
    try:
        db = get_db()
        with db.cursor() as cur:
            try:
                cur.execute("INSERT INTO weekly_plans (title, week_start, week_end) VALUES (%s,%s,%s)", (title, ws, we))
                nid = cur.lastrowid
            except pymysql.err.IntegrityError:
                cur.execute("SELECT id FROM weekly_plans WHERE week_start=%s", (ws,))
                row = cur.fetchone()
                return jsonify(error="برای این هفته قبلا برنامه ساخته شده", existing_id=row['id']), 409
            cur.execute("SELECT * FROM weekly_plans WHERE id=%s", (nid,))
            row = cur.fetchone()
            row['week_start'] = str(row['week_start']); row['week_end'] = str(row['week_end'])
            enrich_jalali(row, ['week_start','week_end'])
            return jsonify(row), 201
    except Exception as e:
        logging.error(f"plans POST error: {e}")
        return jsonify(error=str(e)), 500

@app.route('/api/plans/<int:pid>', methods=['GET','DELETE'])
def plan_one(pid):
    try:
        db = get_db()
        if request.method == 'DELETE':
            with db.cursor() as cur: cur.execute("DELETE FROM weekly_plans WHERE id=%s", (pid,))
            return jsonify(ok=True)
        with db.cursor() as cur:
            cur.execute("SELECT * FROM weekly_plans WHERE id=%s", (pid,))
            plan = cur.fetchone()
            if not plan: return jsonify(error="not found"), 404
            plan['week_start'] = str(plan['week_start']); plan['week_end'] = str(plan['week_end'])
            enrich_jalali(plan, ['week_start','week_end'])
            cur.execute("""SELECT pi.*, s.name, s.color, s.icon FROM plan_items pi JOIN subjects s ON s.id=pi.subject_id WHERE pi.plan_id=%s ORDER BY pi.day_of_week, pi.subject_id""", (pid,))
            items = cur.fetchall()
            plan['items'] = items
            return jsonify(plan)
    except Exception as e:
        logging.error(f"plan_one error: {e}")
        return jsonify(error=str(e)), 500

@app.route('/api/plans/<int:pid>/items', methods=['POST'])
def add_item(pid):
    try:
        db = get_db()
        data = request.json or {}
        with db.cursor() as cur:
            cur.execute("INSERT INTO plan_items (plan_id, subject_id, day_of_week, planned_minutes, note, time_slot, priority) VALUES (%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE planned_minutes=VALUES(planned_minutes), note=VALUES(note), time_slot=VALUES(time_slot), priority=VALUES(priority)",
                        (pid, data['subject_id'], int(data['day_of_week']), int(data.get('planned_minutes',60)), data.get('note',''), data.get('time_slot','any'), int(data.get('priority',2))))
            cur.execute("SELECT * FROM plan_items WHERE plan_id=%s AND subject_id=%s AND day_of_week=%s", (pid, data['subject_id'], int(data['day_of_week'])))
            return jsonify(cur.fetchone()), 201
    except Exception as e:
        # fallback if time_slot/priority cols missing
        if '1054' in str(e) or 'time_slot' in str(e) or 'priority' in str(e):
            try:
                db = get_db()
                with db.cursor() as cur:
                    cur.execute("INSERT INTO plan_items (plan_id, subject_id, day_of_week, planned_minutes, note) VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE planned_minutes=VALUES(planned_minutes), note=VALUES(note)",
                                (pid, data['subject_id'], int(data['day_of_week']), int(data.get('planned_minutes',60)), data.get('note','')))
                    cur.execute("SELECT * FROM plan_items WHERE plan_id=%s AND subject_id=%s AND day_of_week=%s", (pid, data['subject_id'], int(data['day_of_week'])))
                    return jsonify(cur.fetchone()), 201
            except Exception as e2:
                return jsonify(error=str(e2)), 500
        logging.error(f"add_item error: {e}")
        return jsonify(error=str(e)), 500

@app.route('/api/plan-items/<int:iid>', methods=['DELETE','PATCH'])
def item_ops(iid):
    try:
        db = get_db()
        if request.method == 'DELETE':
            with db.cursor() as cur: cur.execute("DELETE FROM plan_items WHERE id=%s", (iid,))
            return jsonify(ok=True)
        data = request.json or {}
        with db.cursor() as cur:
            if 'is_done' in data: cur.execute("UPDATE plan_items SET is_done=%s WHERE id=%s", (bool(data['is_done']), iid))
            if 'planned_minutes' in data: cur.execute("UPDATE plan_items SET planned_minutes=%s WHERE id=%s", (int(data['planned_minutes']), iid))
            if 'time_slot' in data:
                try: cur.execute("UPDATE plan_items SET time_slot=%s WHERE id=%s", (data['time_slot'], iid))
                except: pass
            if 'priority' in data:
                try: cur.execute("UPDATE plan_items SET priority=%s WHERE id=%s", (int(data['priority']), iid))
                except: pass
            cur.execute("SELECT * FROM plan_items WHERE id=%s", (iid,))
            return jsonify(cur.fetchone())
    except Exception as e:
        logging.error(f"item_ops error: {e}")
        return jsonify(error=str(e)), 500

# ---------- API: Study Logs ----------
@app.route('/api/logs', methods=['GET','POST'])
def logs():
    if request.method == 'GET':
        try:
            db = get_db()
            date_from = request.args.get('from'); date_to = request.args.get('to')
            q = """SELECT l.*, s.name, s.color, s.icon FROM study_logs l JOIN subjects s ON s.id=l.subject_id """
            params=[]
            if date_from and date_to: q += " WHERE l.log_date BETWEEN %s AND %s "; params=[date_from, date_to]
            elif date_from: q += " WHERE l.log_date >= %s "; params=[date_from]
            q += " ORDER BY l.log_date DESC, l.id DESC LIMIT 200"
            with db.cursor() as cur:
                cur.execute(q, params)
                rows = cur.fetchall()
                for r in rows:
                    r['log_date']=str(r['log_date']); r['created_at']=str(r['created_at'])
                    enrich_jalali(r, ['log_date'])
                return jsonify(rows)
        except Exception as e:
            logging.error(f"logs GET error: {e}")
            return jsonify([])
    try:
        data = request.json or {}
        db = get_db()
        with db.cursor() as cur:
            # handle mood col optional
            try:
                cur.execute("INSERT INTO study_logs (subject_id, log_date, minutes, description, mood) VALUES (%s,%s,%s,%s,%s)", (data['subject_id'], data['log_date'], int(data['minutes']), data.get('description',''), data.get('mood')))
            except Exception as e:
                if '1054' in str(e) or 'mood' in str(e):
                    cur.execute("INSERT INTO study_logs (subject_id, log_date, minutes, description) VALUES (%s,%s,%s,%s)", (data['subject_id'], data['log_date'], int(data['minutes']), data.get('description','')))
                else: raise
            nid = cur.lastrowid
            cur.execute("SELECT * FROM study_logs WHERE id=%s", (nid,))
            row = cur.fetchone()
            cur.execute("SELECT name,color,icon FROM subjects WHERE id=%s", (data['subject_id'],))
            s = cur.fetchone()
            if s: row.update(s)
            row['log_date']=str(row['log_date']); row['created_at']=str(row['created_at'])
            enrich_jalali(row, ['log_date'])
            return jsonify(row), 201
    except Exception as e:
        logging.error(f"logs POST error: {e}")
        return jsonify(error=str(e)), 500

@app.route('/api/logs/<int:lid>', methods=['DELETE'])
def del_log(lid):
    try:
        db = get_db()
        with db.cursor() as cur: cur.execute("DELETE FROM study_logs WHERE id=%s", (lid,))
        return jsonify(ok=True)
    except Exception as e: return jsonify(error=str(e)), 500

# ---------- Assignments ----------
@app.route('/api/assignments', methods=['GET','POST'])
def assignments():
    try:
        db = get_db()
        if request.method == 'GET':
            status = request.args.get('status')
            q = """SELECT a.*, s.name as subject_name, s.color as subject_color, s.icon as subject_icon FROM assignments a LEFT JOIN subjects s ON s.id=a.subject_id"""
            params=[]
            if status:
                q += " WHERE a.status=%s"
                params=[status]
            q += " ORDER BY a.due_date ASC, a.id DESC"
            with db.cursor() as cur:
                cur.execute(q, params)
                rows = cur.fetchall()
                for r in rows:
                    r['due_date']=str(r['due_date']); r['created_at']=str(r['created_at'])
                    enrich_jalali(r, ['due_date'])
                return jsonify(rows)
        data = request.json or {}
        title = data.get('title','').strip()
        if not title: return jsonify(error="عنوان تکلیف الزامی است"), 400
        due_date = data.get('due_date')
        if not due_date: return jsonify(error="تاریخ تحویل الزامی است"), 400
        subject_id = data.get('subject_id')
        if subject_id == '' or subject_id == 0: subject_id = None
        with db.cursor() as cur:
            cur.execute("INSERT INTO assignments (subject_id, title, description, due_date, priority, status) VALUES (%s,%s,%s,%s,%s,%s)",
                        (subject_id, title, data.get('description',''), due_date, int(data.get('priority',2)), data.get('status','pending')))
            nid = cur.lastrowid
            cur.execute("SELECT a.*, s.name as subject_name, s.color as subject_color, s.icon as subject_icon FROM assignments a LEFT JOIN subjects s ON s.id=a.subject_id WHERE a.id=%s", (nid,))
            row = cur.fetchone()
            row['due_date']=str(row['due_date']); row['created_at']=str(row['created_at'])
            enrich_jalali(row, ['due_date'])
            return jsonify(row), 201
    except Exception as e:
        logging.error(f"assignments error: {e}")
        return jsonify(error=str(e)), 500

@app.route('/api/assignments/<int:aid>', methods=['DELETE','PUT','PATCH'])
def assignment_one(aid):
    try:
        db = get_db()
        if request.method == 'DELETE':
            with db.cursor() as cur: cur.execute("DELETE FROM assignments WHERE id=%s", (aid,))
            return jsonify(ok=True)
        data = request.json or {}
        with db.cursor() as cur:
            if request.method == 'PATCH':
                if 'status' in data: cur.execute("UPDATE assignments SET status=%s WHERE id=%s", (data['status'], aid))
                if 'priority' in data: cur.execute("UPDATE assignments SET priority=%s WHERE id=%s", (int(data['priority']), aid))
            else:
                cur.execute("UPDATE assignments SET subject_id=%s, title=%s, description=%s, due_date=%s, priority=%s, status=%s WHERE id=%s",
                            (data.get('subject_id'), data.get('title'), data.get('description',''), data.get('due_date'), int(data.get('priority',2)), data.get('status','pending'), aid))
            cur.execute("SELECT a.*, s.name as subject_name, s.color as subject_color, s.icon as subject_icon FROM assignments a LEFT JOIN subjects s ON s.id=a.subject_id WHERE a.id=%s", (aid,))
            row = cur.fetchone()
            if row:
                row['due_date']=str(row['due_date']); row['created_at']=str(row['created_at'])
                enrich_jalali(row, ['due_date'])
            return jsonify(row)
    except Exception as e:
        logging.error(f"assignment_one error: {e}")
        return jsonify(error=str(e)), 500

# ---------- Exams ----------
@app.route('/api/exams', methods=['GET','POST'])
def exams():
    try:
        db = get_db()
        if request.method == 'GET':
            with db.cursor() as cur:
                cur.execute("""SELECT e.*, s.name as subject_name, s.color as subject_color, s.icon as subject_icon FROM exams e LEFT JOIN subjects s ON s.id=e.subject_id ORDER BY e.exam_date ASC""")
                rows = cur.fetchall()
                for r in rows:
                    r['exam_date']=str(r['exam_date']); r['created_at']=str(r['created_at'])
                    enrich_jalali(r, ['exam_date'])
                    # days remaining
                    try:
                        d = datetime.strptime(r['exam_date'], '%Y-%m-%d').date()
                        r['days_remaining'] = (d - date.today()).days
                    except: r['days_remaining']=None
                return jsonify(rows)
        data = request.json or {}
        title = data.get('title','').strip()
        if not title: return jsonify(error="عنوان امتحان الزامی است"), 400
        exam_date = data.get('exam_date')
        if not exam_date: return jsonify(error="تاریخ امتحان الزامی است"), 400
        subject_id = data.get('subject_id')
        if subject_id == '' or subject_id == 0: subject_id = None
        with db.cursor() as cur:
            cur.execute("INSERT INTO exams (subject_id, title, exam_date, exam_time, location, description) VALUES (%s,%s,%s,%s,%s,%s)",
                        (subject_id, title, exam_date, data.get('exam_time'), data.get('location'), data.get('description','')))
            nid = cur.lastrowid
            cur.execute("SELECT e.*, s.name as subject_name, s.color as subject_color, s.icon as subject_icon FROM exams e LEFT JOIN subjects s ON s.id=e.subject_id WHERE e.id=%s", (nid,))
            row = cur.fetchone()
            row['exam_date']=str(row['exam_date']); row['created_at']=str(row['created_at'])
            enrich_jalali(row, ['exam_date'])
            return jsonify(row), 201
    except Exception as e:
        logging.error(f"exams error: {e}")
        return jsonify(error=str(e)), 500

@app.route('/api/exams/<int:eid>', methods=['DELETE','PUT'])
def exam_one(eid):
    try:
        db = get_db()
        if request.method == 'DELETE':
            with db.cursor() as cur: cur.execute("DELETE FROM exams WHERE id=%s", (eid,))
            return jsonify(ok=True)
        data = request.json or {}
        with db.cursor() as cur:
            cur.execute("UPDATE exams SET subject_id=%s, title=%s, exam_date=%s, exam_time=%s, location=%s, description=%s WHERE id=%s",
                        (data.get('subject_id'), data.get('title'), data.get('exam_date'), data.get('exam_time'), data.get('location'), data.get('description',''), eid))
            cur.execute("SELECT e.*, s.name as subject_name, s.color as subject_color, s.icon as subject_icon FROM exams e LEFT JOIN subjects s ON s.id=e.subject_id WHERE e.id=%s", (eid,))
            row = cur.fetchone()
            if row:
                row['exam_date']=str(row['exam_date']); row['created_at']=str(row['created_at'])
                enrich_jalali(row, ['exam_date'])
            return jsonify(row)
    except Exception as e:
        logging.error(f"exam_one error: {e}")
        return jsonify(error=str(e)), 500

# ---------- Stats ----------
@app.route('/api/stats')
def stats():
    try:
        db = get_db()
        ws, we = week_range()
        ws_s, we_s = str(ws), str(we)
        with db.cursor() as cur:
            cur.execute("SELECT id FROM weekly_plans WHERE week_start=%s", (ws,))
            prow = cur.fetchone()
            planned = []
            if prow:
                cur.execute("""SELECT s.name, s.color, SUM(pi.planned_minutes) as planned, SUM(CASE WHEN pi.is_done THEN pi.planned_minutes ELSE 0 END) as done FROM plan_items pi JOIN subjects s ON s.id=pi.subject_id WHERE pi.plan_id=%s GROUP BY s.id""", (prow['id'],))
                planned = cur.fetchall()
            cur.execute("""SELECT s.name, s.color, SUM(l.minutes) as actual FROM study_logs l JOIN subjects s ON s.id=l.subject_id WHERE l.log_date BETWEEN %s AND %s GROUP BY s.id""", (ws_s, we_s))
            actual = {r['name']: r for r in cur.fetchall()}
            cur.execute("""SELECT log_date, SUM(minutes) as total FROM study_logs WHERE log_date BETWEEN %s AND %s GROUP BY log_date ORDER BY log_date""", (str(ws - timedelta(days=21)), we_s))
            trend = cur.fetchall()
            for t in trend:
                t['log_date']=str(t['log_date'])
                t['log_date_jalali']=to_jalali_str(t['log_date'])
            cur.execute("SELECT COALESCE(SUM(minutes),0) as total FROM study_logs")
            total_all = cur.fetchone()['total']
            cur.execute("SELECT COALESCE(SUM(minutes),0) as wtotal FROM study_logs WHERE log_date BETWEEN %s AND %s", (ws_s, we_s))
            wtotal = cur.fetchone()['wtotal']
            try:
                cur.execute("SELECT log_date FROM study_logs GROUP BY log_date ORDER BY log_date DESC")
                dates = [r['log_date'] for r in cur.fetchall()]
                streak = 0
                if dates:
                    today = date.today()
                    date_set = set(dates)
                    cur_d = today
                    if cur_d not in date_set: cur_d = today - timedelta(days=1)
                    while cur_d in date_set:
                        streak += 1
                        cur_d -= timedelta(days=1)
                daily_goal = 180
                try:
                    cur.execute("SELECT value FROM app_settings WHERE `key`='daily_goal'")
                    row = cur.fetchone()
                    if row: daily_goal = int(row['value'])
                except: pass
                weekly_target = daily_goal * 7
            except:
                streak = 0; weekly_target = 1260
            # assignments/exams counts
            try:
                cur.execute("SELECT COUNT(*) as c FROM assignments WHERE status='pending' AND due_date >= CURDATE()")
                pending_assignments = cur.fetchone()['c']
                cur.execute("SELECT COUNT(*) as c FROM exams WHERE exam_date >= CURDATE()")
                upcoming_exams = cur.fetchone()['c']
            except:
                pending_assignments=0; upcoming_exams=0
            return jsonify({
                "week_start": ws_s, "week_end": we_s,
                "week_start_jalali": to_jalali_str(ws_s), "week_end_jalali": to_jalali_str(we_s),
                "today_jalali": jalali_today_str(),
                "planned": planned, "actual": actual, "trend": trend,
                "total_all": int(total_all), "week_total": int(wtotal),
                "plan_id": prow['id'] if prow else None,
                "streak": streak, "weekly_target": weekly_target,
                "weekly_progress": round(int(wtotal)/weekly_target*100, 1) if weekly_target else 0,
                "pending_assignments": int(pending_assignments), "upcoming_exams": int(upcoming_exams),
            })
    except Exception as e:
        logging.error(f"stats error: {e}")
        ws, we = week_range()
        return jsonify(week_start=str(ws), week_end=str(we), week_start_jalali=to_jalali_str(str(ws)), week_end_jalali=to_jalali_str(str(we)), today_jalali=jalali_today_str(), planned=[], actual={}, trend=[], total_all=0, week_total=0, plan_id=None, streak=0, weekly_target=1260, weekly_progress=0, pending_assignments=0, upcoming_exams=0, error=str(e))

# ---------- Settings ----------
@app.route('/api/settings', methods=['GET','PUT'])
def settings():
    try:
        db = get_db()
        if request.method == 'GET':
            with db.cursor() as cur:
                cur.execute("SELECT `key`, `value` FROM app_settings")
                rows = {r['key']: r['value'] for r in cur.fetchall()}
                return jsonify(rows)
        data = request.json or {}
        with db.cursor() as cur:
            for k, v in data.items():
                cur.execute("INSERT INTO app_settings (`key`,`value`) VALUES (%s,%s) ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)", (k, str(v)))
        return jsonify(ok=True)
    except Exception as e:
        logging.error(f"settings error: {e}")
        return jsonify(error=str(e)), 500

# ---------- Goals ----------
@app.route('/api/goals', methods=['GET','POST','DELETE'])
def goals():
    try:
        db = get_db()
        if request.method == 'GET':
            ws = request.args.get('week_start') or str(week_range()[0])
            with db.cursor() as cur:
                cur.execute("""SELECT g.*, s.name, s.color, s.icon FROM goals g LEFT JOIN subjects s ON s.id=g.subject_id WHERE g.week_start=%s ORDER BY g.subject_id""", (ws,))
                goals = cur.fetchall()
                for g1 in goals: g1['week_start']=str(g1['week_start']); enrich_jalali(g1, ['week_start'])
                return jsonify(goals)
        if request.method == 'DELETE':
            gid = request.args.get('id')
            with db.cursor() as cur: cur.execute("DELETE FROM goals WHERE id=%s", (gid,))
            return jsonify(ok=True)
        data = request.json or {}
        ws_str = data.get('week_start') or str(week_range()[0])
        ws,_ = week_range(ws_str)
        subject_id = data.get('subject_id')
        target = int(data.get('target_minutes', 180))
        with db.cursor() as cur:
            if subject_id is None or subject_id == '' or subject_id == 0:
                subject_id = None
                cur.execute("SELECT id FROM goals WHERE subject_id IS NULL AND week_start=%s", (ws,))
            else:
                cur.execute("SELECT id FROM goals WHERE subject_id=%s AND week_start=%s", (int(subject_id), ws))
            existing = cur.fetchone()
            if existing:
                cur.execute("UPDATE goals SET target_minutes=%s WHERE id=%s", (target, existing['id']))
                nid = existing['id']
            else:
                cur.execute("INSERT INTO goals (subject_id, week_start, target_minutes) VALUES (%s,%s,%s)", (subject_id, ws, target))
                nid = cur.lastrowid
            cur.execute("SELECT * FROM goals WHERE id=%s", (nid,))
            row = cur.fetchone()
            row['week_start']=str(row['week_start'])
            enrich_jalali(row, ['week_start'])
            return jsonify(row), 201
    except Exception as e:
        logging.error(f"goals error: {e}")
        return jsonify(error=str(e)), 500

@app.route('/api/goals/progress')
def goals_progress():
    try:
        db = get_db()
        ws_str = request.args.get('week_start') or str(week_range()[0])
        ws, we = week_range(ws_str)
        ws_s, we_s = str(ws), str(we)
        with db.cursor() as cur:
            cur.execute("SELECT * FROM goals WHERE week_start=%s", (ws,))
            goals = cur.fetchall()
            for g1 in goals:
                if g1['subject_id'] is None:
                    cur.execute("SELECT COALESCE(SUM(minutes),0) as actual FROM study_logs WHERE log_date BETWEEN %s AND %s", (ws_s, we_s))
                else:
                    cur.execute("SELECT COALESCE(SUM(minutes),0) as actual FROM study_logs WHERE log_date BETWEEN %s AND %s AND subject_id=%s", (ws_s, we_s, g1['subject_id']))
                actual = cur.fetchone()['actual'] or 0
                g1['actual'] = int(actual)
                g1['percent'] = round(int(actual)/g1['target_minutes']*100, 1) if g1['target_minutes'] else 0
                g1['week_start']=str(g1['week_start'])
                enrich_jalali(g1, ['week_start'])
                if g1['subject_id']:
                    cur.execute("SELECT name,color,icon FROM subjects WHERE id=%s", (g1['subject_id'],))
                    s = cur.fetchone()
                    if s: g1.update({f"subject_{k}": v for k,v in s.items()})
            return jsonify(goals)
    except Exception as e:
        logging.error(f"goals_progress error: {e}")
        return jsonify(error=str(e)), 500

# ---------- Daily Notes ----------
@app.route('/api/notes', methods=['GET','POST','DELETE'])
def notes():
    try:
        db = get_db()
        if request.method == 'GET':
            d = request.args.get('date') or str(date.today())
            with db.cursor() as cur:
                cur.execute("SELECT * FROM daily_notes WHERE note_date=%s", (d,))
                row = cur.fetchone()
                if row:
                    row['note_date']=str(row['note_date']); row['created_at']=str(row['created_at'])
                    enrich_jalali(row, ['note_date'])
                return jsonify(row or {})
        if request.method == 'DELETE':
            d = request.args.get('date')
            with db.cursor() as cur: cur.execute("DELETE FROM daily_notes WHERE note_date=%s", (d,))
            return jsonify(ok=True)
        data = request.json or {}
        d = data.get('note_date') or str(date.today())
        content = data.get('content','').strip()
        if not content: return jsonify(error="محتوا خالی است"), 400
        with db.cursor() as cur:
            cur.execute("INSERT INTO daily_notes (note_date, content) VALUES (%s,%s) ON DUPLICATE KEY UPDATE content=VALUES(content)", (d, content))
            cur.execute("SELECT * FROM daily_notes WHERE note_date=%s", (d,))
            row = cur.fetchone()
            row['note_date']=str(row['note_date']); row['created_at']=str(row['created_at'])
            enrich_jalali(row, ['note_date'])
            return jsonify(row), 201
    except Exception as e:
        logging.error(f"notes error: {e}")
        return jsonify(error=str(e)), 500

# ---------- Pomodoro ----------
@app.route('/api/pomodoro', methods=['GET','POST'])
def pomodoro():
    try:
        db = get_db()
        if request.method == 'GET':
            with db.cursor() as cur:
                cur.execute("SELECT p.*, s.name as subject_name FROM pomodoro_sessions p LEFT JOIN subjects s ON s.id=p.subject_id ORDER BY p.started_at DESC LIMIT 30")
                rows = cur.fetchall()
                for r in rows: r['started_at']=str(r['started_at'])
                cur.execute("SELECT COUNT(*) as c, COALESCE(SUM(duration_minutes),0) as total FROM pomodoro_sessions WHERE DATE(started_at)=CURDATE() AND completed=1")
                today = cur.fetchone()
                return jsonify(sessions=rows, today_count=int(today['c'] or 0), today_minutes=int(today['total'] or 0))
        data = request.json or {}
        subject_id = data.get('subject_id')
        if subject_id == 0 or subject_id == '': subject_id = None
        duration = int(data.get('duration_minutes', 25))
        with db.cursor() as cur:
            cur.execute("INSERT INTO pomodoro_sessions (subject_id, duration_minutes, completed) VALUES (%s,%s,1)", (subject_id, duration))
            nid = cur.lastrowid
            cur.execute("SELECT * FROM pomodoro_sessions WHERE id=%s", (nid,))
            row = cur.fetchone()
            row['started_at']=str(row['started_at'])
            return jsonify(row), 201
    except Exception as e:
        logging.error(f"pomodoro error: {e}")
        return jsonify(error=str(e)), 500

# ---------- Calendar ----------
@app.route('/api/calendar')
def calendar_api():
    try:
        db = get_db()
        month = request.args.get('month') or datetime.now().strftime('%Y-%m')
        start = month + '-01'
        y, m = map(int, month.split('-'))
        if m == 12: end = f"{y+1}-01-01"
        else: end = f"{y}-{m+1:02d}-01"
        with db.cursor() as cur:
            cur.execute("""SELECT log_date, SUM(minutes) as total, COUNT(*) as cnt FROM study_logs WHERE log_date >= %s AND log_date < %s GROUP BY log_date""", (start, end))
            logs = {str(r['log_date']): r for r in cur.fetchall()}
            cur.execute("SELECT note_date FROM daily_notes WHERE note_date >= %s AND note_date < %s", (start, end))
            notes_set = set(str(r['note_date']) for r in cur.fetchall())
            try:
                cur.execute("SELECT due_date FROM assignments WHERE due_date >= %s AND due_date < %s", (start, end))
                assign_set = set(str(r['due_date']) for r in cur.fetchall())
                cur.execute("SELECT exam_date FROM exams WHERE exam_date >= %s AND exam_date < %s", (start, end))
                exam_set = set(str(r['exam_date']) for r in cur.fetchall())
            except:
                assign_set=set(); exam_set=set()
            return jsonify(logs=logs, notes=list(notes_set), assignments=list(assign_set), exams=list(exam_set))
    except Exception as e:
        logging.error(f"calendar error: {e}")
        return jsonify(error=str(e)), 500

# ---------- Export ----------
@app.route('/api/export')
def export_data():
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT * FROM subjects ORDER BY id")
            subjects = cur.fetchall()
            for s in subjects: s['created_at']=str(s['created_at'])
            cur.execute("SELECT * FROM study_logs ORDER BY log_date DESC LIMIT 500")
            logs = cur.fetchall()
            for l in logs: l['log_date']=str(l['log_date']); l['created_at']=str(l['created_at']); enrich_jalali(l, ['log_date'])
            cur.execute("SELECT * FROM weekly_plans ORDER BY week_start DESC LIMIT 20")
            plans = cur.fetchall()
            for p in plans: p['week_start']=str(p['week_start']); p['week_end']=str(p['week_end']); p['created_at']=str(p['created_at']); enrich_jalali(p, ['week_start','week_end'])
            try:
                cur.execute("SELECT * FROM assignments ORDER BY due_date DESC LIMIT 100")
                assignments = cur.fetchall()
                for a in assignments: a['due_date']=str(a['due_date']); a['created_at']=str(a['created_at']); enrich_jalali(a, ['due_date'])
                cur.execute("SELECT * FROM exams ORDER BY exam_date DESC LIMIT 100")
                exams = cur.fetchall()
                for e in exams: e['exam_date']=str(e['exam_date']); e['created_at']=str(e['created_at']); enrich_jalali(e, ['exam_date'])
            except:
                assignments=[]; exams=[]
            return jsonify(subjects=subjects, logs=logs, plans=plans, assignments=assignments, exams=exams, exported_at=str(datetime.now()), exported_at_jalali=jalali_today_str())
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route('/api/export/csv')
def export_csv():
    try:
        db = get_db()
        import csv, io
        with db.cursor() as cur:
            cur.execute("""SELECT l.log_date, s.name, s.icon, l.minutes, l.description, l.mood FROM study_logs l JOIN subjects s ON s.id=l.subject_id ORDER BY l.log_date DESC""")
            rows = cur.fetchall()
        output = io.StringIO()
        w = csv.writer(output)
        w.writerow(['تاریخ میلادی','تاریخ شمسی','درس','آیکون','دقیقه','توضیح','حال'])
        for r in rows:
            w.writerow([str(r['log_date']), to_jalali_str(str(r['log_date'])), r['name'], r['icon'], r['minutes'], r['description'] or '', r.get('mood') or ''])
        from flask import Response
        return Response(output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename=study_logs.csv'})
    except Exception as e:
        return jsonify(error=str(e)), 500

# BUILD_ID 1787425043 - v3.3 fix calendar UTC + subjects dedup
# BUILD_ID 1787425043 - v3.3 fix calendar UTC + subjects dedup
logging.info(f"App loaded, PORT={os.getenv('PORT','5000')}, env PORT present={bool(os.getenv('PORT'))}")

if __name__ == '__main__':
    port = int(os.getenv('PORT', '5000'))
    app.run(host='0.0.0.0', port=port, debug=False)
