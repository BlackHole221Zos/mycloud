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

            # 1. Проверяем прямой next_url
            if next_url:
                return redirect(next_url)

            # 2. Проверяем отложенное приглашение
            pending_token = session.get('pending_invite_token')
            if pending_token:
                return redirect(url_for('groups.join_via_link', token=pending_token))

            # 3. Стандартный вход
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
        existing = conn.execute('SELECT id FROM users WHERE username = ? OR email = ?', (username, email)).fetchone()

        if existing:
            flash('Пользователь уже существует', 'error')
            conn.close()
            return render_template('register.html')

        hashed = generate_password_hash(password)
        cursor = conn.execute('INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
                              (username, email, hashed))
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()

        session['user_id'] = user_id
        session['username'] = username
        session['is_admin'] = False
        get_user_folder(user_id)

        flash('Регистрация успешна!', 'success')

        # Проверка приглашения после регистрации
        pending_token = session.get('pending_invite_token')
        if pending_token:
            return redirect(url_for('groups.join_via_link', token=pending_token))

        return redirect(url_for('files.dashboard'))

    return render_template('register.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))