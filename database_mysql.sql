CREATE DATABASE IF NOT EXISTS pdf_web
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

USE pdf_web;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(120) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('admin', 'user') DEFAULT 'user',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS documents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    extracted_text LONGTEXT NULL,
    file_size BIGINT NULL,
    page_count INT NULL,
    extraction_warning TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_documents_user_id (user_id),

    CONSTRAINT fk_documents_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS exams (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    document_id INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    difficulty VARCHAR(50) DEFAULT 'Trung bình',
    category VARCHAR(150) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_exams_user_id (user_id),
    INDEX idx_exams_document_id (document_id),
    CONSTRAINT fk_exams_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_exams_document
        FOREIGN KEY (document_id) REFERENCES documents(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS questions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    exam_id INT NOT NULL,
    content LONGTEXT NOT NULL,
    option_a TEXT NOT NULL,
    option_b TEXT NOT NULL,
    option_c TEXT NOT NULL,
    option_d TEXT NOT NULL,
    correct_answer VARCHAR(1) NOT NULL,
    explanation TEXT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_questions_exam_id (exam_id),
    CONSTRAINT fk_questions_exam
        FOREIGN KEY (exam_id) REFERENCES exams(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS activity_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL,
    action VARCHAR(255) NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_activity_log_user_id (user_id),
    CONSTRAINT fk_activity_log_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- =====================================================================
-- MIGRATION: Chạy các lệnh dưới đây nếu bạn ĐÃ có database cũ và chỉ
-- muốn thêm các cột/bảng mới, thay vì tạo lại từ đầu.
-- Mỗi câu lệnh có thể báo lỗi "Duplicate column" nếu cột đã tồn tại,
-- bỏ qua lỗi đó và chạy tiếp các dòng còn lại.
-- =====================================================================

-- ALTER TABLE documents ADD COLUMN file_size INT NULL;
-- ALTER TABLE documents ADD COLUMN extraction_warning TEXT NULL AFTER page_count;
-- ALTER TABLE documents ADD COLUMN page_count INT NULL;
-- ALTER TABLE exams ADD COLUMN category VARCHAR(150) NULL;
-- ALTER TABLE users ADD COLUMN role ENUM('admin','user') DEFAULT 'user';
-- CREATE TABLE IF NOT EXISTS activity_log (
--     id INT AUTO_INCREMENT PRIMARY KEY,
--     user_id INT NULL,
--     action VARCHAR(255) NOT NULL,
--     timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
--     INDEX idx_activity_log_user_id (user_id),
--     CONSTRAINT fk_activity_log_user
--         FOREIGN KEY (user_id) REFERENCES users(id)
--         ON DELETE SET NULL
-- ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
