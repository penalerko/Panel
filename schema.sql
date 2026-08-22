-- پلنر هفتگی مطالعه v3 - MySQL Schema
CREATE DATABASE IF NOT EXISTS weekly_planner CHARACTER SET utf8mb4 COLLATE utf8mb4_persian_ci;
USE weekly_planner;

-- دروس
CREATE TABLE IF NOT EXISTS subjects (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    color VARCHAR(7) DEFAULT '#6366f1',
    icon VARCHAR(20) DEFAULT '📚',
    daily_goal INT DEFAULT 60 COMMENT 'هدف روزانه دقیقه',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- برنامه هفتگی
CREATE TABLE IF NOT EXISTS weekly_plans (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(150) NOT NULL DEFAULT 'برنامه هفته',
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    template_name VARCHAR(100) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_week (week_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- آیتم‌های برنامه
CREATE TABLE IF NOT EXISTS plan_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    plan_id INT NOT NULL,
    subject_id INT NOT NULL,
    day_of_week TINYINT NOT NULL COMMENT '0=شنبه ... 6=جمعه',
    planned_minutes INT NOT NULL DEFAULT 60,
    time_slot VARCHAR(20) DEFAULT 'any' COMMENT 'morning/afternoon/evening/any',
    priority TINYINT DEFAULT 2 COMMENT '1=کم 2=متوسط 3=زیاد',
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
    mood VARCHAR(20) DEFAULT NULL COMMENT 'great/good/ok/tired',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    INDEX idx_date (log_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- اهداف هفتگی
CREATE TABLE IF NOT EXISTS goals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    subject_id INT NULL COMMENT 'NULL = هدف کلی',
    week_start DATE NOT NULL,
    target_minutes INT NOT NULL DEFAULT 300,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
    UNIQUE KEY unique_goal (subject_id, week_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- یادداشت روزانه
CREATE TABLE IF NOT EXISTS daily_notes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    note_date DATE NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_note_date (note_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- جلسات پومودورو
CREATE TABLE IF NOT EXISTS pomodoro_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    subject_id INT NULL,
    duration_minutes INT NOT NULL DEFAULT 25,
    completed BOOLEAN DEFAULT TRUE,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE SET NULL,
    INDEX idx_started (started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- تکالیف
CREATE TABLE IF NOT EXISTS assignments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    subject_id INT NULL,
    title VARCHAR(200) NOT NULL,
    description TEXT DEFAULT NULL,
    due_date DATE NOT NULL,
    priority TINYINT DEFAULT 2 COMMENT '1=کم 2=متوسط 3=زیاد',
    status VARCHAR(20) DEFAULT 'pending' COMMENT 'pending/done',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE SET NULL,
    INDEX idx_due (due_date),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- امتحان‌ها
CREATE TABLE IF NOT EXISTS exams (
    id INT AUTO_INCREMENT PRIMARY KEY,
    subject_id INT NULL,
    title VARCHAR(200) NOT NULL,
    exam_date DATE NOT NULL,
    exam_time VARCHAR(10) DEFAULT NULL COMMENT 'HH:MM',
    location VARCHAR(150) DEFAULT NULL,
    description TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE SET NULL,
    INDEX idx_exam_date (exam_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- تنظیمات اپ
CREATE TABLE IF NOT EXISTS app_settings (
    `key` VARCHAR(100) PRIMARY KEY,
    `value` TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- مقادیر پیش‌فرض تنظیمات
INSERT INTO app_settings (`key`, `value`) VALUES
('daily_goal','180'),
('pomodoro_work','25'),
('pomodoro_break','5'),
('pomodoro_long_break','15'),
('theme','light'),
('accent','#6366f1'),
('streak_enabled','1'),
('date_mode','jalali')
ON DUPLICATE KEY UPDATE `value`=VALUES(`value`);

-- داده نمونه دروس
INSERT INTO subjects (name, color, icon) VALUES
('ریاضی', '#ef4444', '🔢'),
('فیزیک', '#3b82f6', '⚛️'),
('شیمی', '#10b981', '🧪'),
('زبان انگلیسی', '#f59e0b', '🔤'),
('برنامه‌نویسی', '#8b5cf6', '💻')
ON DUPLICATE KEY UPDATE name=name;
