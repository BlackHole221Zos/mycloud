import sqlite3
import os
from werkzeug.security import generate_password_hash
from config import Config  

def init_database():
    db_path = Config.DATABASE
    print(f" Настройка базы данных: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Таблица пользователей
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

    # 2. Таблица файлов
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

    # 3. Создаем админа
    try:
        cursor.execute('SELECT id FROM users WHERE username = ?', ('admin',))
        if not cursor.fetchone():
            hashed = generate_password_hash('admin123')
            cursor.execute('''
                INSERT INTO users (username, email, password, is_admin) 
                VALUES (?, ?, ?, 1)
            ''', ('admin', 'admin@mycloud.com', hashed))
            print(" Пользователь 'admin' создан.")
        else:
            print(" Пользователь 'admin' уже существует.")
    except Exception as e:
        print(f"Ошибка создания админа: {e}")

    conn.commit()
    conn.close()
    print(" База данных успешно инициализирована!")

if __name__ == '__main__':
    init_database()
