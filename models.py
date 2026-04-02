from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from datetime import datetime
import secrets
from flask_migrate import Migrate

site = SQLAlchemy()

# Добавьте эту модель в ваш models.py

class CustomTheme(site.Model):
    __tablename__ = 'custom_themes'
    
    id = site.Column(site.Integer, primary_key=True)
    user_id = site.Column(site.Integer, site.ForeignKey('user.id'), nullable=False)
    name = site.Column(site.String(100), nullable=False)
    
    # Цвета
    accent = site.Column(site.String(20), default='#38bdf8')
    bg = site.Column(site.String(20), default='#0b1120')
    container = site.Column(site.String(20), default='#1e293b')
    container_opacity = site.Column(site.Integer, default=70)
    text = site.Column(site.String(20), default='#38bdf8')
    text_muted = site.Column(site.String(20), default='#94a3b8')
    success = site.Column(site.String(20), default='#22c55e')
    error = site.Column(site.String(20), default='#ef4444')
    
    # Эффекты
    blur = site.Column(site.Integer, default=10)
    border_radius = site.Column(site.Integer, default=8)
    glow = site.Column(site.Integer, default=15)
    animation_speed = site.Column(site.String(10), default='0.6')
    
    # Шрифты
    font_family = site.Column(site.String(200), default="'Inter', system-ui")
    font_size = site.Column(site.String(10), default='16px')
    line_height = site.Column(site.Float, default=1.6)
    
    created_at = site.Column(site.DateTime, default=datetime.utcnow)
    
    user = site.relationship('User', backref=site.backref('custom_themes', lazy='dynamic'))

class User(site.Model, UserMixin):
    __tablename__ = 'user'
    
    id = site.Column(site.Integer, primary_key=True)
    username = site.Column(site.String(80), unique=True, nullable=False)
    email = site.Column(site.String(120), unique=True, nullable=False)
    password_hash = site.Column(site.String(200), nullable=False)
    role = site.Column(site.String(20), default='user')
    is_blocked = site.Column(site.Boolean, default=False)
    created_at = site.Column(site.DateTime, default=datetime.utcnow)
    avatar = site.Column(site.String(200), default='default.png')
    bio = site.Column(site.Text, nullable=True)
    timezone = site.Column(site.String(50), default='Europe/Moscow')
    last_seen = site.Column(site.DateTime, default=datetime.utcnow)
    
    # 2FA поля
    two_factor_enabled = site.Column(site.Boolean, default=False)
    two_factor_secret = site.Column(site.String(100), nullable=True)
    
    # Тема
    theme = site.Column(site.String(50), default='default')
    custom_accent = site.Column(site.String(20), nullable=True)
    custom_bg = site.Column(site.String(20), nullable=True)
    custom_container = site.Column(site.String(20), nullable=True)
    custom_container_opacity = site.Column(site.Integer, default=70)
    custom_text = site.Column(site.String(20), default='#38bdf8')
    custom_text_muted = site.Column(site.String(20), default='#94a3b8')
    custom_text_size = site.Column(site.String(10), default='16px')
    custom_success = site.Column(site.String(20), default='#22c55e')
    custom_error = site.Column(site.String(20), default='#ef4444')
    custom_font = site.Column(site.String(200), default='"Inter", system-ui')
    custom_blur = site.Column(site.Integer, default=10)
    custom_blur_radius = site.Column(site.Integer, default=8)
    custom_border_radius = site.Column(site.Integer, default=8)
    custom_glow = site.Column(site.Integer, default=15)
    custom_animation_speed = site.Column(site.String(10), default='0.6')
    custom_font_family = site.Column(site.String(200), default="'Inter', system-ui")
    custom_font_size = site.Column(site.String(10), default='16px')
    custom_line_height = site.Column(site.Float, default=1.6)
    
    def set_password(self, password):
        """Устанавливает хеш пароля"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Проверяет пароль"""
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'

class ChatMessage(site.Model):
    __tablename__ = 'chat_message'
    
    id = site.Column(site.Integer, primary_key=True)
    user_id = site.Column(site.Integer, site.ForeignKey("user.id"), nullable=False)
    message = site.Column(site.Text, nullable=False)
    reply = site.Column(site.Text, nullable=True)
    created_at = site.Column(site.DateTime, default=datetime.utcnow)
    edited_at = site.Column(site.DateTime, nullable=True)
    
    # Новые поля для личных сообщений и упоминаний
    is_private = site.Column(site.Boolean, default=False, nullable=False)
    recipient_id = site.Column(site.Integer, site.ForeignKey("user.id"), nullable=True)
    is_read = site.Column(site.Boolean, default=False, nullable=False)
    reply_to_id = site.Column(site.Integer, nullable=True)
    mentions = site.Column(site.Text, nullable=True)  # JSON строка с ID упомянутых пользователей
    
    # Отношения с явным указанием foreign_keys
    user = site.relationship(
        "User", 
        foreign_keys=[user_id],
        backref=site.backref('sent_messages', lazy='dynamic')
    )
    
    recipient = site.relationship(
        "User", 
        foreign_keys=[recipient_id],
        backref=site.backref('private_messages', lazy='dynamic')
    )
    
    def __repr__(self):
        return f'<ChatMessage {self.id}: {self.message[:50]}>'

class SecurityLog(site.Model):
    
    id = site.Column(site.Integer, primary_key=True)
    timestamp = site.Column(site.DateTime, default=datetime.utcnow)
    user_id = site.Column(site.Integer, site.ForeignKey('user.id'), nullable=True)
    action = site.Column(site.String(100), nullable=False)
    ip_address = site.Column(site.String(45), nullable=True)
    details = site.Column(site.Text, nullable=True)
    
    user = site.relationship('User', backref=site.backref('security_logs', lazy=True))

class File(site.Model):
    __tablename__ = 'file'
    
    id = site.Column(site.Integer, primary_key=True)
    storage_filename = site.Column(site.String(255), nullable=True)
    filename = site.Column(site.String(255), nullable=False) 
    upload_time = site.Column(site.DateTime, nullable=False, default=datetime.utcnow)
    user_id = site.Column(site.Integer, site.ForeignKey('user.id'), nullable=False)
    batch_id = site.Column(site.String(36), nullable=True)
    file_data = site.Column(site.LargeBinary, nullable=True)
    description = site.Column(site.Text, nullable=True)
    file_size = site.Column(site.Integer, default=0)  
    
    # Поля для шаринга
    share_token = site.Column(site.String(100), unique=True, nullable=True)
    is_public = site.Column(site.Boolean, default=False)
    shared_at = site.Column(site.DateTime, nullable=True)
    share_clicks = site.Column(site.Integer, default=0)
    share_downloads = site.Column(site.Integer, default=0)
    share_expiry = site.Column(site.DateTime, nullable=True)
    max_downloads = site.Column(site.Integer, nullable=True)
    last_accessed = site.Column(site.DateTime, nullable=True)
    
    user = site.relationship('User', backref=site.backref('files', lazy=True))

class Texture(site.Model):
    __tablename__ = 'textures'
    
    id = site.Column(site.Integer, primary_key=True)
    filename = site.Column(site.String(255), nullable=False)
    storage_filename = site.Column(site.String(255), nullable=False)
    texture_type = site.Column(site.String(50), default='diffuse')
    file_size = site.Column(site.Integer, default=0)
    upload_time = site.Column(site.DateTime, default=datetime.utcnow)
    
    # Внешние ключи
    user_id = site.Column(site.Integer, site.ForeignKey('user.id'), nullable=False)
    model_file_id = site.Column(site.Integer, site.ForeignKey('file.id'), nullable=True)
    mtl_file_id = site.Column(site.Integer, site.ForeignKey('file.id'), nullable=True)
    
    # Отношения с явным указанием foreign_keys
    user = site.relationship('User', backref=site.backref('textures', lazy=True), foreign_keys=[user_id])
    model_file = site.relationship(
        'File', 
        foreign_keys=[model_file_id],
        backref=site.backref('textures', lazy=True)
    )
    mtl_file = site.relationship(
        'File', 
        foreign_keys=[mtl_file_id],
        backref=site.backref('mtl_textures', lazy=True)
    )
    
    def __repr__(self):
        return f'<Texture {self.filename} ({self.texture_type})>'

class Material(site.Model):
    """Модель для хранения материалов из MTL файлов"""
    __tablename__ = 'materials'
    
    id = site.Column(site.Integer, primary_key=True)
    name = site.Column(site.String(255), nullable=False)  # Имя материала
    mtl_file_id = site.Column(site.Integer, site.ForeignKey('file.id'), nullable=False)
    model_file_id = site.Column(site.Integer, site.ForeignKey('file.id'), nullable=True)
    
    # Параметры материала
    ambient = site.Column(site.String(50), nullable=True)  # Ka
    diffuse = site.Column(site.String(50), nullable=True)  # Kd
    specular = site.Column(site.String(50), nullable=True)  # Ks
    emission = site.Column(site.String(50), nullable=True)  # Ke
    shininess = site.Column(site.Float, default=0.0)  # Ns
    transparency = site.Column(site.Float, default=1.0)  # d или Tr
    illumination = site.Column(site.Integer, default=0)  # illum
    
    # Текстуры
    diffuse_map = site.Column(site.String(255), nullable=True)  # map_Kd
    specular_map = site.Column(site.String(255), nullable=True)  # map_Ks
    normal_map = site.Column(site.String(255), nullable=True)  # map_Bump, bump
    alpha_map = site.Column(site.String(255), nullable=True)  # map_d
    
    upload_time = site.Column(site.DateTime, default=datetime.utcnow)
    
    # Отношения с явным указанием foreign_keys
    mtl_file = site.relationship(
        'File', 
        foreign_keys=[mtl_file_id],
        backref=site.backref('materials', lazy=True)
    )
    model_file = site.relationship(
        'File', 
        foreign_keys=[model_file_id],
        backref=site.backref('model_materials', lazy=True)
    )
    
    def __repr__(self):
        return f'<Material {self.name}>'

