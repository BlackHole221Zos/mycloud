import sqlite3
import os
import re
import shutil
from functools import wraps

from flask import session, redirect, url_for, flash, request
from config import Config
import filetype  # <--- новое


def get_db():
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def safe_filename(filename):
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


# ---------- Определение типа файла ----------

_EXT_TYPES = {
    'image':   ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'ico'],
    'video':   ['mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm'],
    'audio':   ['mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a'],
    'document':['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'rtf'],
    'archive': ['zip', 'rar', '7z', 'tar', 'gz', 'bz2'],
    'code':    ['py', 'js', 'html', 'css', 'java', 'cpp', 'c', 'php', 'json', 'xml'],
}


def _get_file_type_by_extension(filename: str) -> str:
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    for t, exts in _EXT_TYPES.items():
        if ext in exts:
            return t
    return 'file'


def get_file_type_by_content(file_storage, fallback_name: str | None = None) -> str:
    """
    Определяет тип файла по содержимому (magic-байты) через filetype,
    при неудаче падает назад на проверку по расширению. [web:831][web:829]

    file_storage: werkzeug.datastructures.FileStorage
    fallback_name: имя файла для fallback по расширению
    """
    try:
        # читаем только "шапку", чтобы не грузить весь файл в память
        head = file_storage.stream.read(261)
        file_storage.stream.seek(0)

        kind = filetype.guess(head)
        if kind is not None:
            mime = kind.mime or ''

            if mime.startswith('image/'):
                return 'image'
            if mime.startswith('video/'):
                return 'video'
            if mime.startswith('audio/'):
                return 'audio'

            # базовые документы
            if mime in (
                'application/pdf',
                'application/msword',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/vnd.ms-excel',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'application/vnd.ms-powerpoint',
                'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                'text/plain',
                'application/rtf',
            ):
                return 'document'

            # архивы
            if mime in (
                'application/zip',
                'application/x-rar-compressed',
                'application/x-7z-compressed',
                'application/x-tar',
                'application/gzip',
                'application/x-bzip2',
            ):
                return 'archive'

            # условно "код"
            if mime.startswith('text/') or 'json' in mime or 'xml' in mime:
                return 'code'
    except Exception:
        # если что-то пошло не так — просто падаем на расширение
        pass

    # fallback по названию
    if fallback_name:
        return _get_file_type_by_extension(fallback_name)
    # если вообще ничего нет
    return 'file'


# Старое API, если где-то ещё используется по имени
def get_file_type(filename: str) -> str:
    return _get_file_type_by_extension(filename)


def format_size(size):
    if size is None:
        size = 0
    for unit in ['Б', 'КБ', 'МБ', 'ГБ']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} ТБ"


def get_user_storage_info(user_id):
    conn = get_db()
    user = conn.execute(
        'SELECT storage_limit, storage_used FROM users WHERE id = ?',
        (user_id,)
    ).fetchone()

    active = conn.execute(
        'SELECT COALESCE(SUM(file_size), 0) as total '
        'FROM files WHERE user_id = ? AND is_folder = 0 AND is_deleted = 0',
        (user_id,)
    ).fetchone()

    trash = conn.execute(
        'SELECT COALESCE(SUM(file_size), 0) as total '
        'FROM files WHERE user_id = ? AND is_folder = 0 AND is_deleted = 1',
        (user_id,)
    ).fetchone()
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
            'percent_trash': round((trash_size / limit) * 100, 1) if limit > 0 else 0,
        }

    return {
        'limit': 3221225472,
        'used': 0,
        'percent': 0,
        'limit_formatted': '3.00 GB',
        'used_formatted': '0 B'
    }


def get_group_storage_info(group_id):
    conn = get_db()

    active = conn.execute(
        'SELECT COALESCE(SUM(file_size), 0) AS total '
        'FROM group_files WHERE group_id = ? AND is_folder = 0 AND is_deleted = 0',
        (group_id,)
    ).fetchone()

    trash = conn.execute(
        'SELECT COALESCE(SUM(file_size), 0) AS total '
        'FROM group_files WHERE group_id = ? AND is_folder = 0 AND is_deleted = 1',
        (group_id,)
    ).fetchone()

    group = conn.execute('SELECT storage_limit FROM groups WHERE id = ?', (group_id,)).fetchone()
    conn.close()

    limit = group['storage_limit'] if group and group['storage_limit'] else 1073741824
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
        'percent_trash': round((trash_size / limit) * 100, 1) if limit > 0 else 0,
    }


def update_user_storage(user_id):
    conn = get_db()
    result = conn.execute(
        'SELECT COALESCE(SUM(file_size), 0) as total '
        'FROM files WHERE user_id = ? AND is_folder = 0',
        (user_id,)
    ).fetchone()
    conn.execute(
        'UPDATE users SET storage_used = ? WHERE id = ?',
        (result['total'], user_id)
    )
    conn.commit()
    conn.close()


def get_user_folder(user_id):
    folder = os.path.join(Config.UPLOAD_FOLDER, str(user_id))
    os.makedirs(folder, exist_ok=True)
    return folder


def delete_file_from_disk(file_path):
    full_path = os.path.join(Config.UPLOAD_FOLDER, file_path)
    if os.path.exists(full_path):
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
        else:
            os.remove(full_path)


# ========= РЕКУРСИВНЫЕ ОПЕРАЦИИ ДЛЯ ПАПОК (files / group_files) =========

def delete_folder_contents(conn, folder_id, table_name='files'):
    """
    Рекурсивное удаление содержимого папки (из БД и диска).
    Работает и для files, и для group_files.
    """
    items = conn.execute(
        f'SELECT * FROM {table_name} WHERE parent_id = ?',
        (folder_id,)
    ).fetchall()

    for item in items:
        if item['is_folder']:
            delete_folder_contents(conn, item['id'], table_name)

        delete_file_from_disk(item['file_path'])
        conn.execute(
            f'DELETE FROM {table_name} WHERE id = ?',
            (item['id'],)
        )


def move_folder_to_trash(conn, folder_id, table_name='files'):
    """
    Рекурсивное перемещение в корзину.
    Для group_files предполагается наличие полей is_deleted, deleted_at.
    """
    from datetime import datetime

    items = conn.execute(
        f'SELECT * FROM {table_name} WHERE parent_id = ?',
        (folder_id,)
    ).fetchall()

    for item in items:
        conn.execute(
            f'UPDATE {table_name} SET is_deleted = 1, deleted_at = ? WHERE id = ?',
            (datetime.now(), item['id'])
        )
        if item['is_folder']:
            move_folder_to_trash(conn, item['id'], table_name)


def restore_folder_contents(conn, folder_id, table_name='files'):
    """
    Рекурсивное восстановление из корзины.
    """
    items = conn.execute(
        f'SELECT * FROM {table_name} WHERE parent_id = ?',
        (folder_id,)
    ).fetchall()

    for item in items:
        conn.execute(
            f'UPDATE {table_name} SET is_deleted = 0, deleted_at = NULL WHERE id = ?',
            (item['id'],)
        )
        if item['is_folder']:
            restore_folder_contents(conn, item['id'], table_name)
