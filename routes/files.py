from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_file, jsonify, abort
from datetime import datetime
import os
import uuid
import zipfile
import io
import shutil

from config import Config
from utils import (
    get_db, safe_filename, login_required, format_size,
    get_user_storage_info, update_user_storage, delete_file_from_disk,
    delete_folder_contents, move_folder_to_trash, restore_folder_contents,
    get_file_type_by_content
)

files_bp = Blueprint('files', __name__)



@files_bp.route('/dashboard')
@files_bp.route('/dashboard/<int:folder_id>')
@login_required
def dashboard(folder_id=None):
    conn = get_db()

    if folder_id:
        files = conn.execute('''
            SELECT * FROM files 
            WHERE user_id = ? AND parent_id = ? AND is_deleted = 0
            ORDER BY is_folder DESC, original_filename
        ''', (session['user_id'], folder_id)).fetchall()

        current_folder = conn.execute('SELECT * FROM files WHERE id = ?', (folder_id,)).fetchone()
    else:
        files = conn.execute('''
            SELECT * FROM files 
            WHERE user_id = ? AND parent_id IS NULL AND is_deleted = 0
            ORDER BY is_folder DESC, original_filename
        ''', (session['user_id'],)).fetchall()
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

    storage_info = get_user_storage_info(session['user_id'])

    return render_template('dashboard.html',
                           files=files,
                           current_folder=current_folder,
                           folder_id=folder_id,
                           breadcrumbs=breadcrumbs,
                           storage_info=storage_info,
                           format_size=format_size)


@files_bp.route('/create_folder', methods=['POST'])
@login_required
def create_folder():
    folder_name = request.form.get('folder_name', '').strip()
    parent_id = request.form.get('parent_id')
    parent_id = int(parent_id) if parent_id else None

    if not folder_name:
        flash('Введите имя папки', 'error')
        return redirect(url_for('files.dashboard', folder_id=parent_id))

    folder_name = safe_filename(folder_name)

    conn = get_db()

    existing = conn.execute('''
        SELECT id FROM files 
        WHERE user_id = ? AND original_filename = ? AND parent_id IS ? AND is_folder = 1 AND is_deleted = 0
    ''', (session['user_id'], folder_name, parent_id)).fetchone()

    if existing:
        flash('Папка с таким именем уже существует', 'error')
        conn.close()
        return redirect(url_for('files.dashboard', folder_id=parent_id))

    unique_name = f"{uuid.uuid4()}_{folder_name}"

    if parent_id:
        parent = conn.execute('SELECT file_path FROM files WHERE id = ?', (parent_id,)).fetchone()
        folder_path = os.path.join(parent['file_path'], unique_name)
    else:
        folder_path = os.path.join(str(session['user_id']), unique_name)

    full_path = os.path.join(Config.UPLOAD_FOLDER, folder_path)
    os.makedirs(full_path, exist_ok=True)

    conn.execute('''
        INSERT INTO files (user_id, filename, original_filename, file_path, is_folder, parent_id)
        VALUES (?, ?, ?, ?, 1, ?)
    ''', (session['user_id'], unique_name, folder_name, folder_path, parent_id))
    conn.commit()
    conn.close()

    flash(f'Папка "{folder_name}" создана', 'success')
    return redirect(url_for('files.dashboard', folder_id=parent_id))


@files_bp.route('/upload', methods=['POST'])
@login_required
def upload_file():
    parent_id = request.form.get('parent_id')
    parent_id = int(parent_id) if parent_id else None

    if 'files' not in request.files:
        flash('Файлы не выбраны', 'error')
        return redirect(url_for('files.dashboard', folder_id=parent_id))

    files = request.files.getlist('files')

    if not files or files[0].filename == '':
        flash('Файлы не выбраны', 'error')
        return redirect(url_for('files.dashboard', folder_id=parent_id))

    conn = get_db()
    user = conn.execute('SELECT storage_limit, storage_used FROM users WHERE id = ?', (session['user_id'],)).fetchone()

    if parent_id:
        parent = conn.execute('SELECT file_path FROM files WHERE id = ?', (parent_id,)).fetchone()
        upload_path = parent['file_path']
    else:
        upload_path = str(session['user_id'])

    uploaded_count = 0
    total_storage_used = user['storage_used'] if user['storage_used'] else 0
    storage_limit = user['storage_limit'] if user['storage_limit'] else 3221225472

    for file in files:
        if file and file.filename:
            file.seek(0, 2)
            file_size = file.tell()
            file.seek(0)

            if total_storage_used + file_size > storage_limit:
                flash('Недостаточно места в хранилище', 'error')
                break

            original_filename = safe_filename(file.filename)
            unique_filename = f"{uuid.uuid4()}_{original_filename}"
            file_path = os.path.join(upload_path, unique_filename)
            full_path = os.path.join(Config.UPLOAD_FOLDER, file_path)

            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            file.save(full_path)

            file_type = get_file_type_by_content(file, fallback_name=original_filename)

            conn.execute('''
                INSERT INTO files (user_id, filename, original_filename, file_path, file_size, file_type, parent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (session['user_id'], unique_filename, original_filename, file_path, file_size, file_type, parent_id))

            total_storage_used += file_size
            uploaded_count += 1

    conn.commit()
    conn.close()

    update_user_storage(session['user_id'])

    if uploaded_count > 0:
        flash(f'Загружено файлов: {uploaded_count}', 'success')

    return redirect(url_for('files.dashboard', folder_id=parent_id))


@files_bp.route('/download/<int:file_id>')
@login_required
def download_file(file_id):
    conn = get_db()
    file = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    conn.close()

    if not file:
        flash('Файл не найден', 'error')
        return redirect(url_for('files.dashboard'))

    if file['user_id'] != session['user_id'] and not session.get('is_admin'):
        flash('Нет доступа к файлу', 'error')
        return redirect(url_for('files.dashboard'))

    full_path = os.path.join(Config.UPLOAD_FOLDER, file['file_path'])

    if file['is_folder']:
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files_in_folder in os.walk(full_path):
                for f in files_in_folder:
                    file_path_in_folder = os.path.join(root, f)
                    arcname = os.path.relpath(file_path_in_folder, full_path)
                    zf.write(file_path_in_folder, arcname)
        memory_file.seek(0)
        return send_file(memory_file, as_attachment=True,
                         download_name=f"{file['original_filename']}.zip",
                         mimetype='application/zip')
    else:
        if os.path.exists(full_path):
            return send_file(full_path, as_attachment=True,
                             download_name=file['original_filename'])
        else:
            flash('Файл не найден на диске', 'error')
            return redirect(url_for('files.dashboard'))


@files_bp.route('/preview/<int:file_id>')
@login_required
def preview_file(file_id):
    conn = get_db()
    file = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    conn.close()

    # нет файла или это папка
    if not file or file['is_folder']:
        abort(404)

    # только картинки
    if file['file_type'] != 'image':
        abort(404)

    full_path = os.path.join(Config.UPLOAD_FOLDER, file['file_path'])
    if not os.path.exists(full_path):
        abort(404)

    # отдаём файл браузеру как есть
    return send_file(full_path)

@files_bp.route('/preview_inline/<int:file_id>')
@login_required
def preview_inline(file_id):
    conn = get_db()
    file = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()
    conn.close()

    if not file or file['is_folder']:
        abort(404)

    full_path = os.path.join(Config.UPLOAD_FOLDER, file['file_path'])
    if not os.path.exists(full_path):
        abort(404)

    # По типу выбираем способ отдачи
    if file['file_type'] == 'image':
        # можно использовать уже существующий preview, но этот тоже ок
        return send_file(full_path)

    # PDF — отдать с правильным mimetype
    if file['file_type'] == 'document' and file['original_filename'].lower().endswith('.pdf'):
        return send_file(full_path, mimetype='application/pdf')

    # Текст / код — читаем и возвращаем как text/plain
    if file['file_type'] in ('document', 'code'):
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        from flask import Response
        return Response(content, mimetype='text/plain; charset=utf-8')

    # Остальное пока не поддерживаем
    abort(415)


@files_bp.route('/edit/<int:file_id>', methods=['POST'])
@login_required
def edit_file(file_id):
    new_content = request.form.get('content', '')

    conn = get_db()
    file = conn.execute('SELECT * FROM files WHERE id = ? AND user_id = ?', (file_id, session['user_id'])).fetchone()
    if not file or file['is_folder']:
        conn.close()
        abort(404)

    full_path = os.path.join(Config.UPLOAD_FOLDER, file['file_path'])
    if not os.path.exists(full_path):
        conn.close()
        abort(404)

    # Разрешаем правку только “текстовых” файлов
    if file['file_type'] not in ('document', 'code'):
        conn.close()
        abort(415)

    # Перезаписываем файл
    with open(full_path, 'w', encoding='utf-8', errors='replace') as f:
        f.write(new_content)

    new_size = os.path.getsize(full_path)
    conn.execute('UPDATE files SET file_size = ? WHERE id = ?', (new_size, file_id))
    conn.commit()
    conn.close()
    update_user_storage(session['user_id'])

    return jsonify({'status': 'ok'})


@files_bp.route('/delete/<int:file_id>', methods=['POST'])
@login_required
def delete_file(file_id):
    delete_type = request.form.get('delete_type', 'trash')

    conn = get_db()
    file = conn.execute('SELECT * FROM files WHERE id = ?', (file_id,)).fetchone()

    if not file:
        flash('Файл не найден', 'error')
        conn.close()
        return redirect(url_for('files.dashboard'))

    if file['user_id'] != session['user_id'] and not session.get('is_admin'):
        flash('Нет доступа к файлу', 'error')
        conn.close()
        return redirect(url_for('files.dashboard'))

    user_id = file['user_id']

    if delete_type == 'permanent':
        delete_file_from_disk(file['file_path'])

        if file['is_folder']:
            delete_folder_contents(conn, file_id)

        conn.execute('DELETE FROM files WHERE id = ?', (file_id,))
        flash('Файл удалён навсегда', 'success')
    else:
        conn.execute('''
            UPDATE files SET is_deleted = 1, deleted_at = ? WHERE id = ?
        ''', (datetime.now(), file_id))

        if file['is_folder']:
            move_folder_to_trash(conn, file_id)

        flash('Файл перемещён в корзину', 'success')

    conn.commit()
    conn.close()

    update_user_storage(user_id)

    return redirect(request.referrer or url_for('files.dashboard'))


@files_bp.route('/trash')
@login_required
def trash():
    conn = get_db()
    files = conn.execute('''
        SELECT * FROM files 
        WHERE user_id = ? AND is_deleted = 1
        ORDER BY deleted_at DESC
    ''', (session['user_id'],)).fetchall()
    conn.close()

    storage_info = get_user_storage_info(session['user_id'])

    return render_template('trash.html', files=files, storage_info=storage_info, format_size=format_size)


@files_bp.route('/restore/<int:file_id>', methods=['POST'])
@login_required
def restore_file(file_id):
    conn = get_db()
    file = conn.execute('SELECT * FROM files WHERE id = ? AND user_id = ?',
                        (file_id, session['user_id'])).fetchone()

    if not file:
        flash('Файл не найден', 'error')
        conn.close()
        return redirect(url_for('files.trash'))

    conn.execute('UPDATE files SET is_deleted = 0, deleted_at = NULL WHERE id = ?', (file_id,))

    if file['is_folder']:
        restore_folder_contents(conn, file_id)

    conn.commit()
    conn.close()

    update_user_storage(session['user_id'])

    flash('Файл восстановлен', 'success')
    return redirect(url_for('files.trash'))


@files_bp.route('/empty_trash', methods=['POST'])
@login_required
def empty_trash():
    conn = get_db()
    files = conn.execute('SELECT * FROM files WHERE user_id = ? AND is_deleted = 1',
                         (session['user_id'],)).fetchall()

    for file in files:
        delete_file_from_disk(file['file_path'])

    conn.execute('DELETE FROM files WHERE user_id = ? AND is_deleted = 1', (session['user_id'],))
    conn.commit()
    conn.close()

    update_user_storage(session['user_id'])

    flash('Корзина очищена', 'success')
    return redirect(url_for('files.trash'))


@files_bp.route('/rename/<int:file_id>', methods=['POST'])
@login_required
def rename_file(file_id):
    new_name = request.form.get('new_name', '').strip()

    if not new_name:
        flash('Введите новое имя', 'error')
        return redirect(request.referrer or url_for('files.dashboard'))

    new_name = safe_filename(new_name)

    conn = get_db()
    file = conn.execute('SELECT * FROM files WHERE id = ? AND user_id = ?',
                        (file_id, session['user_id'])).fetchone()

    if not file:
        flash('Файл не найден', 'error')
        conn.close()
        return redirect(url_for('files.dashboard'))

    conn.execute('UPDATE files SET original_filename = ? WHERE id = ?', (new_name, file_id))
    conn.commit()
    conn.close()

    flash('Файл переименован', 'success')
    return redirect(request.referrer or url_for('files.dashboard'))


# --- НОВЫЕ ФУНКЦИИ ДЛЯ ПЕРЕМЕЩЕНИЯ ---

@files_bp.route('/get_folders_tree', methods=['GET'])
@login_required
def get_folders_tree():
    conn = get_db()
    folders = conn.execute('''
        SELECT id, original_filename, parent_id 
        FROM files 
        WHERE user_id = ? AND is_folder = 1 AND is_deleted = 0
        ORDER BY original_filename
    ''', (session['user_id'],)).fetchall()
    conn.close()

    folder_list = [{'id': f['id'], 'name': f['original_filename'], 'parent_id': f['parent_id']} for f in folders]
    return jsonify(folder_list)


def update_children_paths(conn, folder_id, new_parent_path):
    children = conn.execute('SELECT * FROM files WHERE parent_id = ?', (folder_id,)).fetchall()
    for child in children:
        child_new_path = os.path.join(new_parent_path, child['filename'])
        conn.execute('UPDATE files SET file_path = ? WHERE id = ?', (child_new_path, child['id']))
        if child['is_folder']:
            update_children_paths(conn, child['id'], child_new_path)


def copy_children_db(conn, old_parent_id, new_parent_id, new_parent_path):
    children = conn.execute('SELECT * FROM files WHERE parent_id = ? AND is_deleted = 0', (old_parent_id,)).fetchall()
    for child in children:
        new_path = os.path.join(new_parent_path, child['filename'])
        cursor = conn.execute('''
            INSERT INTO files (user_id, filename, original_filename, file_path, file_size, file_type, is_folder, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (child['user_id'], child['filename'], child['original_filename'], new_path, child['file_size'],
              child['file_type'], child['is_folder'], new_parent_id))
        new_child_id = cursor.lastrowid
        if child['is_folder']:
            copy_children_db(conn, child['id'], new_child_id, new_path)


@files_bp.route('/file_action', methods=['POST'])
@login_required
def file_action():
    action = request.form.get('action')
    target_id = request.form.get('target_id')
    file_ids = request.form.getlist('file_ids')

    if not file_ids:
        flash('Файлы не выбраны', 'error')
        return redirect(request.referrer)

    target_id = int(target_id) if target_id and target_id != 'root' else None

    conn = get_db()
    target_path_disk = str(session['user_id'])
    if target_id:
        target_folder = conn.execute('SELECT file_path FROM files WHERE id = ?', (target_id,)).fetchone()
        if target_folder:
            target_path_disk = target_folder['file_path']
        else:
            target_id = None

    base_abs_path = Config.UPLOAD_FOLDER
    count = 0

    for file_id in file_ids:
        file = conn.execute('SELECT * FROM files WHERE id = ? AND user_id = ?',
                            (file_id, session['user_id'])).fetchone()
        if not file: continue

        if file['is_folder'] and target_id:
            if file['id'] == target_id: continue

        old_abs_path = os.path.join(base_abs_path, file['file_path'])
        new_filename = file['filename']
        if action == 'copy':
            new_filename = f"{uuid.uuid4()}_{file['original_filename']}"

        new_rel_path = os.path.join(target_path_disk, new_filename)
        new_abs_path = os.path.join(base_abs_path, new_rel_path)

        try:
            if action == 'move':
                shutil.move(old_abs_path, new_abs_path)
                conn.execute('UPDATE files SET parent_id = ?, file_path = ? WHERE id = ?',
                             (target_id, new_rel_path, file_id))
                if file['is_folder']:
                    update_children_paths(conn, file_id, new_rel_path)

            elif action == 'copy':
                if file['is_folder']:
                    shutil.copytree(old_abs_path, new_abs_path)
                else:
                    shutil.copy2(old_abs_path, new_abs_path)

                cursor = conn.execute('''
                    INSERT INTO files (user_id, filename, original_filename, file_path, file_size, file_type, is_folder, parent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (session['user_id'], new_filename, file['original_filename'], new_rel_path, file['file_size'],
                      file['file_type'], file['is_folder'], target_id))
                new_id = cursor.lastrowid

                if file['is_folder']:
                    copy_children_db(conn, file['id'], new_id, new_rel_path)

            count += 1
        except Exception as e:
            print(f"Error {action} file {file_id}: {e}")
            continue

    conn.commit()
    conn.close()
    update_user_storage(session['user_id'])

    flash(f'Действие выполнено: {count} файл(ов)', 'success')
    return redirect(request.referrer)

@files_bp.route('/search')
@login_required
def search_files():
    q = request.args.get('q', '').strip()
    ftype = request.args.get('type', 'all')
    include_trash = request.args.get('include_trash') == '1'

    conn = get_db()

    sql = '''
        SELECT *
        FROM files
        WHERE user_id = ?
    '''
    params = [session['user_id']]

    # Фильтр по тексту – только если что-то ввели
    if q:
        sql += ' AND (original_filename LIKE ? OR filename LIKE ?)'
        like = f'%{q}%'
        params.extend([like, like])

    # Фильтр по типу – если выбран не "Все"
    if ftype != 'all':
        sql += ' AND file_type = ?'
        params.append(ftype)

    # Фильтр по корзине
    if not include_trash:
        sql += ' AND is_deleted = 0'

    sql += ' ORDER BY is_folder DESC, original_filename'

    files = conn.execute(sql, params).fetchall()
    conn.close()

    return render_template(
        'files/search.html',
        files=files,
        q=q,
        ftype=ftype,
        include_trash=include_trash,
        format_size=format_size,
    )

