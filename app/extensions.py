from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_login import LoginManager

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
login_manager = LoginManager()
login_manager.login_view = "auth.login_page"
login_manager.login_message = "Debe iniciar sesión para acceder al sistema."
login_manager.login_message_category = "warning"