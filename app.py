from flask import Flask
import os
import sqlite3
from werkzeug.security import generate_password_hash

from config import Config
from routes.auth import auth_bp
from routes.files import files_bp
from routes.bulk import bulk_bp
from routes.admin import admin_bp
from routes.groups import groups_bp

# Создаём приложение
app = Flask(__name__)
app.config.from_object(Config)

# Создаём папки для загрузок
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(Config.UPLOAD_FOLDER, 'group_uploads'), exist_ok=True)


def check_and_create_db():
    db_path = app.config['DATABASE']
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    def add_column_if_not_exists(table, column, type):
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type}")
        except sqlite3.OperationalError:
            pass

    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, email TEXT UNIQUE, password TEXT, is_admin INTEGER DEFAULT 0, storage_limit INTEGER DEFAULT 3221225472, storage_used INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, user_id INTEGER, filename TEXT, original_filename TEXT, file_path TEXT, file_size INTEGER, file_type TEXT, is_folder INTEGER DEFAULT 0, parent_id INTEGER, is_deleted INTEGER DEFAULT 0, uploaded_at TIMESTAMP, deleted_at TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE, FOREIGN KEY (parent_id) REFERENCES files(id) ON DELETE CASCADE)''')
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY, name TEXT, owner_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(owner_id) REFERENCES users(id))''')
    add_column_if_not_exists('groups', 'invite_token', 'TEXT')
    add_column_if_not_exists('groups', 'pincode_hash', 'TEXT')
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS group_members (group_id INTEGER, user_id INTEGER, PRIMARY KEY (group_id, user_id), FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)''')
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS group_files (id INTEGER PRIMARY KEY, group_id INTEGER, uploader_id INTEGER, filename TEXT, original_filename TEXT, file_path TEXT, file_size INTEGER, file_type TEXT, is_folder INTEGER DEFAULT 0, parent_id INTEGER, uploaded_at TIMESTAMP, FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE, FOREIGN KEY(uploader_id) REFERENCES users(id), FOREIGN KEY(parent_id) REFERENCES group_files(id) ON DELETE CASCADE)''')

    try:
        cursor.execute('SELECT id FROM users WHERE username = ?', ('admin',))
        if not cursor.fetchone():
            hashed = generate_password_hash('admin123')
            cursor.execute('INSERT INTO users (username, email, password, is_admin) VALUES (?, ?, ?, 1)',
                           ('admin', 'admin@mycloud.com', hashed))
    except:
        pass

    conn.commit()
    conn.close()


app.register_blueprint(auth_bp)
app.register_blueprint(files_bp)
app.register_blueprint(bulk_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(groups_bp)

if __name__ == '__main__':
    check_and_create_db()
    app.run(debug=True, host='0.0.0.0', port=5000)