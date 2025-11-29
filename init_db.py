import sqlite3
import os
from werkzeug.security import generate_password_hash


def init_database():
    """Создание базы данных и таблиц"""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_PATH = os.path.join(BASE_DIR, 'cloud.db')

    # Если база уже есть - не трогаем
    if os.path.exists(DB_PATH):
        print('✅ База данных уже существует')
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Создаём таблицу пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            storage_limit INTEGER DEFAULT 3221225472,
            storage_used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Создаём таблицу файлов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            file_type TEXT,
            is_folder INTEGER DEFAULT 0,
            parent_id INTEGER DEFAULT NULL,
            is_deleted INTEGER DEFAULT 0,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMP DEFAULT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (parent_id) REFERENCES files(id)
        )
    ''')

    # Создаём админа
    hashed = generate_password_hash('admin123')
    cursor.execute('''
        INSERT INTO users (username, email, password, is_admin)
        VALUES (?, ?, ?, 1)
    ''', ('admin', 'admin@mycloud.com', hashed))

    conn.commit()
    conn.close()

    print(' База данных создана!')
    print('Логин: admin')
    print(' Пароль: admin123')


if __name__ == '__main__':

    init_database()
