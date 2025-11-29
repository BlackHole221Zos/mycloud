from flask import Flask
import os

from config import Config
from routes.auth import auth_bp
from routes.files import files_bp
from routes.bulk import bulk_bp
from routes.admin import admin_bp

# Создаём приложение
app = Flask(__name__)
app.config.from_object(Config)

# Создаём папки
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)

# Инициализация БД при первом запуске
from init_db import init_database
init_database()

# Регистрируем Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(files_bp)
app.register_blueprint(bulk_bp)
app.register_blueprint(admin_bp)

# ==================== ЗАПУСК ====================
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)