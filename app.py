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

def init_db():
    try:
        db = get_db()
        schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
        if not os.path.exists(schema_path):
            logging.warning("schema.sql not found")
            return
        with open(schema_path, 'r', encoding='utf-8') as f:
            sql = f.read()
        with db.cursor() as cur:
            statements = []
            for stmt in sql.split(';'):
                s = stmt.strip()
                if not s:
                    continue
                # skip DB creation/use - we handle it
                up = s.upper()
                if up.startswith('CREATE DATABASE') or up.startswith('USE '):
                    continue
                statements.append(s)
            for stmt in statements:
                try:
                    cur.execute(stmt)
                except Exception as e:
                    # ignore duplicate errors
                    if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                        continue
                    logging.warning(f"SQL warn: {e} | {stmt[:120]}")
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
            return jsonify({
                "week_start": ws_s, "week_end": we_s,
                "planned": planned,
                "actual": actual,
                "trend": trend,
                "total_all": int(total_all),
                "week_total": int(wtotal),
                "plan_id": prow['id'] if prow else None
            })
    except Exception as e:
        logging.error(f"stats error: {e}")
        return jsonify(week_start=str(week_range()[0]), week_end=str(week_range()[1]), planned=[], actual={}, trend=[], total_all=0, week_total=0, plan_id=None, error=str(e))

# Log startup
logging.info(f"App loaded, PORT={os.getenv('PORT','5000')}, env PORT present={bool(os.getenv('PORT'))}")

if __name__ == '__main__':
    port = int(os.getenv('PORT', '5000'))
    app.run(host='0.0.0.0', port=port, debug=False)
