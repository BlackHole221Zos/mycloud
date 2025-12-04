import sqlite3
import os
import re
import shutil
from flask import session, redirect, url_for, flash, request
from functools import wraps
from config import Config

def get_db():
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def safe_filename(filename):
    if not filename: return 'unnamed'
    filename = filename.replace('\\', '/').split('/')[-1]
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
    while '..' in filename: filename = filename.replace('..', '.')
    filename = filename.strip()
    if not filename or filename == '.': return 'unnamed'
    return filename

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Необходимо войти в систему.', 'error')
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Необходимо войти в систему.', 'error')
            return redirect(url_for('auth.login'))
        if not session.get('is_admin'):
            flash('Доступ запрещён.', 'error')
            return redirect(url_for('files.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def get_file_type(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    types = {'image': ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'ico'], 'video': ['mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm'], 'audio': ['mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a'], 'document': ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'rtf'], 'archive': ['zip', 'rar', '7z', 'tar', 'gz', 'bz2'], 'code': ['py', 'js', 'html', 'css', 'java', 'cpp', 'c', 'php', 'json', 'xml']}
    for t, exts in types.items():
        if ext in exts: return t
    return 'file'

def format_size(size):
    if size is None: size = 0
    for unit in ['Б', 'КБ', 'МБ', 'ГБ']:
        if size < 1024: return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} ТБ"

def get_user_storage_info(user_id):
    conn = get_db()
    user = conn.execute('SELECT storage_limit, storage_used FROM users WHERE id = ?', (user_id,)).fetchone()
    active = conn.execute('SELECT COALESCE(SUM(file_size), 0) as total FROM files WHERE user_id = ? AND is_folder = 0 AND is_deleted = 0', (user_id,)).fetchone()
    trash = conn.execute('SELECT COALESCE(SUM(file_size), 0) as total FROM files WHERE user_id = ? AND is_folder = 0 AND is_deleted = 1', (user_id,)).fetchone()
    conn.close()
    if user:
        limit = user['storage_limit'] if user['storage_limit'] else 3221225472
        active_size = active['total'] if active else 0
        trash_size = trash['total'] if trash else 0
        total_used = active_size + trash_size
        return {'limit': limit, 'used': total_used, 'active': active_size, 'trash': trash_size, 'limit_formatted': format_size(limit), 'used_formatted': format_size(total_used), 'active_formatted': format_size(active_size), 'trash_formatted': format_size(trash_size), 'percent': round((total_used / limit) * 100, 1) if limit > 0 else 0, 'percent_active': round((active_size / limit) * 100, 1) if limit > 0 else 0, 'percent_trash': round((trash_size / limit) * 100, 1) if limit > 0 else 0}
    return {'limit': 3221225472, 'used': 0, 'percent': 0, 'limit_formatted': '3.00 GB', 'used_formatted': '0 B'}


def get_group_storage_info(group_id):
    conn = get_db()
    result = conn.execute(
        'SELECT COALESCE(SUM(file_size), 0) as total FROM group_files WHERE group_id = ? AND is_folder = 0',
        (group_id,)).fetchone()
    used = result['total']

    group = conn.execute('SELECT storage_limit FROM groups WHERE id = ?', (group_id,)).fetchone()
    conn.close()

    limit = group['storage_limit'] if group and group['storage_limit'] else 1073741824

    return {
        'limit': limit,
        'used': used,
        'limit_formatted': format_size(limit),
        'used_formatted': format_size(used),
        'percent': round((used / limit) * 100, 1) if limit > 0 else 0
    }
def update_user_storage(user_id):
    conn = get_db()
    result = conn.execute('SELECT COALESCE(SUM(file_size), 0) as total FROM files WHERE user_id = ? AND is_folder = 0', (user_id,)).fetchone()
    conn.execute('UPDATE users SET storage_used = ? WHERE id = ?', (result['total'], user_id))
    conn.commit()
    conn.close()

def get_user_folder(user_id):
    folder = os.path.join(Config.UPLOAD_FOLDER, str(user_id))
    os.makedirs(folder, exist_ok=True)
    return folder

def delete_file_from_disk(file_path):
    full_path = os.path.join(Config.UPLOAD_FOLDER, file_path)
    if os.path.exists(full_path):
        if os.path.isdir(full_path): shutil.rmtree(full_path)
        else: os.remove(full_path)

# 👇 УНИВЕРСАЛЬНЫЕ ФУНКЦИИ УДАЛЕНИЯ (ДЛЯ FILES И GROUP_FILES) 👇

def delete_folder_contents(conn, folder_id, table_name='files'):
    """Рекурсивное удаление содержимого папки (из БД и диска)."""
    items = conn.execute(f'SELECT * FROM {table_name} WHERE parent_id = ?', (folder_id,)).fetchall()
    for item in items:
        if item['is_folder']:
            delete_folder_contents(conn, item['id'], table_name)
        delete_file_from_disk(item['file_path'])
        conn.execute(f'DELETE FROM {table_name} WHERE id = ?', (item['id'],))

def move_folder_to_trash(conn, folder_id, table_name='files'):
    """Рекурсивное перемещение в корзину."""
    from datetime import datetime
    items = conn.execute(f'SELECT * FROM {table_name} WHERE parent_id = ?', (folder_id,)).fetchall()
    for item in items:
        conn.execute(f'''
            UPDATE {table_name} SET is_deleted = 1, deleted_at = ? WHERE id = ?
        ''', (datetime.now(), item['id']))
        if item['is_folder']:
            move_folder_to_trash(conn, item['id'], table_name)

def restore_folder_contents(conn, folder_id, table_name='files'):
    """Рекурсивное восстановление."""
    items = conn.execute(f'SELECT * FROM {table_name} WHERE parent_id = ?', (folder_id,)).fetchall()
    for item in items:
        conn.execute(f'UPDATE {table_name} SET is_deleted = 0, deleted_at = NULL WHERE id = ?', (item['id'],))
        if item['is_folder']:
            restore_folder_contents(conn, item['id'], table_name)