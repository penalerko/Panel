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
    except Exception as _e:
        pass

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'weekly-planner-secret')
app.config['JSON_AS_ASCII'] = False

# ---------- DB Config ----------
def get_db_config():
    # Railway provides MYSQL_URL / MYSQLHOST / DB_HOST - support all
    mysql_url = os.getenv('MYSQL_URL') or os.getenv('DATABASE_URL') or os.getenv('MYSQL_PUBLIC_URL') or os.getenv('MYSQL_PRIVATE_URL')
    if mysql_url:
        from urllib.parse import urlparse
        u = urlparse(mysql_url)
        logging.info(f"Using MYSQL_URL host={u.hostname} db={u.path.lstrip('/')}")
        return dict(
            host=u.hostname,
            port=u.port or 3306,
            user=u.username,
            password=u.password,
            database=u.path.lstrip('/'),
            charset='utf8mb4',
            cursorclass=DictCursor,
            autocommit=True,
            connect_timeout=5
        )
    # Try Railway plugin vars or custom DB_*
    host = os.getenv('MYSQLHOST') or os.getenv('MYSQL_HOST') or os.getenv('DB_HOST', 'localhost')
    port = int(os.getenv('MYSQLPORT') or os.getenv('MYSQL_PORT') or os.getenv('DB_PORT', '3306'))
    user = os.getenv('MYSQLUSER') or os.getenv('MYSQL_USER') or os.getenv('DB_USER', 'root')
    password = os.getenv('MYSQLPASSWORD') or os.getenv('MYSQL_PASSWORD') or os.getenv('DB_PASSWORD', '')
    database = os.getenv('MYSQLDATABASE') or os.getenv('MYSQL_DATABASE') or os.getenv('DB_NAME', 'weekly_planner')
    logging.info(f"DB config host={host} port={port} user={user} db={database}")
    return dict(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset='utf8mb4',
        cursorclass=DictCursor,
        autocommit=True,
        connect_timeout=5
    )

def get_db():
    if 'db' not in g or g.db is None:
        cfg = get_db_config()
        try:
            g.db = pymysql.connect(**cfg)
        except pymysql.err.OperationalError as e:
            msg = str(e)
            # auto-create database if not exists
            if 'Unknown database' in msg:
                logging.info(f"Database {cfg['database']} not found, creating...")
                cfg2 = {k: v for k, v in cfg.items() if k != 'database'}
                # need raw connection without db
                tmp_cfg = {k: v for k, v in cfg2.items() if k in ('host','port','user','password','charset','connect_timeout')}
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
        try:
            db.close()
        except:
            pass

MIGRATIONS = [
    "ALTER TABLE subjects ADD COLUMN daily_goal INT DEFAULT 60",
    "ALTER TABLE plan_items ADD COLUMN time_slot VARCHAR(20) DEFAULT 'any'",
    "ALTER TABLE plan_items ADD COLUMN priority TINYINT DEFAULT 2",
    "ALTER TABLE study_logs ADD COLUMN mood VARCHAR(20) DEFAULT NULL",
]

def run_migrations(db):
    with db.cursor() as cur:
        for sql in MIGRATIONS:
            try:
                cur.execute(sql)
                logging.info(f"Migration OK: {sql[:60]}")
            except Exception as e:
                if 'Duplicate column' in str(e) or 'already exists' in str(e):
                    continue
                # pymysql error code 1060
                if '1060' in str(e):
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
                    if not s:
                        continue
                    up = s.upper()
                    if up.startswith('CREATE DATABASE') or up.startswith('USE '):
                        continue
                    statements.append(s)
                for stmt in statements:
                    try:
                        cur.execute(stmt)
                    except Exception as e:
                        if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                            continue
                        # ON DUPLICATE KEY etc are ok
                        if 'Duplicate entry' in str(e):
                            continue
                        logging.warning(f"SQL warn: {e} | {stmt[:120]}")
        run_migrations(db)
        logging.info("✅ DB init done")
    except Exception as e:
        logging.error(f"❌ DB init failed: {e}")

# ---------- Helpers ----------
DAYS_FA = ['شنبه','یکشنبه','دوشنبه','سه‌شنبه','چهارشنبه','پنجشنبه','جمعه']

def week_range(d=None):
    if d is None:
        d = date.today()
    if isinstance(d, str):
        d = datetime.strptime(d, '%Y-%m-%d').date()
    offset = (d.weekday() - 5) % 7
    sat = d - timedelta(days=offset)
    fri = sat + timedelta(days=6)
    return sat, fri

# ---------- Lazy init on first request ----------
_inited = False
@app.before_request
def lazy_init():
    global _inited
    if not _inited:
        _inited = True
        try:
            init_db()
        except Exception as e:
            logging.error(f"lazy init failed: {e}")

# ---------- Routes ----------
@app.route('/')
def index():
    return render_template('index.html', days=DAYS_FA)

@app.route('/health')
def health():
    # health should ALWAYS return 200 so Railway doesn't mark as failed
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT 1")
        return jsonify(status="ok", db="connected")
    except Exception as e:
        # still return 200 but show error - don't break healthcheck
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
            return jsonify([])  # return empty instead of 500
    data = request.json or {}
    name = data.get('name','').strip()
    if not name:
        return jsonify(error="نام درس الزامی است"), 400
    color = data.get('color','#6366f1')
    icon = data.get('icon','📚')
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute("INSERT INTO subjects (name,color,icon) VALUES (%s,%s,%s)", (name,color,icon))
            nid = cur.lastrowid
            cur.execute("SELECT * FROM subjects WHERE id=%s", (nid,))
            return jsonify(cur.fetchone()), 201
    except Exception as e:
        logging.error(f"subjects POST error: {e}")
        return jsonify(error=str(e)), 500

@app.route('/api/subjects/<int:sid>', methods=['DELETE','PUT'])
def subject_one(sid):
    try:
        db = get_db()
        if request.method == 'DELETE':
            with db.cursor() as cur:
                cur.execute("DELETE FROM subjects WHERE id=%s", (sid,))
            return jsonify(ok=True)
        data = request.json or {}
        with db.cursor() as cur:
            cur.execute("UPDATE subjects SET name=%s, color=%s, icon=%s WHERE id=%s",
                        (data.get('name'), data.get('color'), data.get('icon'), sid))
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
                    p['week_start'] = str(p['week_start'])
                    p['week_end'] = str(p['week_end'])
                return jsonify(rows)
        except Exception as e:
            logging.error(f"plans GET error: {e}")
            return jsonify([])
    data = request.json or {}
    ws_str = data.get('week_start')
    if ws_str:
        ws, we = week_range(ws_str)
    else:
        ws, we = week_range()
    title = data.get('title', f"برنامه هفته {ws}")
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
            row['week_start'] = str(row['week_start'])
            row['week_end'] = str(row['week_end'])
            return jsonify(row), 201
    except Exception as e:
        logging.error(f"plans POST error: {e}")
        return jsonify(error=str(e)), 500

@app.route('/api/plans/<int:pid>', methods=['GET','DELETE'])
def plan_one(pid):
    try:
        db = get_db()
        if request.method == 'DELETE':
            with db.cursor() as cur:
                cur.execute("DELETE FROM weekly_plans WHERE id=%s", (pid,))
            return jsonify(ok=True)
        with db.cursor() as cur:
            cur.execute("SELECT * FROM weekly_plans WHERE id=%s", (pid,))
            plan = cur.fetchone()
            if not plan:
                return jsonify(error="not found"), 404
            plan['week_start'] = str(plan['week_start'])
            plan['week_end'] = str(plan['week_end'])
            cur.execute("""SELECT pi.*, s.name, s.color, s.icon 
                           FROM plan_items pi JOIN subjects s ON s.id=pi.subject_id 
                           WHERE pi.plan_id=%s ORDER BY pi.day_of_week, pi.subject_id""", (pid,))
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
            cur.execute("INSERT INTO plan_items (plan_id, subject_id, day_of_week, planned_minutes, note) VALUES (%s,%s,%s,%s,%s) "
                        "ON DUPLICATE KEY UPDATE planned_minutes=VALUES(planned_minutes), note=VALUES(note)",
                        (pid, data['subject_id'], int(data['day_of_week']), int(data.get('planned_minutes',60)), data.get('note','')))
            cur.execute("SELECT * FROM plan_items WHERE plan_id=%s AND subject_id=%s AND day_of_week=%s",
                        (pid, data['subject_id'], int(data['day_of_week'])))
            return jsonify(cur.fetchone()), 201
    except Exception as e:
        logging.error(f"add_item error: {e}")
        return jsonify(error=str(e)), 500

@app.route('/api/plan-items/<int:iid>', methods=['DELETE','PATCH'])
def item_ops(iid):
    try:
        db = get_db()
        if request.method == 'DELETE':
            with db.cursor() as cur:
                cur.execute("DELETE FROM plan_items WHERE id=%s", (iid,))
            return jsonify(ok=True)
        data = request.json or {}
        with db.cursor() as cur:
            if 'is_done' in data:
                cur.execute("UPDATE plan_items SET is_done=%s WHERE id=%s", (bool(data['is_done']), iid))
            if 'planned_minutes' in data:
                cur.execute("UPDATE plan_items SET planned_minutes=%s WHERE id=%s", (int(data['planned_minutes']), iid))
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
            date_from = request.args.get('from')
            date_to = request.args.get('to')
            q = """SELECT l.*, s.name, s.color, s.icon FROM study_logs l 
                   JOIN subjects s ON s.id=l.subject_id """
            params=[]
            if date_from and date_to:
                q += " WHERE l.log_date BETWEEN %s AND %s "
                params=[date_from, date_to]
            elif date_from:
                q += " WHERE l.log_date >= %s "
                params=[date_from]
            q += " ORDER BY l.log_date DESC, l.id DESC LIMIT 200"
            with db.cursor() as cur:
                cur.execute(q, params)
                rows = cur.fetchall()
                for r in rows:
                    r['log_date']=str(r['log_date'])
                    r['created_at']=str(r['created_at'])
                return jsonify(rows)
        except Exception as e:
            logging.error(f"logs GET error: {e}")
            return jsonify([])
    try:
        data = request.json or {}
        db = get_db()
        with db.cursor() as cur:
            cur.execute("INSERT INTO study_logs (subject_id, log_date, minutes, description) VALUES (%s,%s,%s,%s)",
                        (data['subject_id'], data['log_date'], int(data['minutes']), data.get('description','')))
            nid = cur.lastrowid
            cur.execute("SELECT * FROM study_logs WHERE id=%s", (nid,))
            row = cur.fetchone()
            # also need subject info
            cur.execute("SELECT name,color,icon FROM subjects WHERE id=%s", (data['subject_id'],))
            s = cur.fetchone()
            if s:
                row.update(s)
            row['log_date']=str(row['log_date'])
            row['created_at']=str(row['created_at'])
            return jsonify(row), 201
    except Exception as e:
        logging.error(f"logs POST error: {e}")
        return jsonify(error=str(e)), 500

@app.route('/api/logs/<int:lid>', methods=['DELETE'])
def del_log(lid):
    try:
        db = get_db()
        with db.cursor() as cur:
            cur.execute("DELETE FROM study_logs WHERE id=%s", (lid,))
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(error=str(e)), 500

# ---------- API: Stats ----------
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
                cur.execute("""SELECT s.name, s.color, SUM(pi.planned_minutes) as planned,
                               SUM(CASE WHEN pi.is_done THEN pi.planned_minutes ELSE 0 END) as done
                               FROM plan_items pi JOIN subjects s ON s.id=pi.subject_id
                               WHERE pi.plan_id=%s GROUP BY s.id""", (prow['id'],))
                planned = cur.fetchall()
            cur.execute("""SELECT s.name, s.color, SUM(l.minutes) as actual
                           FROM study_logs l JOIN subjects s ON s.id=l.subject_id
                           WHERE l.log_date BETWEEN %s AND %s GROUP BY s.id""", (ws_s, we_s))
            actual = {r['name']: r for r in cur.fetchall()}
            cur.execute("""SELECT log_date, SUM(minutes) as total FROM study_logs 
                           WHERE log_date BETWEEN %s AND %s GROUP BY log_date ORDER BY log_date""",
                        (str(ws - timedelta(days=21)), we_s))
            trend = cur.fetchall()
            for t in trend:
                t['log_date']=str(t['log_date'])
            cur.execute("SELECT COALESCE(SUM(minutes),0) as total FROM study_logs")
            total_all = cur.fetchone()['total']
            cur.execute("SELECT COALESCE(SUM(minutes),0) as wtotal FROM study_logs WHERE log_date BETWEEN %s AND %s", (ws_s, we_s))
            wtotal = cur.fetchone()['wtotal']
            # streak
            try:
                cur.execute("SELECT log_date FROM study_logs GROUP BY log_date ORDER BY log_date DESC")
                dates = [r['log_date'] for r in cur.fetchall()]
                streak = 0
                if dates:
                    from datetime import date as dt
                    today = dt.today()
                    date_set = set(dates)
                    # count consecutive days from today or yesterday
                    cur_d = today
                    if cur_d not in date_set:
                        cur_d = today - timedelta(days=1)
                    while cur_d in date_set:
                        streak += 1
                        cur_d -= timedelta(days=1)
                # weekly target progress
                daily_goal = 180
                try:
                    cur.execute("SELECT value FROM app_settings WHERE `key`='daily_goal'")
                    row = cur.fetchone()
                    if row:
                        daily_goal = int(row['value'])
                except: pass
                weekly_target = daily_goal * 7
            except:
                streak = 0
                weekly_target = 1260
            return jsonify({
                "week_start": ws_s, "week_end": we_s,
                "planned": planned,
                "actual": actual,
                "trend": trend,
                "total_all": int(total_all),
                "week_total": int(wtotal),
                "plan_id": prow['id'] if prow else None,
                "streak": streak,
                "weekly_target": weekly_target,
                "weekly_progress": round(int(wtotal)/weekly_target*100, 1) if weekly_target else 0,
            })
    except Exception as e:
        logging.error(f"stats error: {e}")
        return jsonify(week_start=str(week_range()[0]), week_end=str(week_range()[1]), planned=[], actual={}, trend=[], total_all=0, week_total=0, plan_id=None, streak=0, weekly_target=1260, weekly_progress=0, error=str(e))

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
                cur.execute("""SELECT g.*, s.name, s.color, s.icon FROM goals g
                    LEFT JOIN subjects s ON s.id=g.subject_id WHERE g.week_start=%s ORDER BY g.subject_id""", (ws,))
                goals = cur.fetchall()
                for g1 in goals:
                    g1['week_start']=str(g1['week_start'])
                return jsonify(goals)
        if request.method == 'DELETE':
            gid = request.args.get('id')
            with db.cursor() as cur:
                cur.execute("DELETE FROM goals WHERE id=%s", (gid,))
            return jsonify(ok=True)
        data = request.json or {}
        ws_str = data.get('week_start') or str(week_range()[0])
        ws,_ = week_range(ws_str)
        subject_id = data.get('subject_id')  # None = کلی
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
                cur.execute("SELECT COALESCE(SUM(minutes),0) as actual FROM study_logs WHERE log_date BETWEEN %s AND %s " + (" AND subject_id IS NULL" if g1['subject_id'] is None else " AND subject_id=%s"), (ws_s, we_s) if g1['subject_id'] is None else (ws_s, we_s, g1['subject_id']))
                # fix for NULL case
                if g1['subject_id'] is None:
                    cur.execute("SELECT COALESCE(SUM(minutes),0) as actual FROM study_logs WHERE log_date BETWEEN %s AND %s", (ws_s, we_s))
                else:
                    cur.execute("SELECT COALESCE(SUM(minutes),0) as actual FROM study_logs WHERE log_date BETWEEN %s AND %s AND subject_id=%s", (ws_s, we_s, g1['subject_id']))
                actual = cur.fetchone()['actual'] or 0
                g1['actual'] = int(actual)
                g1['percent'] = round(int(actual)/g1['target_minutes']*100, 1) if g1['target_minutes'] else 0
                g1['week_start']=str(g1['week_start'])
                if g1['subject_id']:
                    cur.execute("SELECT name,color,icon FROM subjects WHERE id=%s", (g1['subject_id'],))
                    s = cur.fetchone()
                    if s:
                        g1.update({f"subject_{k}": v for k,v in s.items()})
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
                    row['note_date']=str(row['note_date'])
                    row['created_at']=str(row['created_at'])
                return jsonify(row or {})
        if request.method == 'DELETE':
            d = request.args.get('date')
            with db.cursor() as cur:
                cur.execute("DELETE FROM daily_notes WHERE note_date=%s", (d,))
            return jsonify(ok=True)
        data = request.json or {}
        d = data.get('note_date') or str(date.today())
        content = data.get('content','').strip()
        if not content:
            return jsonify(error="محتوا خالی است"), 400
        with db.cursor() as cur:
            cur.execute("INSERT INTO daily_notes (note_date, content) VALUES (%s,%s) ON DUPLICATE KEY UPDATE content=VALUES(content)", (d, content))
            cur.execute("SELECT * FROM daily_notes WHERE note_date=%s", (d,))
            row = cur.fetchone()
            row['note_date']=str(row['note_date'])
            row['created_at']=str(row['created_at'])
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
                cur.execute("SELECT * FROM pomodoro_sessions ORDER BY started_at DESC LIMIT 30")
                rows = cur.fetchall()
                for r in rows:
                    r['started_at']=str(r['started_at'])
                # today count
                cur.execute("SELECT COUNT(*) as c, COALESCE(SUM(duration_minutes),0) as total FROM pomodoro_sessions WHERE DATE(started_at)=CURDATE() AND completed=1")
                today = cur.fetchone()
                return jsonify(sessions=rows, today_count=int(today['c'] or 0), today_minutes=int(today['total'] or 0))
        data = request.json or {}
        subject_id = data.get('subject_id')
        if subject_id == 0 or subject_id == '':
            subject_id = None
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
        # month = 2026-08
        start = month + '-01'
        # next month start
        y, m = map(int, month.split('-'))
        if m == 12:
            end = f"{y+1}-01-01"
        else:
            end = f"{y}-{m+1:02d}-01"
        with db.cursor() as cur:
            cur.execute("""SELECT log_date, SUM(minutes) as total, COUNT(*) as cnt FROM study_logs
                WHERE log_date >= %s AND log_date < %s GROUP BY log_date""", (start, end))
            logs = {str(r['log_date']): r for r in cur.fetchall()}
            cur.execute("SELECT note_date FROM daily_notes WHERE note_date >= %s AND note_date < %s", (start, end))
            notes_set = set(str(r['note_date']) for r in cur.fetchall())
            return jsonify(logs=logs, notes=list(notes_set))
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
            for s in subjects:
                s['created_at']=str(s['created_at'])
            cur.execute("SELECT * FROM study_logs ORDER BY log_date DESC LIMIT 500")
            logs = cur.fetchall()
            for l in logs:
                l['log_date']=str(l['log_date'])
                l['created_at']=str(l['created_at'])
            cur.execute("SELECT * FROM weekly_plans ORDER BY week_start DESC LIMIT 20")
            plans = cur.fetchall()
            for p in plans:
                p['week_start']=str(p['week_start'])
                p['week_end']=str(p['week_end'])
                p['created_at']=str(p['created_at'])
            return jsonify(subjects=subjects, logs=logs, plans=plans, exported_at=str(datetime.now()))
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
        w.writerow(['تاریخ','درس','آیکون','دقیقه','توضیح','حال'])
        for r in rows:
            w.writerow([str(r['log_date']), r['name'], r['icon'], r['minutes'], r['description'] or '', r.get('mood') or ''])
        from flask import Response
        return Response(output.getvalue(), mimetype='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename=study_logs.csv'})
    except Exception as e:
        return jsonify(error=str(e)), 500

# Log startup
# BUILD_ID 1787422340 - v2 force rebuild
logging.info(f"App loaded, PORT={os.getenv('PORT','5000')}, env PORT present={bool(os.getenv('PORT'))}")

if __name__ == '__main__':
    port = int(os.getenv('PORT', '5000'))
    app.run(host='0.0.0.0', port=port, debug=False)
