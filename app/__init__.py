import pymysql

from app.admin import configuracion_admin
pymysql.install_as_MySQLdb()

from flask import Flask
from config import Config
from .extensions import db, login_manager, admin, migrate

def create_app():
    app = Flask (__name__)
    app.config.from_object(Config)
    
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    
    admin.init_app(app)
    from .models import User
    from .admin import configuracion_admin
    from .auth import auth_bp
    from .ai_chat import chat_bp
    configuracion_admin()
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    return app
