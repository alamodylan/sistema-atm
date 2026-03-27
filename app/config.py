import os


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key")

    # PostgreSQL con pg8000 (IMPORTANTE)
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql+pg8000://postgres:password@localhost:5432/sistema_atm"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # JWT
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwt-secret-key")

    # Opcional: mejorar logs en producción
    PROPAGATE_EXCEPTIONS = True