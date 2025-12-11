import sqlite3
from werkzeug.security import generate_password_hash
from config import Config


def init_database():
    db_path = Config.DATABASE
    print(f"Обновление базы данных: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    def add_column_if_not_exists(table, column, col_type):
        try:
            cursor.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
            )
            print(f"Добавлена колонка '{column}' в таблицу '{table}'")
        except sqlite3.OperationalError:
            # колонка уже существует
            pass

    # Таблица пользователей
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE,
            email         TEXT UNIQUE,
            password      TEXT,
            is_admin      INTEGER DEFAULT 0,
            storage_limit INTEGER DEFAULT 3221225472,
            storage_used  INTEGER DEFAULT 0,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )

    # Таблица личных файлов
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS files (
            id               INTEGER PRIMARY KEY,
            user_id          INTEGER,
            filename         TEXT,
            original_filename TEXT,
            file_path        TEXT,
            file_size        INTEGER,
            file_type        TEXT,
            is_folder        INTEGER DEFAULT 0,
            parent_id        INTEGER,
            is_deleted       INTEGER DEFAULT 0,
            uploaded_at      TIMESTAMP,
            deleted_at       TIMESTAMP,
            FOREIGN KEY (user_id)   REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_id) REFERENCES files(id) ON DELETE CASCADE
        )
        '''
    )

    # Таблица групп
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS groups (
            id         INTEGER PRIMARY KEY,
            name       TEXT,
            owner_id   INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
        '''
    )

    # Таблица инвайтов в группы
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS group_invites (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id    INTEGER NOT NULL,
            token       TEXT    NOT NULL UNIQUE,
            pincode_hash TEXT,
            expires_at  TEXT,
            max_uses    INTEGER,
            uses        INTEGER NOT NULL DEFAULT 0,
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_by  INTEGER NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (group_id)   REFERENCES groups(id) ON DELETE CASCADE,
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
        )
        '''
    )

    add_column_if_not_exists('groups', 'storage_limit', 'INTEGER DEFAULT 1073741824')
    add_column_if_not_exists('groups', 'invite_token',  'TEXT')
    add_column_if_not_exists('groups', 'pincode_hash',  'TEXT')

    # Участники групп
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS group_members (
            group_id INTEGER,
            user_id  INTEGER,
            PRIMARY KEY (group_id, user_id),
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id)  REFERENCES users(id) ON DELETE CASCADE
        )
        '''
    )

    # Файлы групп
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS group_files (
            id               INTEGER PRIMARY KEY,
            group_id         INTEGER,
            uploader_id      INTEGER,
            filename         TEXT,
            original_filename TEXT,
            file_path        TEXT,
            file_size        INTEGER,
            file_type        TEXT,
            is_folder        INTEGER DEFAULT 0,
            parent_id        INTEGER,
            uploaded_at      TIMESTAMP,
            FOREIGN KEY(group_id)    REFERENCES groups(id) ON DELETE CASCADE,
            FOREIGN KEY(uploader_id) REFERENCES users(id),
            FOREIGN KEY(parent_id)   REFERENCES group_files(id) ON DELETE CASCADE
        )
        '''
    )

    # Таблица для сброса пароля
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS password_resets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            token      TEXT    NOT NULL UNIQUE,
            expires_at TIMESTAMP NOT NULL,
            used       INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        '''
    )

    # Дополнительные колонки для групповых файлов
    add_column_if_not_exists('group_files', 'is_deleted', 'INTEGER DEFAULT 0')
    add_column_if_not_exists('group_files', 'deleted_at', 'TIMESTAMP')

    # Создание администратора по умолчанию
    try:
        cursor.execute(
            'SELECT id FROM users WHERE username = ?',
            ('admin',)
        )
        if not cursor.fetchone():
            hashed = generate_password_hash('admin')
            cursor.execute(
                '''
                INSERT INTO users (username, email, password, is_admin)
                VALUES (?, ?, ?, 1)
                ''',
                ('admin', 'admin@mycloud.com', hashed)
            )
    except Exception:
        pass

    conn.commit()
    conn.close()
    print("База данных готова!")


if __name__ == '__main__':
    init_database()
