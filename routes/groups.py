from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
import os
import uuid
import sqlite3
import shutil
import random
import string
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from utils import get_db, login_required, safe_filename, format_size, get_file_type, get_group_storage_info

groups_bp = Blueprint('groups', __name__)


def is_group_member(group_id, user_id):
    conn = get_db()
    member = conn.execute('SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?',
                          (group_id, user_id)).fetchone()
    conn.close()
    return member is not None


def generate_pincode(length=6):
    return ''.join(random.choices(string.digits, k=length))


def bulk_group_action_internal(action, file_ids):
    if not file_ids: return redirect(request.referrer)
    conn = get_db()
    count = 0
    for file_id in file_ids:
        file = conn.execute('SELECT * FROM group_files WHERE id = ?', (file_id,)).fetchone()
        if not file or not is_group_member(file['group_id'], session['user_id']): continue

        if action == 'trash':
            conn.execute('UPDATE group_files SET is_deleted = 1, deleted_at = CURRENT_TIMESTAMP WHERE id = ?',
                         (file_id,))
            count += 1
        elif action == 'delete_permanent':
            full_path = os.path.join(Config.UPLOAD_FOLDER, file['file_path'])
            if os.path.exists(full_path):
                if file['is_folder']:
                    shutil.rmtree(full_path, ignore_errors=True)
                else:
                    os.remove(full_path)

            if file['is_folder']:
                def delete_db_recursive(folder_id):
                    child_items = conn.execute('SELECT id, is_folder FROM group_files WHERE parent_id = ?',
                                               (folder_id,)).fetchall()
                    for child in child_items:
                        if child['is_folder']: delete_db_recursive(child['id'])
                    conn.execute('DELETE FROM group_files WHERE parent_id = ?', (folder_id,))

                delete_db_recursive(file_id)

            conn.execute('DELETE FROM group_files WHERE id = ?', (file_id,))
            count += 1

    conn.commit()
    conn.close()
    msg = "Перемещено в корзину" if action == 'trash' else "Удалено навсегда"
    flash(f'{msg}: {count} файл(ов)', 'success')
    return redirect(request.referrer)


@groups_bp.route('/groups')
@login_required
def list_groups():
    conn = get_db()
    groups = conn.execute(
        '''SELECT g.id, g.name, g.owner_id, u.username as owner_name, (SELECT COUNT(*) FROM group_members gm WHERE gm.group_id = g.id) as member_count FROM groups g JOIN users u ON g.owner_id = u.id JOIN group_members gm ON g.id = gm.group_id WHERE gm.user_id = ? ORDER BY g.name''',
        (session['user_id'],)).fetchall()
    conn.close()
    return render_template('groups/list.html', groups=groups)


@groups_bp.route('/groups/create', methods=['GET', 'POST'])
@login_required
def create_group():
    if request.method == 'POST':
        group_name = request.form.get('group_name', '').strip()
        try:
            storage_limit_gb = int(request.form.get('storage_limit', 1))
        except (ValueError, TypeError):
            storage_limit_gb = 1
        storage_limit_bytes = storage_limit_gb * 1024 * 1024 * 1024

        if not group_name:
            flash('Название группы не может быть пустым.', 'error')
            return redirect(url_for('groups.create_group'))

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO groups (name, owner_id, storage_limit) VALUES (?, ?, ?)',
                       (group_name, session['user_id'], storage_limit_bytes))
        group_id = cursor.lastrowid
        cursor.execute('INSERT OR IGNORE INTO group_members (group_id, user_id) VALUES (?, ?)',
                       (group_id, session['user_id']))
        conn.commit()
        conn.close()
        os.makedirs(os.path.join(Config.UPLOAD_FOLDER, 'group_uploads', str(group_id)), exist_ok=True)
        flash(f'Группа "{group_name}" создана (Лимит: {storage_limit_gb} ГБ)!', 'success')
        return redirect(url_for('groups.view_group', group_id=group_id))
    return render_template('groups/create.html')


@groups_bp.route('/groups/<int:group_id>')
@groups_bp.route('/groups/<int:group_id>/folder/<int:folder_id>')
@login_required
def view_group(group_id, folder_id=None):
    if not is_group_member(group_id, session['user_id']):
        flash('Вы не являетесь участником этой группы.', 'error')
        return redirect(url_for('groups.list_groups'))

    conn = get_db()
    group = conn.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    query = 'SELECT gf.*, u.username as uploader_name FROM group_files gf JOIN users u ON gf.uploader_id = u.id WHERE gf.group_id = ? AND gf.is_deleted = 0 AND {} ORDER BY gf.is_folder DESC, gf.original_filename'
    params = (group_id,)
    if folder_id:
        query, params = query.format("gf.parent_id = ?"), params + (folder_id,)
        current_folder = conn.execute('SELECT * FROM group_files WHERE id = ?', (folder_id,)).fetchone()
    else:
        query, current_folder = query.format("gf.parent_id IS NULL"), None

    files = conn.execute(query, params).fetchall()
    members = conn.execute(
        'SELECT u.id, u.username FROM users u JOIN group_members gm ON u.id = gm.user_id WHERE gm.group_id = ?',
        (group_id,)).fetchall()
    conn.close()

    invite_link = url_for('groups.join_via_link', token=group['invite_token'], _external=True) if group and group[
        'invite_token'] else None
    storage_info = get_group_storage_info(group_id)

    return render_template('groups/view.html', group=group, files=files, members=members, current_folder=current_folder,
                           format_size=format_size, invite_link=invite_link, storage_info=storage_info)


@groups_bp.route('/groups/<int:group_id>/invite', methods=['POST'])
@login_required
def manage_invite_link(group_id):
    if not is_group_member(group_id, session['user_id']): return jsonify({'error': 'Нет прав'}), 403
    conn = get_db()
    new_token, new_pincode = str(uuid.uuid4()), generate_pincode()
    pincode_hash = generate_password_hash(new_pincode)
    conn.execute('UPDATE groups SET invite_token = ?, pincode_hash = ? WHERE id = ?',
                 (new_token, pincode_hash, group_id))
    conn.commit()
    conn.close()
    invite_link = url_for('groups.join_via_link', token=new_token, _external=True)
    return jsonify({'success': True, 'invite_link': invite_link, 'pincode': new_pincode})


@groups_bp.route('/join/<token>', methods=['GET', 'POST'])
def join_via_link(token):
    if 'user_id' not in session:
        session['pending_invite_token'] = token
        flash('Войдите, чтобы принять приглашение.', 'info')
        return redirect(url_for('auth.login'))
    conn = get_db()
    group = conn.execute('SELECT * FROM groups WHERE invite_token = ?', (token,)).fetchone()
    if not group:
        flash('Ссылка недействительна.', 'error')
        conn.close()
        session.pop('pending_invite_token', None)
        return redirect(url_for('groups.list_groups'))
    if is_group_member(group['id'], session['user_id']):
        flash(f'Вы уже в группе "{group["name"]}".', 'info')
        conn.close()
        session.pop('pending_invite_token', None)
        return redirect(url_for('groups.view_group', group_id=group['id']))
    if request.args.get('action') == 'decline':
        session.pop('pending_invite_token', None)
        conn.close()
        flash('Приглашение отклонено.', 'info')
        return redirect(url_for('files.dashboard'))
    if request.method == 'POST':
        if not check_password_hash(group['pincode_hash'], request.form.get('pincode', '')):
            flash('Неверный пин-код.', 'error')
            return render_template('groups/join.html', group=group)
        try:
            conn.execute('INSERT OR IGNORE INTO group_members (group_id, user_id) VALUES (?, ?)',
                         (group['id'], session['user_id']))
            conn.commit()
            flash(f'Вы в группе "{group["name"]}"!', 'success')
            session.pop('pending_invite_token', None)
            return redirect(url_for('groups.view_group', group_id=group['id']))
        except sqlite3.IntegrityError:
            return redirect(url_for('groups.view_group', group_id=group['id']))
        finally:
            conn.close()
    conn.close()
    return render_template('groups/join.html', group=group)


@groups_bp.route('/groups/<int:group_id>/members', methods=['POST'])
@login_required
def manage_members(group_id):
    user_id = session['user_id']
    conn = get_db()
    group = conn.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not group or group['owner_id'] != user_id:
        flash('Только владелец может удалять.', 'error')
        conn.close()
        return redirect(url_for('groups.view_group', group_id=group_id))
    user_id_to_remove = request.form.get('user_id')
    if user_id_to_remove and int(user_id_to_remove) != group['owner_id']:
        conn.execute('DELETE FROM group_members WHERE group_id = ? AND user_id = ?', (group_id, user_id_to_remove))
        conn.commit()
        flash('Участник удален.', 'success')
    conn.close()
    return redirect(url_for('groups.view_group', group_id=group_id))


@groups_bp.route('/groups/<int:group_id>/upload', methods=['POST'])
@login_required
def upload_group_file(group_id):
    if not is_group_member(group_id, session['user_id']): return flash('Доступ запрещен.', 'error'), 403
    parent_id = request.form.get('parent_id') or None
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        flash('Файлы не выбраны.', 'error')
        return redirect(url_for('groups.view_group', group_id=group_id, folder_id=parent_id))

    storage_info = get_group_storage_info(group_id)
    if storage_info['used'] >= storage_info['limit']:
        flash('Лимит группы превышен!', 'error')
        return redirect(url_for('groups.view_group', group_id=group_id, folder_id=parent_id))

    conn = get_db()
    group_base_path = os.path.join('group_uploads', str(group_id))
    upload_path = group_base_path
    if parent_id:
        parent = conn.execute('SELECT file_path FROM group_files WHERE id = ?', (parent_id,)).fetchone()
        if parent: upload_path = parent['file_path']

    current_used = storage_info['used']
    limit = storage_info['limit']
    for file in files:
        file.seek(0, 2);
        size = file.tell();
        file.seek(0)
        if current_used + size > limit:
            flash(f'Файл {file.filename} не помещается', 'error')
            continue
        original = safe_filename(file.filename)
        unique = f"{uuid.uuid4()}_{original}"
        path = os.path.join(upload_path, unique)
        full = os.path.join(Config.UPLOAD_FOLDER, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        file.save(full)
        conn.execute(
            'INSERT INTO group_files (group_id, uploader_id, filename, original_filename, file_path, file_size, file_type, parent_id) VALUES (?,?,?,?,?,?,?,?)',
            (group_id, session['user_id'], unique, original, path, size, get_file_type(original), parent_id))
        current_used += size
    conn.commit()
    conn.close()
    flash('Загружено.', 'success')
    return redirect(url_for('groups.view_group', group_id=group_id, folder_id=parent_id))


@groups_bp.route('/groups/delete_file/<int:file_id>', methods=['POST'])
@login_required
def delete_group_file(file_id):
    return bulk_group_action_internal('trash', [file_id])


@groups_bp.route('/groups/action', methods=['POST'])
@login_required
def bulk_group_action():
    group_id = request.form.get('group_id')
    action = request.form.get('action')
    file_ids = request.form.getlist('file_ids')
    if group_id and not is_group_member(group_id, session['user_id']): return redirect(url_for('groups.list_groups'))
    return bulk_group_action_internal(action, file_ids)


@groups_bp.route('/groups/<int:group_id>/leave', methods=['POST'])
@login_required
def leave_group(group_id):
    user_id = session['user_id']
    conn = get_db()
    group = conn.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    if group and group['owner_id'] != user_id:
        conn.execute('DELETE FROM group_members WHERE group_id = ? AND user_id = ?', (group_id, user_id))
        conn.commit()
        flash(f'Вы покинули группу.', 'info')
    conn.close()
    return redirect(url_for('groups.list_groups'))


@groups_bp.route('/groups/<int:group_id>/delete', methods=['POST'])
@login_required
def delete_group(group_id):
    user_id = session['user_id']
    conn = get_db()
    group = conn.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    if group and group['owner_id'] == user_id:
        path = os.path.join(Config.UPLOAD_FOLDER, 'group_uploads', str(group_id))
        if os.path.exists(path): shutil.rmtree(path)
        conn.execute('DELETE FROM groups WHERE id = ?', (group_id,))
        conn.commit()
        flash(f'Группа удалена.', 'success')
    conn.close()
    return redirect(url_for('groups.list_groups'))


@groups_bp.route('/groups/<int:group_id>/create_folder', methods=['POST'])
@login_required
def create_group_folder(group_id):
    if not is_group_member(group_id, session['user_id']): return redirect(url_for('groups.list_groups'))
    folder_name = request.form.get('folder_name', '').strip()
    parent_id = request.form.get('parent_id')
    parent_id = int(parent_id) if parent_id else None
    if not folder_name: return redirect(url_for('groups.view_group', group_id=group_id, folder_id=parent_id))

    folder_name = safe_filename(folder_name)
    conn = get_db()
    path = os.path.join('group_uploads', str(group_id))
    if parent_id:
        p = conn.execute('SELECT file_path FROM group_files WHERE id=?', (parent_id,)).fetchone()
        if p: path = p['file_path']

    rel = os.path.join(path, f"{uuid.uuid4()}_{folder_name}")
    os.makedirs(os.path.join(Config.UPLOAD_FOLDER, rel), exist_ok=True)
    conn.execute(
        'INSERT INTO group_files (group_id, uploader_id, filename, original_filename, file_path, is_folder, parent_id) VALUES (?,?,?,?,?,1,?)',
        (group_id, session['user_id'], f"{uuid.uuid4()}_{folder_name}", folder_name, rel, parent_id))
    conn.commit()
    conn.close()
    return redirect(url_for('groups.view_group', group_id=group_id, folder_id=parent_id))


@groups_bp.route('/groups/<int:group_id>/get_folders', methods=['GET'])
@login_required
def get_group_folders_tree(group_id):
    if not is_group_member(group_id, session['user_id']): return jsonify([])
    conn = get_db()
    folders = conn.execute(
        'SELECT id, original_filename, parent_id FROM group_files WHERE group_id=? AND is_folder=1 AND is_deleted=0 ORDER BY original_filename',
        (group_id,)).fetchall()
    conn.close()
    return jsonify([{'id': f['id'], 'name': f['original_filename'], 'parent_id': f['parent_id']} for f in folders])


@groups_bp.route('/groups/<int:group_id>/file_action', methods=['POST'])
@login_required
def group_file_action(group_id):
    if not is_group_member(group_id, session['user_id']): return redirect(url_for('groups.list_groups'))
    action = request.form.get('action')
    target_id = request.form.get('target_id')
    file_ids = request.form.getlist('file_ids')
    if not file_ids: return redirect(request.referrer)

    target_id = int(target_id) if target_id and target_id != 'root' else None
    conn = get_db()
    target_path = os.path.join('group_uploads', str(group_id))
    if target_id:
        t = conn.execute('SELECT file_path FROM group_files WHERE id=?', (target_id,)).fetchone()
        if t:
            target_path = t['file_path']
        else:
            target_id = None

    for fid in file_ids:
        f = conn.execute('SELECT * FROM group_files WHERE id=? AND group_id=?', (fid, group_id)).fetchone()
        if not f: continue
        old = os.path.join(Config.UPLOAD_FOLDER, f['file_path'])
        new_n = f"{uuid.uuid4()}_{f['original_filename']}" if action == 'copy' else f['filename']
        new_r = os.path.join(target_path, new_n)
        new_a = os.path.join(Config.UPLOAD_FOLDER, new_r)

        try:
            if action == 'move':
                shutil.move(old, new_a)
                conn.execute('UPDATE group_files SET parent_id=?, file_path=? WHERE id=?', (target_id, new_r, fid))
            elif action == 'copy':
                if f['is_folder']:
                    shutil.copytree(old, new_a)
                else:
                    shutil.copy2(old, new_a)
                conn.execute(
                    'INSERT INTO group_files (group_id, uploader_id, filename, original_filename, file_path, file_size, file_type, is_folder, parent_id) VALUES (?,?,?,?,?,?,?,?,?)',
                    (group_id, session['user_id'], new_n, f['original_filename'], new_r, f['file_size'], f['file_type'],
                     f['is_folder'], target_id))
        except:
            pass
    conn.commit()
    conn.close()
    return redirect(request.referrer)


# Корзина группы
@groups_bp.route('/groups/<int:group_id>/trash')
@login_required
def group_trash(group_id):
    if not is_group_member(group_id, session['user_id']): return redirect(url_for('groups.list_groups'))
    conn = get_db()
    group = conn.execute('SELECT * FROM groups WHERE id=?', (group_id,)).fetchone()
    files = conn.execute(
        'SELECT gf.*, u.username as uploader_name FROM group_files gf JOIN users u ON gf.uploader_id=u.id WHERE gf.group_id=? AND gf.is_deleted=1 ORDER BY gf.deleted_at DESC',
        (group_id,)).fetchall()
    storage_info = get_group_storage_info(group_id)
    conn.close()
    return render_template('groups/trash.html', group=group, files=files, storage_info=storage_info,
                           format_size=format_size)


@groups_bp.route('/groups/<int:group_id>/restore_file/<int:file_id>', methods=['POST'])
@login_required
def restore_group_file(group_id, file_id):
    if not is_group_member(group_id, session['user_id']): return redirect(url_for('groups.list_groups'))
    conn = get_db()
    conn.execute('UPDATE group_files SET is_deleted=0, deleted_at=NULL WHERE id=?', (file_id,))
    conn.commit()
    conn.close()
    flash('Восстановлено.', 'success')
    return redirect(url_for('groups.group_trash', group_id=group_id))


@groups_bp.route('/groups/<int:group_id>/empty_trash', methods=['POST'])
@login_required
def empty_group_trash(group_id):
    if not is_group_member(group_id, session['user_id']): return redirect(url_for('groups.list_groups'))
    conn = get_db()
    files = conn.execute('SELECT * FROM group_files WHERE group_id=? AND is_deleted=1', (group_id,)).fetchall()
    for f in files:
        path = os.path.join(Config.UPLOAD_FOLDER, f['file_path'])
        if os.path.exists(path):
            if f['is_folder']:
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
    conn.execute('DELETE FROM group_files WHERE group_id=? AND is_deleted=1', (group_id,))
    conn.commit()
    conn.close()
    flash('Очищено.', 'success')
    return redirect(url_for('groups.group_trash', group_id=group_id))


@groups_bp.route('/groups/<int:group_id>/delete_forever/<int:file_id>', methods=['POST'])
@login_required
def delete_group_file_forever(group_id, file_id):
    conn = get_db()
    f = conn.execute('SELECT * FROM group_files WHERE id=?', (file_id,)).fetchone()
    if f:
        path = os.path.join(Config.UPLOAD_FOLDER, f['file_path'])
        if os.path.exists(path):
            if f['is_folder']:
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
        conn.execute('DELETE FROM group_files WHERE id=?', (file_id,))
    conn.commit()
    conn.close()
    flash('Удалено.', 'success')
    return redirect(url_for('groups.group_trash', group_id=group_id))