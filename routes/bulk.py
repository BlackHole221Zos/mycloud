from flask import Blueprint, request, redirect, url_for, flash, session, send_file
from datetime import datetime
import os
import zipfile
import io

from config import Config
from utils import (
    get_db, login_required, update_user_storage, delete_file_from_disk,
    delete_folder_contents, move_folder_to_trash, restore_folder_contents
)

bulk_bp = Blueprint('bulk', __name__)


@bulk_bp.route('/bulk_delete', methods=['POST'])
@login_required
def bulk_delete():
    """Массовое удаление файлов"""
    file_ids = request.form.getlist('file_ids')
    delete_type = request.form.get('delete_type', 'trash')
    redirect_url = request.form.get('redirect_url', url_for('files.dashboard'))

    if not file_ids:
        flash('Файлы не выбраны', 'error')
        return redirect(redirect_url)

    conn = get_db()
    deleted_count = 0

    for file_id in file_ids:
        try:
            file_id = int(file_id)
            file = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()

            if not file:
                continue

            if file['user_id'] != session['user_id'] and not session.get('is_admin'):
                continue

            if delete_type == 'permanent':
                delete_file_from_disk(file['file_path'])

                if file['is_folder']:
                    delete_folder_contents(conn, file_id)

                conn.execute('DELETE FROM files WHERE id = ?', (file_id,))
            else:
                conn.execute('''
                    UPDATE files SET is_deleted = 1, deleted_at = ? WHERE id = ?
                ''', (datetime.now(), file_id))

                if file['is_folder']:
                    move_folder_to_trash(conn, file_id)

            deleted_count += 1

        except (ValueError, TypeError):
            continue

    conn.commit()
    conn.close()

    update_user_storage(session['user_id'])

    if deleted_count > 0:
        if delete_type == 'permanent':
            flash(f'Удалено навсегда: {deleted_count} файл(ов)', 'success')
        else:
            flash(f'Перемещено в корзину: {deleted_count} файл(ов)', 'success')

    return redirect(redirect_url)


@bulk_bp.route('/bulk_download', methods=['POST'])
@login_required
def bulk_download():
    """Массовое скачивание файлов как ZIP"""
    file_ids = request.form.getlist('file_ids')

    if not file_ids:
        flash('Файлы не выбраны', 'error')
        return redirect(url_for('files.dashboard'))

    conn = get_db()

    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_id in file_ids:
            try:
                file_id = int(file_id)
                file = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()

                if not file:
                    continue

                if file['user_id'] != session['user_id'] and not session.get('is_admin'):
                    continue

                full_path = os.path.join(Config.UPLOAD_FOLDER, file['file_path'])

                if file['is_folder']:
                    for root, dirs, files_in_folder in os.walk(full_path):
                        for f in files_in_folder:
                            file_path = os.path.join(root, f)
                            arcname = os.path.join(file['original_filename'], os.path.relpath(file_path, full_path))
                            if os.path.exists(file_path):
                                zf.write(file_path, arcname)
                else:
                    if os.path.exists(full_path):
                        zf.write(full_path, file['original_filename'])

            except (ValueError, TypeError):
                continue

    conn.close()

    memory_file.seek(0)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        memory_file,
        as_attachment=True,
        download_name=f'files_{timestamp}.zip',
        mimetype='application/zip'
    )


@bulk_bp.route('/bulk_restore', methods=['POST'])
@login_required
def bulk_restore():
    """Массовое восстановление файлов из корзины"""
    file_ids = request.form.getlist('file_ids')

    if not file_ids:
        flash('Файлы не выбраны', 'error')
        return redirect(url_for('files.trash'))

    conn = get_db()
    restored_count = 0

    for file_id in file_ids:
        try:
            file_id = int(file_id)
            file = conn.execute('SELECT * FROM files WHERE id = ? AND user_id = ?',
                                (file_id, session['user_id'])).fetchone()

            if not file:
                continue

            conn.execute('UPDATE files SET is_deleted = 0, deleted_at = NULL WHERE id = ?', (file_id,))

            if file['is_folder']:
                restore_folder_contents(conn, file_id)

            restored_count += 1

        except (ValueError, TypeError):
            continue

    conn.commit()
    conn.close()

    update_user_storage(session['user_id'])

    if restored_count > 0:
        flash(f'Восстановлено: {restored_count} файл(ов)', 'success')

    return redirect(url_for('files.trash'))