-- پلنر هفتگی مطالعه - MySQL Schema
-- برای Railway: این فایل به صورت خودکار توسط app.py اجرا می‌شود
-- برای اجرای دستی: mysql -u root -p < schema.sql

CREATE DATABASE IF NOT EXISTS weekly_planner CHARACTER SET utf8mb4 COLLATE utf8mb4_persian_ci;
USE weekly_planner;

-- دروس / موضوعات
CREATE TABLE IF NOT EXISTS subjects (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    color VARCHAR(7) DEFAULT '#6366f1',
    icon VARCHAR(20) DEFAULT '📚',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- برنامه هفتگی
CREATE TABLE IF NOT EXISTS weekly_plans (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(150) NOT NULL DEFAULT 'برنامه هفته',
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_week (week_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- آیتم‌های برنامه (هر روز + هر درس)
CREATE TABLE IF NOT EXISTS plan_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    plan_id INT NOT NULL,
    subject_id INT NOT NULL,
    day_of_week TINYINT NOT NULL COMMENT '0=شنبه ... 6=جمعه',
    planned_minutes INT NOT NULL DEFAULT 60,
    note VARCHAR(255) DEFAULT NULL,
    is_done BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (plan_id) REFERENCES weekly_plans(id) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    UNIQUE KEY unique_plan_subject_day (plan_id, subject_id, day_of_week)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- لاگ مطالعه روزانه
CREATE TABLE IF NOT EXISTS study_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    subject_id INT NOT NULL,
    log_date DATE NOT NULL,
    minutes INT NOT NULL,
    description VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    INDEX idx_date (log_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- داده نمونه
INSERT INTO subjects (name, color, icon) VALUES
('ریاضی', '#ef4444', '🔢'),
('فیزیک', '#3b82f6', '⚛️'),
('شیمی', '#10b981', '🧪'),
('زبان انگلیسی', '#f59e0b', '🔤'),
('برنامه‌نویسی', '#8b5cf6', '💻')
ON DUPLICATE KEY UPDATE name=name;
