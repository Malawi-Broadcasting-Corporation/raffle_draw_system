import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate

from app.config import config

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()


def create_app(config_name=None):
    config_name = config_name or os.environ.get('APP_ENV', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    if not app.config.get('SECRET_KEY'):
        raise RuntimeError("SECRET_KEY is not set. Add it to your .env file.")

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)  # batch mode is needed for SQLite schema changes
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    # Upload directories
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'participants'), exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'logos'), exist_ok=True)

    # Models must be imported so Flask-Migrate can see them
    from app import models  # noqa: F401

    # Blueprints
    from app.routes.auth import auth_bp
    from app.routes.draws import draws_bp
    from app.routes.participants import participants_bp
    from app.routes.admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(draws_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(admin_bp)

    from app.cli import register_cli
    register_cli(app)

    return app