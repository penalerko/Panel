# پلنر هفتگی مطالعه - Railway Ready

## نصب لوکال
```bash
pip install -r requirements.txt
# .env را از .env.example بساز و پر کن
python app.py
```

## دیپلوی روی Railway

### روش ۱: از طریق GitHub
1. این پوشه را به یک ریپوی GitHub پوش کن
2. در Railway: New Project -> Deploy from GitHub
3. سرویس MySQL اضافه کن: New -> Database -> MySQL
4. متغیرهای محیطی به صورت خودکار وصل می‌شوند (MYSQLHOST, MYSQLUSER, ...)

### روش ۲: با Railway CLI + توکن
```bash
npm i -g @railway/cli
railway login --token a1a2b0f7-54d3-4da3-8e1c-5366c598470e
railway init
railway add --database mysql
railway up
```

### نکات Railway
- `app.py` به صورت خودکار از `MYSQL_URL` / `MYSQLHOST` / `DB_HOST` می‌خواند
- `schema.sql` در استارتاپ اجرا می‌شود (جداول خودکار ساخته می‌شوند)
- `PORT` را Railway ست می‌کند، نیازی به تنظیم دستی نیست
- `Procfile` برای gunicorn آماده است

## ENV های پشتیبانی شده
- `MYSQL_URL` / `DATABASE_URL` (اولویت اول)
- `MYSQLHOST`, `MYSQLPORT`, `MYSQLUSER`, `MYSQLPASSWORD`, `MYSQLDATABASE`
- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
- `PORT`, `SECRET_KEY`

## API
- `GET /health` - چک دیتابیس
- `GET/POST /api/subjects`
- `GET/POST /api/plans` و `GET /api/plans/<id>`
- `POST /api/plans/<id>/items` و `PATCH/DELETE /api/plan-items/<id>`
- `GET/POST /api/logs` و `DELETE /api/logs/<id>`
- `GET /api/stats`
