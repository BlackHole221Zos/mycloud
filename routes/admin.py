from flask import Blueprint, render_template, request, redirect, url_for, flash, session
import os
import shutil
import uuid

from config import Config
from utils import (
    get_db, admin_required, safe_filename, get_file_type, format_size,
    get_user_storage_info, update_user_storage, get_user_folder,
    delete_file_from_disk, delete_folder_contents
)

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin')
@admin_required
def admin_panel():
    conn = get_db()
    users = conn.execute('''
        SELECT u.*, 
               COUNT(f.id) as file_count,
               COALESCE(SUM(CASE WHEN f.is_folder = 0 AND f.is_deleted = 0 THEN f.file_size ELSE 0 END), 0) as total_size
        FROM users u
        LEFT JOIN files f ON u.id = f.user_id
        GROUP BY u.id
        ORDER BY u.created_at DESC
    ''').fetchall()
    conn.close()

    return render_template('admin.html', users=users, format_size=format_size)


@admin_bp.route('/admin/user/<int:user_id>')
@admin_bp.route('/admin/user/<int:user_id>/folder/<int:folder_id>')
@admin_required
def admin_user_files(user_id, folder_id=None):
    conn = get_db()

    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        flash('Пользователь не найден', 'error')
        conn.close()
        return redirect(url_for('admin.admin_panel'))

    if folder_id:
        files = conn.execute('''
            SELECT * FROM files 
            WHERE user_id = ? AND parent_id = ? AND is_deleted = 0
            ORDER BY is_folder DESC, original_filename
        ''', (user_id, folder_id)).fetchall()
        current_folder = conn.execute('SELECT * FROM files WHERE id = ?', (folder_id,)).fetchone()
    else:
        files = conn.execute('''
            SELECT * FROM files 
            WHERE user_id = ? AND parent_id IS NULL AND is_deleted = 0
            ORDER BY is_folder DESC, original_filename
        ''', (user_id,)).fetchall()
        current_folder = None

    breadcrumbs = []
    if folder_id:
        temp_folder_id = folder_id
        while temp_folder_id:
            folder = conn.execute('SELECT * FROM files WHERE id = ?', (temp_folder_id,)).fetchone()
            if folder:
                breadcrumbs.insert(0, {'id': folder['id'], 'name': folder['original_filename']})
                temp_folder_id = folder['parent_id']
            else:
                break

    conn.close()

    storage_info = get_user_storage_info(user_id)

    return render_template('admin_user_files.html',
                           user=user,
                           files=files,
                           current_folder=current_folder,
                           folder_id=folder_id,
                           breadcrumbs=breadcrumbs,
                           storage_info=storage_info,
                           format_size=format_size)


@admin_bp.route('/admin/upload/<int:user_id>', methods=['POST'])
@admin_required
def admin_upload_file(user_id):
    parent_id = request.form.get('parent_id')
    parent_id = int(parent_id) if parent_id else None

    if 'files' not in request.files:
        flash('Файлы не выбраны', 'error')
        return redirect(url_for('admin.admin_user_files', user_id=user_id, folder_id=parent_id))

    files = request.files.getlist('files')
    conn = get_db()

    if parent_id:
        parent = conn.execute('SELECT file_path FROM files WHERE id = ?', (parent_id,)).fetchone()
        upload_path = parent['file_path']
    else:
        upload_path = str(user_id)

    get_user_folder(user_id)

    for file in files:
        if file and file.filename:
            file.seek(0, 2)
            file_size = file.tell()
            file.seek(0)

            original_filename = safe_filename(file.filename)
            unique_filename = f"{uuid.uuid4()}_{original_filename}"
            file_path = os.path.join(upload_path, unique_filename)
            full_path = os.path.join(Config.UPLOAD_FOLDER, file_path)

            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            file.save(full_path)

            file_type = get_file_type(original_filename)

            conn.execute('''
                INSERT INTO files (user_id, filename, original_filename, file_path, file_size, file_type, parent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, unique_filename, original_filename, file_path, file_size, file_type, parent_id))

    conn.commit()
    conn.close()

    update_user_storage(user_id)

    flash('Файлы загружены', 'success')
    return redirect(url_for('admin.admin_user_files', user_id=user_id, folder_id=parent_id))


@admin_bp.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    if user_id == session['user_id']:
        flash('Нельзя удалить самого себя', 'error')
        return redirect(url_for('admin.admin_panel'))

    conn = get_db()

    user_folder = os.path.join(Config.UPLOAD_FOLDER, str(user_id))
    if os.path.exists(user_folder):
        shutil.rmtree(user_folder)

    conn.execute('DELETE FROM files WHERE user_id = ?', (user_id,))
    conn.execute('DELETE FROM users WHERE id = ?', (user_id,))

    conn.commit()
    conn.close()

    flash('Пользователь удалён', 'success')
    return redirect(url_for('admin.admin_panel'))


@admin_bp.route('/admin/delete_file/<int:file_id>', methods=['POST'])
@admin_required
def admin_delete_file(file_id):
    conn = get_db()
    file = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()

    if not file:
        flash('Файл не найден', 'error')
        conn.close()
        return redirect(url_for('admin.admin_panel'))

    user_id = file['user_id']
    parent_id = file['parent_id']

    delete_file_from_disk(file['file_path'])

    if file['is_folder']:
        delete_folder_contents(conn, file_id)

    conn.execute('DELETE FROM files WHERE id = ?', (file_id,))
    conn.commit()
    conn.close()

    update_user_storage(user_id)

    flash('Файл удалён', 'success')
    return redirect(url_for('admin.admin_user_files', user_id=user_id, folder_id=parent_id))