from flask import Flask
import os

from config import Config
from routes.auth import auth_bp
from routes.files import files_bp
from routes.bulk import bulk_bp
from routes.admin import admin_bp
from routes.groups import groups_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)


    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(os.path.join(Config.UPLOAD_FOLDER, 'group_uploads'), exist_ok=True)


    app.register_blueprint(auth_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(bulk_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(groups_bp)

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
