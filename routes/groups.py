from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, send_file, abort
import os
import uuid
import sqlite3
import shutil
import random
import string
import zipfile
import io
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from utils import get_db, login_required, safe_filename, format_size, get_file_type, get_group_storage_info

groups_bp = Blueprint('groups', __name__)

def is_group_owner(group_id, user_id):
    conn = get_db()
    row = conn.execute(
        'SELECT owner_id FROM groups WHERE id = ?',
        (group_id,)
    ).fetchone()
    conn.close()
    return row and row['owner_id'] == user_id

def is_group_member(group_id, user_id):
    conn = get_db()
    member = conn.execute('SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?',
                          (group_id, user_id)).fetchone()
    conn.close()
    return member is not None


def generate_pincode(length=6):
    return ''.join(random.choices(string.digits, k=length))


@groups_bp.route('/groups/<int:group_id>/download/<int:file_id>')
@login_required
def download_group_file(group_id, file_id):
    # Проверяем, что пользователь в группе
    if not is_group_member(group_id, session['user_id']):
        flash('Доступ запрещен.', 'error')
        return redirect(url_for('groups.list_groups'))

    conn = get_db()
    file = conn.execute(
        'SELECT * FROM group_files WHERE id = ? AND group_id = ?',
        (file_id, group_id)
    ).fetchone()
    conn.close()

    if not file:
        flash('Файл не найден.', 'error')
        return redirect(url_for('groups.view_group', group_id=group_id))

    full_path = os.path.join(Config.UPLOAD_FOLDER, file['file_path'])

    # Если это папка — отдать zip-архив
    if file['is_folder']:
        if not os.path.exists(full_path):
            flash('Папка не найдена на диске.', 'error')
            return redirect(url_for('groups.view_group', group_id=group_id))

        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files_in_folder in os.walk(full_path):
                for f in files_in_folder:
                    file_path_in_folder = os.path.join(root, f)
                    arcname = os.path.relpath(file_path_in_folder, full_path)
                    zf.write(file_path_in_folder, arcname)

        memory_file.seek(0)
        return send_file(
            memory_file,
            as_attachment=True,
            download_name=f"{file['original_filename']}.zip",
            mimetype='application/zip'
        )

    # Обычный файл
    if os.path.exists(full_path):
        return send_file(
            full_path,
            as_attachment=True,
            download_name=file['original_filename']
        )
    else:
        flash('Файл не найден на диске.', 'error')
        return redirect(url_for('groups.view_group', group_id=group_id))


@groups_bp.route('/groups/<int:group_id>/preview/<int:file_id>')
@login_required
def preview_group_file(group_id, file_id):
    if not is_group_member(group_id, session['user_id']):
        flash('Доступ запрещен.', 'error')
        return redirect(url_for('groups.list_groups'))

    conn = get_db()
    file = conn.execute(
        'SELECT * FROM group_files WHERE id = ? AND group_id = ?',
        (file_id, group_id)
    ).fetchone()
    conn.close()

    if not file or file['is_folder']:
        abort(404)

    if file['file_type'] != 'image':
        abort(404)

    full_path = os.path.join(Config.UPLOAD_FOLDER, file['file_path'])
    if not os.path.exists(full_path):
        abort(404)

    return send_file(full_path)



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

@groups_bp.route('/groups/<int:group_id>/bulk_download', methods=['POST'])
@login_required
def bulk_group_download(group_id):
    if not is_group_member(group_id, session['user_id']):
        flash('Доступ запрещен.', 'error')
        return redirect(url_for('groups.list_groups'))

    file_ids = request.form.getlist('file_ids')
    if not file_ids:
        flash('Файлы не выбраны.', 'error')
        return redirect(request.referrer or url_for('groups.view_group', group_id=group_id))

    conn = get_db()
    placeholders = ','.join('?' * len(file_ids))
    files = conn.execute(
        f'''
        SELECT * FROM group_files
        WHERE group_id = ? AND id IN ({placeholders}) AND is_deleted = 0
        ''',
        [group_id, *file_ids]
    ).fetchall()
    conn.close()

    if not files:
        flash('Файлы не найдены.', 'error')
        return redirect(request.referrer or url_for('groups.view_group', group_id=group_id))

    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if f['is_folder']:
                folder_path = os.path.join(Config.UPLOAD_FOLDER, f['file_path'])
                if not os.path.exists(folder_path):
                    continue
                for root, dirs, filenames in os.walk(folder_path):
                    for name in filenames:
                        full_path = os.path.join(root, name)
                        arcname = os.path.join(
                            f['original_filename'],
                            os.path.relpath(full_path, folder_path)
                        )
                        zf.write(full_path, arcname)
            else:
                full_path = os.path.join(Config.UPLOAD_FOLDER, f['file_path'])
                if os.path.exists(full_path):
                    zf.write(full_path, f['original_filename'])

    memory_file.seek(0)
    return send_file(
        memory_file,
        as_attachment=True,
        download_name=f'group_{group_id}_files.zip',
        mimetype='application/zip'
    )

@groups_bp.route('/groups')
@login_required
def list_groups():
    conn = get_db()
    groups = conn.execute(
        '''
        SELECT g.*, u.username AS owner_name,
               (SELECT COUNT(*) FROM group_members gm WHERE gm.group_id = g.id) AS member_count
        FROM groups g
        JOIN users u ON u.id = g.owner_id
        WHERE EXISTS (
            SELECT 1 FROM group_members gm
            WHERE gm.group_id = g.id AND gm.user_id = ?
        )
        ORDER BY g.created_at DESC
        ''',
        (session['user_id'],)
    ).fetchall()

    invites = conn.execute(
        '''
        SELECT gi.*, g.name AS group_name
        FROM group_invites gi
        JOIN groups g ON gi.group_id = g.id
        WHERE g.owner_id = ?
        ORDER BY gi.id DESC
        ''',
        (session['user_id'],)
    ).fetchall()
    conn.close()

    return render_template('groups/list.html', groups=groups, invites=invites)



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

    query = '''
        SELECT gf.*, u.username as uploader_name
        FROM group_files gf
        JOIN users u ON gf.uploader_id = u.id
        WHERE gf.group_id = ? AND gf.is_deleted = 0 AND {}
        ORDER BY gf.is_folder DESC, gf.original_filename
    '''
    params = (group_id,)

    if folder_id:
        query, params = query.format("gf.parent_id = ?"), params + (folder_id,)
        current_folder = conn.execute('SELECT * FROM group_files WHERE id = ?', (folder_id,)).fetchone()
    else:
        query, current_folder = query.format("gf.parent_id IS NULL"), None

    files = conn.execute(query, params).fetchall()
    members = conn.execute(
        'SELECT u.id, u.username FROM users u JOIN group_members gm ON u.id = gm.user_id WHERE gm.group_id = ?',
        (group_id,)
    ).fetchall()

    # НОВОЕ: выбираем инвайты этой группы
    invites = conn.execute(
        '''
        SELECT id, token, uses, max_uses, expires_at, is_active, pincode_hash
        FROM group_invites
        WHERE group_id = ? AND is_active = 1
        ORDER BY id DESC
        ''',
        (group_id,)
    ).fetchall()

    conn.close()

    storage_info = get_group_storage_info(group_id)

    return render_template(
        'groups/view.html',
        group=group,
        files=files,
        members=members,
        current_folder=current_folder,
        format_size=format_size,
        storage_info=storage_info,
        invites=invites  # <‑‑ добавили
    )



@groups_bp.route('/groups/<int:group_id>/invite', methods=['POST'])
@login_required
def manage_invite_link(group_id):
    if not is_group_member(group_id, session['user_id']):
        return jsonify({'error': 'Нет прав'}), 403

    raw_pin = request.form.get('pincode', '').strip()
    no_pin = request.form.get('no_pin') == '1'

    # срок действия
    raw_days = request.form.get('expires_in', '7')
    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        days = 7

    if days <= 0:
        expires_at = None
    else:
        expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat(timespec='seconds')

    # PIN
    if no_pin or not raw_pin:
        pincode_hash = None
    else:
        if not raw_pin.isdigit() or not (4 <= len(raw_pin) <= 8):
            return jsonify({'error': 'ПИН должен быть от 4 до 8 цифр'}), 400
        pincode_hash = generate_password_hash(raw_pin)

    max_uses = None
    token = str(uuid.uuid4())

    conn = get_db()
    conn.execute(
        '''
        INSERT INTO group_invites
            (group_id, token, pincode_hash, expires_at, max_uses, uses, is_active, created_by)
        VALUES (?, ?, ?, ?, ?, 0, 1, ?)
        ''',
        (group_id, token, pincode_hash, expires_at, max_uses, session['user_id'])
    )
    conn.commit()
    conn.close()

    invite_link = url_for('groups.join_via_link', token=token, _external=True)

    resp = {'success': True, 'invite_link': invite_link}
    if pincode_hash is not None:
        resp['pincode'] = raw_pin

    return jsonify(resp)

@groups_bp.route('/groups/invites/manage')
@login_required
def manage_all_invites():
    conn = get_db()
    invites = conn.execute(
        '''
        SELECT gi.*, g.name AS group_name
        FROM group_invites gi
        JOIN groups g ON gi.group_id = g.id
        WHERE g.owner_id = ?
        ORDER BY gi.created_at DESC
        ''',
        (session['user_id'],)
    ).fetchall()
    conn.close()
    return render_template('groups/invites_manage.html', invites=invites)


@groups_bp.route('/groups/<int:group_id>/invites/deactivate_all', methods=['POST'])
@login_required
def deactivate_all_invites(group_id):
    if not is_group_owner(group_id, session['user_id']):
        flash('Только владелец группы может отключать приглашения.', 'error')
        return redirect(url_for('groups.view_group', group_id=group_id))

    conn = get_db()
    conn.execute(
        'UPDATE group_invites SET is_active = 0 WHERE group_id = ? AND is_active = 1',
        (group_id,)
    )
    conn.commit()
    conn.close()
    flash('Все активные ссылки отключены.', 'success')
    return redirect(url_for('groups.view_group', group_id=group_id))


@groups_bp.route('/join/<token>', methods=['GET', 'POST'])
def join_via_link(token):
    if 'user_id' not in session:
        session['pending_invite_token'] = token
        flash('Войдите, чтобы принять приглашение.', 'info')
        return redirect(url_for('auth.login'))

    conn = get_db()
    invite = conn.execute(
        '''
        SELECT gi.*, g.name AS group_name
        FROM group_invites gi
        JOIN groups g ON gi.group_id = g.id
        WHERE gi.token = ?
        ''',
        (token,)
    ).fetchone()

    if not invite:
        flash('Ссылка недействительна.', 'error')
        conn.close()
        session.pop('pending_invite_token', None)
        return redirect(url_for('groups.list_groups'))

    if invite['is_active'] != 1:
        flash('Приглашение отключено.', 'error')
        conn.close()
        session.pop('pending_invite_token', None)
        return redirect(url_for('groups.list_groups'))

    if invite['expires_at']:
        try:
            expires = datetime.fromisoformat(invite['expires_at'])
            if datetime.utcnow() > expires:
                flash('Приглашение истекло.', 'error')
                conn.close()
                session.pop('pending_invite_token', None)
                return redirect(url_for('groups.list_groups'))
        except ValueError:
            pass

    if invite['max_uses'] is not None and invite['uses'] >= invite['max_uses']:
        flash('Лимит использований приглашения исчерпан.', 'error')
        conn.close()
        session.pop('pending_invite_token', None)
        return redirect(url_for('groups.list_groups'))

    group_id = invite['group_id']

    if is_group_member(group_id, session['user_id']):
        flash(f'Вы уже в группе "{invite["group_name"]}".', 'info')
        conn.close()
        session.pop('pending_invite_token', None)
        return redirect(url_for('groups.view_group', group_id=group_id))

    if request.args.get('action') == 'decline':
        session.pop('pending_invite_token', None)
        conn.close()
        flash('Приглашение отклонено.', 'info')
        return redirect(url_for('files.dashboard'))

    # === PIN-код ===
    if invite['pincode_hash']:
        if request.method == 'GET':
            # показать форму с полем PIN
            conn.close()
            return render_template('groups/join.html', group=invite)

        # POST: проверяем PIN
        pin = request.form.get('pincode', '').strip()
        if not pin:
            flash('Введите ПИН-код.', 'error')
            conn.close()
            return render_template('groups/join.html', group=invite)

        if not check_password_hash(invite['pincode_hash'], pin):
            flash('Неверный ПИН-код.', 'error')
            conn.close()
            return render_template('groups/join.html', group=invite)
    else:
        # без PIN: GET просто показывает форму
        if request.method == 'GET':
            conn.close()
            return render_template('groups/join.html', group=invite)

    # === сюда дойдём только если PIN не нужен или он верный ===
    if request.method == 'POST':
        try:
            conn.execute(
                'INSERT OR IGNORE INTO group_members (group_id, user_id) VALUES (?, ?)',
                (group_id, session['user_id'])
            )
            conn.execute(
                'UPDATE group_invites SET uses = uses + 1 WHERE id = ?',
                (invite['id'],)
            )
            conn.commit()
            flash(f'Вы в группе "{invite["group_name"]}"!', 'success')
            session.pop('pending_invite_token', None)
            return redirect(url_for('groups.view_group', group_id=group_id))
        except sqlite3.IntegrityError:
            return redirect(url_for('groups.view_group', group_id=group_id))
        finally:
            conn.close()
    else:
        # на всякий случай
        conn.close()
        return render_template('groups/join.html', group=invite)

@groups_bp.route('/groups/<int:group_id>/invites/<int:invite_id>/deactivate', methods=['POST'])
@login_required
def deactivate_invite(group_id, invite_id):
    # только владелец группы может отключать инвайты
    conn = get_db()
    group = conn.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    if not group:
        conn.close()
        flash('Группа не найдена.', 'error')
        return redirect(url_for('groups.list_groups'))

    if group['owner_id'] != session['user_id']:
        conn.close()
        flash('Только владелец может управлять приглашениями.', 'error')
        return redirect(url_for('groups.view_group', group_id=group_id))

    # убеждаемся, что инвайт принадлежит этой группе
    invite = conn.execute(
        'SELECT * FROM group_invites WHERE id = ? AND group_id = ?',
        (invite_id, group_id)
    ).fetchone()
    if not invite:
        conn.close()
        flash('Приглашение не найдено.', 'error')
        return redirect(url_for('groups.view_group', group_id=group_id))

    conn.execute(
        'UPDATE group_invites SET is_active = 0 WHERE id = ?',
        (invite_id,)
    )
    conn.commit()
    conn.close()

    flash('Ссылка приглашения отключена.', 'info')
    return redirect(url_for('groups.view_group', group_id=group_id))



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

@groups_bp.route('/groups/<int:group_id>/rename/<int:file_id>', methods=['POST'])
@login_required
def rename_group_file(group_id, file_id):
    new_name = request.form.get('new_name', '').strip()

    if not new_name:
        flash('Введите новое имя', 'error')
        return redirect(request.referrer or url_for('groups.view_group', group_id=group_id))

    new_name = safe_filename(new_name)

    conn = get_db()
    # проверка, что пользователь участник группы
    if not is_group_member(group_id, session['user_id']):
        conn.close()
        flash('Доступ запрещён', 'error')
        return redirect(url_for('groups.list_groups'))

    file = conn.execute(
        'SELECT * FROM group_files WHERE id = ? AND group_id = ?',
        (file_id, group_id)
    ).fetchone()

    if not file:
        conn.close()
        flash('Файл не найден', 'error')
        return redirect(url_for('groups.view_group', group_id=group_id))

    conn.execute(
        'UPDATE group_files SET original_filename = ? WHERE id = ?',
        (new_name, file_id)
    )
    conn.commit()
    conn.close()

    flash('Файл переименован', 'success')
    return redirect(request.referrer or url_for('groups.view_group', group_id=group_id))

@groups_bp.route('/groups/<int:group_id>/search')
@login_required
def search_group_files(group_id):
    if not is_group_member(group_id, session['user_id']):
        flash('Вы не являетесь участником этой группы.', 'error')
        return redirect(url_for('groups.list_groups'))

    q = request.args.get('q', '').strip()
    ftype = request.args.get('type', 'all')
    include_trash = request.args.get('include_trash') == '1'

    conn = get_db()

    group = conn.execute(
        'SELECT * FROM groups WHERE id = ?',
        (group_id,)
    ).fetchone()

    sql = '''
        SELECT gf.*, u.username AS uploader_name
        FROM group_files gf
        JOIN users u ON gf.uploader_id = u.id
        WHERE gf.group_id = ?
    '''
    params = [group_id]

    # фильтр по тексту, только если задан q
    if q:
        sql += ' AND (gf.original_filename LIKE ? OR gf.filename LIKE ?)'
        pattern = f'%{q}%'
        params.extend([pattern, pattern])

    # фильтр по типу
    if ftype != 'all':
        sql += ' AND gf.file_type = ?'
        params.append(ftype)

    # корзина
    if not include_trash:
        sql += ' AND gf.is_deleted = 0'

    sql += ' ORDER BY gf.is_folder DESC, gf.original_filename'

    files = conn.execute(sql, params).fetchall()
    storage_info = get_group_storage_info(group_id)
    conn.close()

    return render_template(
        'groups/search.html',
        group=group,
        files=files,
        q=q,
        ftype=ftype,
        include_trash=include_trash,
        storage_info=storage_info,
        format_size=format_size,
    )

@groups_bp.route('/groups/<int:group_id>/preview_inline/<int:file_id>')
@login_required
def preview_group_inline(group_id, file_id):
    if not is_group_member(group_id, session['user_id']):
        flash('Доступ запрещен.', 'error')
        return redirect(url_for('groups.list_groups'))

    conn = get_db()
    file = conn.execute(
        'SELECT * FROM group_files WHERE id = ? AND group_id = ?',
        (file_id, group_id)
    ).fetchone()
    conn.close()

    if not file or file['is_folder']:
        abort(404)

    full_path = os.path.join(Config.UPLOAD_FOLDER, file['file_path'])
    if not os.path.exists(full_path):
        abort(404)

    # картинки
    if file['file_type'] == 'image':
        return send_file(full_path)

    # pdf
    if file['file_type'] == 'document' and file['original_filename'].lower().endswith('.pdf'):
        return send_file(full_path, mimetype='application/pdf')

    # текст / код
    if file['file_type'] in ('document', 'code'):
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        from flask import Response
        return Response(content, mimetype='text/plain; charset=utf-8')

    abort(415)

@groups_bp.route('/groups/<int:group_id>/edit/<int:file_id>', methods=['POST'])
@login_required
def edit_group_file(group_id, file_id):
    if not is_group_member(group_id, session['user_id']):
        return jsonify({'error': 'forbidden'}), 403

    new_content = request.form.get('content', '')

    conn = get_db()
    file = conn.execute(
        'SELECT * FROM group_files WHERE id = ? AND group_id = ?',
        (file_id, group_id)
    ).fetchone()

    if not file or file['is_folder']:
        conn.close()
        abort(404)

    full_path = os.path.join(Config.UPLOAD_FOLDER, file['file_path'])
    if not os.path.exists(full_path):
        conn.close()
        abort(404)

    if file['file_type'] not in ('document', 'code'):
        conn.close()
        abort(415)

    try:
        with open(full_path, 'w', encoding='utf-8', errors='replace') as f:
            f.write(new_content)
    except Exception:
        conn.close()
        abort(500)

    new_size = os.path.getsize(full_path)
    conn.execute('UPDATE group_files SET file_size = ? WHERE id = ?', (new_size, file_id))
    conn.commit()
    conn.close()

    # для групп у тебя нет отдельного `storage_used`, поэтому update_group_storage не нужен
    return jsonify({'status': 'ok'})


@groups_bp.route('/groups/<int:group_id>/share/<int:file_id>', methods=['POST'])
@login_required
def share_group_file(group_id, file_id):
    if not is_group_member(group_id, session['user_id']):
        return jsonify({'success': False, 'error': 'Нет доступа'}), 403

    conn = get_db()
    file = conn.execute(
        'SELECT * FROM group_files WHERE id = ? AND group_id = ? AND is_deleted = 0',
        (file_id, group_id)
    ).fetchone()
    if not file:
        conn.close()
        return jsonify({'success': False, 'error': 'Файл не найден'}), 404

    # читаем поля из формы
    raw_password = request.form.get('password') or ''
    raw_max_downloads = request.form.get('max_downloads') or ''
    raw_expires_in = request.form.get('expires_in') or ''  # например, дни

    password_hash = generate_password_hash(raw_password) if raw_password else None

    try:
        max_downloads = int(raw_max_downloads) if raw_max_downloads else None
    except ValueError:
        max_downloads = None

    try:
        days = int(raw_expires_in) if raw_expires_in else None
    except ValueError:
        days = None

    if days and days > 0:
        expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat(timespec='seconds')
    else:
        expires_at = None

    token = str(uuid.uuid4())

    conn.execute(
        '''
        INSERT INTO file_shares (file_id, token, password_hash,
                                 max_downloads, downloads, expires_at, created_by, is_active)
        VALUES (?, ?, ?, ?, 0, ?, ?, 1)
        ''',
        (file_id, token, password_hash, max_downloads, expires_at, session['user_id'])
    )
    conn.commit()
    conn.close()

    public_url = url_for('files.shared_file', token=token, _external=True)
    return jsonify({'success': True, 'share_url': public_url})

@groups_bp.route('/groups/<int:group_id>/shares')
@login_required
def group_shares(group_id):
    if not is_group_member(group_id, session['user_id']):
        flash('Вы не являетесь участником этой группы.', 'error')
        return redirect(url_for('groups.list_groups'))

    status = request.args.get('status', 'all')

    conn = get_db()
    group = conn.execute(
        'SELECT * FROM groups WHERE id = ?',
        (group_id,)
    ).fetchone()

    # берём только ссылки на group_files этой группы
    base_sql = '''
        SELECT fs.*, gf.original_filename, gf.file_size, gf.file_type
        FROM file_shares fs
        JOIN group_files gf ON gf.id = fs.file_id
        WHERE gf.group_id = ?
    '''
    params = [group_id]

    if status == 'active':
        base_sql += ' AND fs.is_active = 1'
    elif status == 'inactive':
        base_sql += ' AND fs.is_active = 0'

    base_sql += ' ORDER BY fs.created_at DESC'

    shares = conn.execute(base_sql, params).fetchall()
    conn.close()

    # подготовить удобные поля можно в шаблоне
    now_iso = datetime.utcnow().isoformat(timespec='seconds')

    return render_template(
        'groups/shares.html',
        group=group,
        shares=shares,
        status_filter=status,
        format_size=format_size,
        now_iso=now_iso
    )
