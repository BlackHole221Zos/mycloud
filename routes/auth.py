from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from utils import get_db, get_user_folder

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('files.dashboard'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    next_url = request.args.get('next')

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = bool(user['is_admin'])

            get_user_folder(user['id'])
            flash('Добро пожаловать!', 'success')

            if next_url:
                return redirect(next_url)

            pending_token = session.get('pending_invite_token')
            if pending_token:
                return redirect(url_for('groups.join_via_link', token=pending_token))

            if user['is_admin']:
                return redirect(url_for('admin.admin_panel'))
            return redirect(url_for('files.dashboard'))
        else:
            flash('Неверный логин или пароль.', 'error')

    return render_template('login.html', next=next_url)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Пароли не совпадают', 'error')
            return render_template('register.html')

        conn = get_db()
        existing = conn.execute(
            'SELECT id FROM users WHERE username = ? OR email = ?',
            (username, email)
        ).fetchone()

        if existing:
            flash('Пользователь уже существует', 'error')
            conn.close()
            return render_template('register.html')

        hashed = generate_password_hash(password)
        cursor = conn.execute(
            'INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
            (username, email, hashed)
        )
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()

        session['user_id'] = user_id
        session['username'] = username
        session['is_admin'] = False
        get_user_folder(user_id)

        flash('Регистрация успешна!', 'success')

        pending_token = session.get('pending_invite_token')
        if pending_token:
            return redirect(url_for('groups.join_via_link', token=pending_token))

        return redirect(url_for('files.dashboard'))

    return render_template('register.html')


# ---------- ВОССТАНОВЛЕНИЕ ПАРОЛЯ БЕЗ ПОЧТЫ ----------

@auth_bp.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
    if 'user_id' in session:
        return redirect(url_for('files.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()

        if not username:
            flash('Введите имя пользователя.', 'error')
            return redirect(url_for('auth.forgot_password'))

        conn = get_db()
        user = conn.execute(
            'SELECT id, username FROM users WHERE username = ?',
            (username,)
        ).fetchone()
        conn.close()

        if not user:
            flash('Пользователь с таким именем не найден.', 'error')
            return redirect(url_for('auth.forgot_password'))

        session['reset_user_id'] = user['id']
        session['reset_username'] = user['username']

        return redirect(url_for('auth.reset_password_simple'))

    return render_template('forgot_username.html')


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password_simple():
    if 'user_id' in session:
        return redirect(url_for('files.dashboard'))

    user_id = session.get('reset_user_id')
    username = session.get('reset_username')

    if not user_id:
        flash('Сессия восстановления истекла. Попробуйте ещё раз.', 'error')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')

        if not password or len(password) < 6:
            flash('Пароль должен быть не короче 6 символов.', 'error')
            return redirect(url_for('auth.reset_password_simple'))

        if password != password2:
            flash('Пароли не совпадают.', 'error')
            return redirect(url_for('auth.reset_password_simple'))

        hashed = generate_password_hash(password)

        conn = get_db()
        conn.execute(
            'UPDATE users SET password = ? WHERE id = ?',
            (hashed, user_id)
        )
        conn.commit()
        conn.close()

        session.pop('reset_user_id', None)
        session.pop('reset_username', None)

        flash('Пароль обновлён. Теперь можете войти.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset_simple.html', username=username)


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
