import os
import sys

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = "Very_difficult_secret_key)))))))))))"

    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "site.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MAX_CONTENT_LENGTH = 1000* 1024 * 1024 * 1024   # 900MB

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static/uploads/files")
    AVATAR_FOLDER = os.path.join(BASE_DIR, "static/uploads/avatars")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_DOMAIN = False

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None

    CHAT_HISTORY_LIMIT = 50  # Сообщений за раз
    CHAT_MESSAGE_MAX_LENGTH = 5000
    CHAT_MENTION_LIMIT = 10  # Максимум упоминаний в сообщении
    
    #РЕАЛИЗАЦИЯ ЧАНКОВОЙ ЗАГРУЗКИ(БЕЗ ЛИМИТА)
    CHUNK_SIZE = 5 * 1024 * 1024  # 5MB на чанк (можно менять)
    CHUNK_UPLOAD_TIMEOUT = 3600  # 1 час на загрузку
    MAX_FILE_SIZE = 100 * 1024 * 1024 * 1024  # 100GB максимальный файл
    TEMP_UPLOAD_DIR = os.path.join(BASE_DIR, "static/uploads/temp")
    CHUNK_CLEANUP_INTERVAL = 3600  # Очистка старых чанков каждый час
    CHUNK_TTL = 86400  # Время жизни незавершённых чанков (24 часа)