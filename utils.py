import sqlite3
import os
import re
import shutil
from flask import session, redirect, url_for, flash
from functools import wraps
from config import Config


def get_db():
    """Подключение к базе данных"""
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def safe_filename(filename):
    """Безопасное имя файла с поддержкой русских символов"""
    if not filename:
        return 'unnamed'

    filename = filename.replace('\\', '/').split('/')[-1]
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)

    while '..' in filename:
        filename = filename.replace('..', '.')

    filename = filename.strip()

    if not filename or filename == '.':
        return 'unnamed'

    return filename


def login_required(f):
    """Декоратор для проверки авторизации"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Необходимо войти в систему', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """Декоратор для проверки прав администратора"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Необходимо войти в систему', 'error')
            return redirect(url_for('auth.login'))
        if not session.get('is_admin'):
            flash('Доступ запрещён', 'error')
            return redirect(url_for('files.dashboard'))
        return f(*args, **kwargs)

    return decorated_function


def get_file_type(filename):
    """Определение типа файла"""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    types = {
        'image': ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'ico'],
        'video': ['mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm'],
        'audio': ['mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a'],
        'document': ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'rtf'],
        'archive': ['zip', 'rar', '7z', 'tar', 'gz', 'bz2'],
        'code': ['py', 'js', 'html', 'css', 'java', 'cpp', 'c', 'php', 'json', 'xml']
    }

    for file_type, extensions in types.items():
        if ext in extensions:
            return file_type

    return 'file'


def format_size(size):
    """Форматирование размера файла"""
    if size is None:
        size = 0
    for unit in ['Б', 'КБ', 'МБ', 'ГБ']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} ТБ"


def get_user_storage_info(user_id):
    """Получение информации о хранилище пользователя"""
    conn = get_db()
    user = conn.execute('SELECT storage_limit, storage_used FROM users WHERE id = ?', (user_id,)).fetchone()

    # Считаем отдельно активные файлы
    active = conn.execute('''
        SELECT COALESCE(SUM(file_size), 0) as total 
        FROM files 
        WHERE user_id = ? AND is_folder = 0 AND is_deleted = 0
    ''', (user_id,)).fetchone()

    # Считаем файлы в корзине
    trash = conn.execute('''
        SELECT COALESCE(SUM(file_size), 0) as total 
        FROM files 
        WHERE user_id = ? AND is_folder = 0 AND is_deleted = 1
    ''', (user_id,)).fetchone()

    conn.close()

    if user:
        limit = user['storage_limit'] if user['storage_limit'] else 3221225472
        active_size = active['total'] if active else 0
        trash_size = trash['total'] if trash else 0
        total_used = active_size + trash_size

        return {
            'limit': limit,
            'used': total_used,
            'active': active_size,
            'trash': trash_size,
            'limit_formatted': format_size(limit),
            'used_formatted': format_size(total_used),
            'active_formatted': format_size(active_size),
            'trash_formatted': format_size(trash_size),
            'percent': round((total_used / limit) * 100, 1) if limit > 0 else 0,
            'percent_active': round((active_size / limit) * 100, 1) if limit > 0 else 0,
            'percent_trash': round((trash_size / limit) * 100, 1) if limit > 0 else 0
        }

    return {
        'limit': 3221225472,
        'used': 0,
        'active': 0,
        'trash': 0,
        'limit_formatted': '3.00 ГБ',
        'used_formatted': '0.00 Б',
        'active_formatted': '0.00 Б',
        'trash_formatted': '0.00 Б',
        'percent': 0,
        'percent_active': 0,
        'percent_trash': 0
    }


def update_user_storage(user_id):
    """Обновление использованного места"""
    conn = get_db()
    result = conn.execute('''
        SELECT COALESCE(SUM(file_size), 0) as total 
        FROM files 
        WHERE user_id = ? AND is_folder = 0
    ''', (user_id,)).fetchone()

    conn.execute('UPDATE users SET storage_used = ? WHERE id = ?', (result['total'], user_id))
    conn.commit()
    conn.close()


def get_user_folder(user_id):
    """Получение пути к папке пользователя"""
    folder = os.path.join(Config.UPLOAD_FOLDER, str(user_id))
    os.makedirs(folder, exist_ok=True)
    return folder


def delete_file_from_disk(file_path):
    """Удаление файла с диска"""
    full_path = os.path.join(Config.UPLOAD_FOLDER, file_path)
    if os.path.exists(full_path):
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
        else:
            os.remove(full_path)


def delete_folder_contents(conn, folder_id):
    """Рекурсивное удаление содержимого папки"""
    items = conn.execute('SELECT * FROM files WHERE parent_id = ?', (folder_id,)).fetchall()
    for item in items:
        if item['is_folder']:
            delete_folder_contents(conn, item['id'])
        delete_file_from_disk(item['file_path'])
        conn.execute('DELETE FROM files WHERE id = ?', (item['id'],))


def move_folder_to_trash(conn, folder_id):
    """Рекурсивное перемещение содержимого папки в корзину"""
    from datetime import datetime
    items = conn.execute('SELECT * FROM files WHERE parent_id = ?', (folder_id,)).fetchall()
    for item in items:
        conn.execute('''
            UPDATE files SET is_deleted = 1, deleted_at = ? WHERE id = ?
        ''', (datetime.now(), item['id']))
        if item['is_folder']:
            move_folder_to_trash(conn, item['id'])


def restore_folder_contents(conn, folder_id):
    """Рекурсивное восстановление содержимого папки"""
    items = conn.execute('SELECT * FROM files WHERE parent_id = ?', (folder_id,)).fetchall()
    for item in items:
        conn.execute('UPDATE files SET is_deleted = 0, deleted_at = NULL WHERE id = ?', (item['id'],))
        if item['is_folder']:
            restore_folder_contents(conn, item['id'])