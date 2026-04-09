import sys
import os
import uuid
import io
import base64
import secrets
import pyotp
import qrcode
import traceback
import logging
import time
import json
import plistlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from itertools import groupby
from functools import wraps
import xml.etree.ElementTree as ET
import csv
from io import StringIO

from flask import Flask, jsonify, render_template, url_for, flash, abort, redirect, request, send_from_directory, session, current_app, Response
from flask_socketio import SocketIO
from flask_socketio import join_room, leave_room
from flask_login import LoginManager, login_user, current_user, logout_user, login_required
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate
from sqlalchemy import func, or_
from werkzeug.utils import secure_filename
from markupsafe import Markup, escape
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from docx import Document
except ImportError:
    Document = None

from models import site, User, File, ChatMessage, Texture, CustomTheme
from config import Config
from chunk_upload import chunk_manager

# НАСТРОЙКИ

ALLOWED_EXTENSIONS = {
    # КАРТИНКИ 
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg',
    
    # ДОКИ
    'pdf', 'docx', 'doc', 'odt', 'txt', 'md', 'csv', 'json',
    
    # КОДЫ ЛОГИ И ВСЯКАЯ ФИГНЯ
    'html', 'css', 'js', 'py', 'xml', 'ini', 'cfg', 'log',
    
    # ЗВУКИ
    'mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac',
    
    # ВИДЕО
    'mp4', 'webm', 'mov', 'avi', 'mkv',
    
    # АРХИВЫ
    'zip', 'rar', '7z', 'tar', 'gz',
    
    # ССЫЛКИ(хз зачем добавил , но почему бы и нет)
    'url', 'webloc', 'desktop',

    # МОДКЛЬКИ
    'stl', 'obj', 'gltf', 'glb', 'ply', 'fbx', '3mf', 'dae',
    
    # ТЕКСТУРЫ ДЛЯ МОДЕЛЕК
    'jpg', 'jpeg', 'png', 'tga', 'dds', 'tiff', 'mtl'
}

LOCAL_TIMEZONE = ZoneInfo("Europe/Moscow")
socketio = SocketIO()

 
# ДЕКОРАТОРЫ И ПРОЧАЯ ФИГНЯ
class CustomRequestFormatter(logging.Formatter):
    def format(self, record):
        if hasattr(record, 'request_time'):
            record.request_time = f"{record.request_time:.2f}"
        else:
            record.request_time = "0.00"
        
        record.date = datetime.now().strftime('%d/%b/%Y %H:%M:%S')
        return super().format(record)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def parse_mtl_file(mtl_path, mtl_file_id, model_id):
    """Парсинг"""
    materials = []
    current_material = {}
    
    try:
        with open(mtl_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                parts = line.split()
                if not parts:
                    continue
                
                cmd = parts[0].lower()
                
                if cmd == 'newmtl':
                    if current_material and 'name' in current_material:
                        materials.append(current_material)
                    current_material = {'name': ' '.join(parts[1:])}
                
                elif cmd == 'ka':
                    if len(parts) >= 4:
                        current_material['Ka'] = f"{parts[1]} {parts[2]} {parts[3]}"
                    elif len(parts) >= 2:
                        current_material['Ka'] = parts[1]
                
                elif cmd == 'kd':
                    if len(parts) >= 4:
                        current_material['Kd'] = f"{parts[1]} {parts[2]} {parts[3]}"
                    elif len(parts) >= 2:
                        current_material['Kd'] = parts[1]
                
                elif cmd == 'ks':
                    if len(parts) >= 4:
                        current_material['Ks'] = f"{parts[1]} {parts[2]} {parts[3]}"
                    elif len(parts) >= 2:
                        current_material['Ks'] = parts[1]
                
                elif cmd == 'ke':
                    if len(parts) >= 4:
                        current_material['Ke'] = f"{parts[1]} {parts[2]} {parts[3]}"
                    elif len(parts) >= 2:
                        current_material['Ke'] = parts[1]
                
                elif cmd == 'ns':
                    if len(parts) >= 2:
                        try:
                            current_material['Ns'] = float(parts[1])
                        except:
                            pass
                
                elif cmd == 'd' or cmd == 'tr':
                    if len(parts) >= 2:
                        try:
                            current_material['d'] = float(parts[1])
                        except:
                            pass
                
                elif cmd == 'illum':
                    if len(parts) >= 2:
                        try:
                            current_material['illum'] = int(parts[1])
                        except:
                            pass
                
                elif cmd == 'map_kd':
                    if len(parts) >= 2:
                        current_material['map_Kd'] = ' '.join(parts[1:])
                
                elif cmd == 'map_ks':
                    if len(parts) >= 2:
                        current_material['map_Ks'] = ' '.join(parts[1:])
                
                elif cmd == 'map_bump' or cmd == 'bump':
                    if len(parts) >= 2:
                        current_material['map_Bump'] = ' '.join(parts[1:])
                
                elif cmd == 'map_d':
                    if len(parts) >= 2:
                        current_material['map_d'] = ' '.join(parts[1:])
    
    except Exception as e:
        print(f"Error parsing MTL: {e}")
    
    if current_material and 'name' in current_material:
        materials.append(current_material)
    
    return materials



#СОБСТВЕННО ПРИЛОЖЕНИЕ
def create_app(gui_signal=None):
    """экземпляр Flask приложения"""
    
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
        bundle_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(os.path.dirname(__file__))
        bundle_path = base_path

    app = Flask(
        __name__,
        template_folder=os.path.join(bundle_path, "templates"),
        static_folder=os.path.join(bundle_path, "static")
    )

    app.config.from_object(Config)

    upload_folder = os.path.join(base_path, "static", "uploads", "files")
    avatar_folder = os.path.join(base_path, "static", "uploads", "avatars")

    app.config["UPLOAD_FOLDER"] = upload_folder
    app.config["AVATAR_FOLDER"] = avatar_folder

    os.makedirs(upload_folder, exist_ok=True)
    os.makedirs(avatar_folder, exist_ok=True)

    CSRFProtect(app)
    site.init_app(app)
    Migrate(app, site)

    # ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
    for handler in logging.getLogger('werkzeug').handlers[:]:
        logging.getLogger('werkzeug').removeHandler(handler)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(CustomRequestFormatter(
        '%(request_time)s - [%(date)s] "%(message)s"'
    ))
    console_handler.setLevel(logging.INFO)
    
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.INFO)
    werkzeug_logger.addHandler(console_handler)
    werkzeug_logger.propagate = False
    
    app.logger.setLevel(logging.INFO)
    app.logger.addHandler(console_handler)
    app.logger.propagate = False
    
    app.config['GUI_SIGNAL'] = gui_signal

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.login_message_category = "danger"
    login_manager.login_message = "Пожалуйста, войдите в систему."
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    #Фильтры
    @app.template_filter('linebreaksbr')
    def linebreaksbr_filter(s):
        if not s:
            return ""
        lines = escape(s).replace('\n', Markup('<br>'))
        return lines
    

    @app.template_filter("localtime")
    def localtime_filter(dt):
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local_dt = dt.astimezone(LOCAL_TIMEZONE)
        return local_dt.strftime("%d.%m.%Y %H:%M")

    @app.template_filter('rgb')
    def hex_to_rgb_filter(hex_color):
        """перевод хекс в ргб"""
        if not hex_color or not hex_color.startswith('#'):
            return '30, 41, 59'  
        
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 6:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            return f"{r}, {g}, {b}"
        return '30, 41, 59'
    
    # ну короче проверка перед дейсвиями
    @app.before_request
    def start_timer():
        request.start_time = time.time()
    
    @app.before_request
    def refresh_session():
        session.permanent = True
        app.permanent_session_lifetime = timedelta(minutes=30)
        
        if current_user.is_authenticated:
            current_user.last_seen = datetime.utcnow()
            try:
                site.session.commit()
            except:
                site.session.rollback()
    
    @app.before_request
    def check_if_blocked():
        if not current_user.is_authenticated:
            return
        allowed_routes = ["logout", "static"]
        if request.endpoint in allowed_routes:
            return
        if current_user.is_blocked:
            return render_template("blocked.html"), 403
    
    @app.after_request
    def log_request(response):
        if hasattr(request, 'start_time'):
            elapsed = time.time() - request.start_time
        else:
            elapsed = 0
        
        log_message = f'{request.method} {request.path} HTTP/1.1" {response.status_code}'
        content_length = response.headers.get('Content-Length', '-')
        werkzeug_logger.info(f'{content_length} - "{log_message}"')
        
        return response

    # обработчики
    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500


    # маршруты(да я перестал писать капсом , надоело)
    @app.route('/')
    @app.route('/index')
    @login_required
    def index():
        all_files = File.query.order_by(File.upload_time.desc()).limit(100).all()
        
        def get_group_key(f):
            return f.batch_id if f.batch_id else f"single_{f.id}"
        
        all_files.sort(key=lambda x: (get_group_key(x), x.upload_time), reverse=True)
        
        grouped_list = []
        for key, group in groupby(all_files, key=get_group_key):
            grouped_list.append(list(group))
        grouped_list.sort(key=lambda g: g[0].upload_time, reverse=True)
        
        return render_template('index.html', grouped_files=grouped_list, now=datetime.utcnow())

    @app.route('/profile/<int:user_id>')
    @login_required
    def profile(user_id):
        user = User.query.get_or_404(user_id)
        page = request.args.get('page', 1, type=int)
        files = File.query.filter_by(user_id=user.id)\
                    .order_by(File.upload_time.desc())\
                    .paginate(page=page, per_page=5)
        
        total_size_bytes = site.session.query(func.sum(File.file_size)).filter_by(user_id=user.id).scalar() or 0
        total_size_mb = total_size_bytes / (1024 * 1024)
        total_files_count = File.query.filter_by(user_id=user.id).count()
        
        user.last_seen = datetime.utcnow()
        site.session.commit()
        
        return render_template('profile.html', 
                            user=user, 
                            files=files,
                            total_size_mb=total_size_mb,
                            total_files_count=total_files_count,
                            now=datetime.utcnow())

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
            
        if request.method == 'POST':
            try:
                username = request.form.get("username", "").strip()
                email = request.form.get("email", "").strip().lower()
                password = request.form.get("password", "")

                if not username or not email or len(password) < 6:
                    flash('Неправильный ввод', 'danger')
                    return redirect(url_for('register'))

                if User.query.filter_by(username=username).first():
                    flash('Такое имя уже есть', 'danger')
                    return redirect(request.url)
                
                if User.query.filter_by(email=email).first():
                    flash('Такой email уже есть', 'danger')
                    return redirect(request.url)
                
                user = User(username=username, email=email)
                user.set_password(password)
                
                site.session.add(user)
                site.session.commit()
                
                flash('Аккаунт создан!', 'success')
                return redirect(url_for('login'))
                
            except Exception as e:
                site.session.rollback()
                flash(f'Ошибка при регистрации: {str(e)}', 'danger')
                return redirect(url_for('register'))
                
        return render_template('register.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))

        if request.method == 'POST':
            email = request.form.get("email", "")
            password = request.form.get("password", "")
            user = User.query.filter_by(email=email).first()

            if user and user.is_blocked:
                flash("Аккаунт заблокирован администратором", "danger")
                return redirect(url_for("login"))

            if user and user.check_password(password):
                if user.two_factor_enabled:
                    session["2fa_user_id"] = user.id
                    return redirect(url_for("two_factor_verify"))

                login_user(user, remember=True)
                return redirect(url_for('index'))

            flash('Вход не удался. Проверьте данные.', 'danger')

        return render_template('login.html')

    @app.route('/logout')
    def logout():
        logout_user()
        return redirect(url_for('index'))

    @app.route('/profile/edit', methods=['GET', 'POST'])
    @login_required
    def edit_profile():
        if request.method == 'POST':
            username = request.form.get('username')
            email = request.form.get('email')
            bio = request.form.get('bio')

            if username != current_user.username:
                user_exists = User.query.filter_by(username=username).first()
                if user_exists:
                    flash('Это имя пользователя уже занято.', 'error')
                    return redirect(url_for('edit_profile'))

            current_user.username = username
            current_user.email = email
            current_user.bio = bio

            try:
                site.session.commit()
                flash('Профиль успешно обновлен!', 'success')
                return redirect(url_for('profile', user_id=current_user.id))
            except Exception as e:
                site.session.rollback()
                flash('Произошла ошибка при сохранении изменений.', 'error')
        
        return render_template('edit_profile.html', user=current_user)
    
    @app.route('/theme-settings')
    @login_required
    def theme_settings():
        """кастомки для тем"""
        return render_template('theme_settings.html')

    @app.route('/api/custom-themes')
    @login_required
    def get_custom_themes():
        """все кастомные темы пользователя"""
        themes = CustomTheme.query.filter_by(user_id=current_user.id).order_by(CustomTheme.created_at.desc()).all()
        
        return jsonify({
            'themes': [{
                'id': theme.id,
                'name': theme.name,
                'accent': theme.accent,
                'bg': theme.bg,
                'container': theme.container,
                'created_at': theme.created_at.strftime('%d.%m.%Y') if theme.created_at else ''
            } for theme in themes]
        })

    @app.route('/api/save-custom-theme', methods=['POST'])
    @login_required
    def save_custom_theme():
        """сохранить текущую тему"""
        data = request.get_json()
        
        theme = CustomTheme(
            user_id=current_user.id,
            name=data.get('name', 'Моя тема'),
            accent=data.get('accent', '#38bdf8'),
            bg=data.get('bg', '#0b1120'),
            container=data.get('container', '#1e293b'),
            container_opacity=data.get('container_opacity', 70),
            text=data.get('text', '#38bdf8'),
            text_muted=data.get('text_muted', '#94a3b8'),
            success=data.get('success', '#22c55e'),
            error=data.get('error', '#ef4444'),
            blur=data.get('blur', 10),
            border_radius=data.get('border_radius', 8),
            glow=data.get('glow', 15),
            animation_speed=data.get('animation_speed', '0.6'),
            font_family=data.get('font_family', "'Inter', system-ui"),
            font_size=data.get('font_size', '16px'),
            line_height=float(data.get('line_height', 1.6)),
            # НОВЫЕ ПОЛЯ:
            blur_radius=data.get('custom_blur_radius', 8),
            custom_font=data.get('custom_font', "'Inter', system-ui"),
            custom_text_size=data.get('custom_text_size', '16px')
        )
        
        site.session.add(theme)
        site.session.commit()
        
        return jsonify({'success': True, 'id': theme.id})

    @app.route('/api/apply-theme/<int:theme_id>', methods=['POST'])
    @login_required
    def apply_custom_theme(theme_id):
        """применить тему"""
        theme = CustomTheme.query.get_or_404(theme_id)
        
        if theme.user_id != current_user.id:
            abort(403)
        
        current_user.theme = 'custom'
        current_user.custom_accent = theme.accent
        current_user.custom_bg = theme.bg
        current_user.custom_container = theme.container
        current_user.custom_container_opacity = theme.container_opacity
        current_user.custom_text = theme.text
        current_user.custom_text_muted = theme.text_muted
        current_user.custom_success = theme.success
        current_user.custom_error = theme.error
        current_user.custom_blur = theme.blur
        current_user.custom_border_radius = theme.border_radius
        current_user.custom_glow = theme.glow
        current_user.custom_animation_speed = theme.animation_speed
        current_user.custom_font_family = theme.font_family
        current_user.custom_font_size = theme.font_size
        current_user.custom_line_height = theme.line_height
        current_user.custom_blur_radius = theme.blur_radius
        current_user.custom_font = theme.custom_font
        current_user.custom_text_size = theme.custom_text_size
        
        site.session.commit()
        
        return jsonify({'success': True})

    @app.route('/api/delete-theme/<int:theme_id>', methods=['DELETE'])
    @login_required
    def delete_custom_theme(theme_id):
        """удалить тему"""
        theme = CustomTheme.query.get_or_404(theme_id)
        
        if theme.user_id != current_user.id:
            abort(403)
        
        site.session.delete(theme)
        site.session.commit()
        
        return jsonify({'success': True})

    
    # так то тоже маршруты , но для файлов
   
    @app.route("/upload", methods=["GET", "POST"])
    @login_required
    def upload():
        if request.method == "POST":
            if "files" not in request.files:
                flash("Файлы не найдены", "error")
                return redirect(request.url)

            files = request.files.getlist("files")
            if not files or files[0].filename == "":
                flash("Файлы не выбраны", "error")
                return redirect(request.url)

            upload_folder = app.config["UPLOAD_FOLDER"]
            os.makedirs(upload_folder, exist_ok=True)
            
            
            existing_batch_id = request.form.get("batch_id")
            
            # Если передан существующий batch_id, используем его, иначе создаем новый
            if existing_batch_id:
                batch_id = existing_batch_id
            else:
                batch_id = str(uuid.uuid4()) if len(files) > 1 else None

            uploaded_count = 0
            failed_count = 0

            for file in files:
                original_name = file.filename
                if "." not in original_name:
                    flash(f"Файл {original_name} без расширения", "error")
                    failed_count += 1
                    continue

                ext = original_name.rsplit(".", 1)[-1].lower()
                if ext not in ALLOWED_EXTENSIONS:
                    flash(f"Файл {original_name} запрещён", "error")
                    failed_count += 1
                    continue

                storage_name = f"{uuid.uuid4().hex}.{ext}"
                file_path = os.path.join(upload_folder, storage_name)
                file.save(file_path)
                
                file_size = os.path.getsize(file_path)
                description = request.form.get("description")

                new_file = File(
                    filename=original_name,
                    storage_filename=storage_name,
                    user_id=current_user.id,
                    batch_id=batch_id,
                    description=description,
                    file_size=file_size
                )
                site.session.add(new_file)
                uploaded_count += 1

            site.session.commit()
            
            if uploaded_count > 0:
                if failed_count > 0:
                    flash(f"Загружено {uploaded_count} файлов. Ошибок: {failed_count}", "warning")
                else:
                    flash(f"Успешно загружено {uploaded_count} файлов", "success")
            else:
                flash("Не удалось загрузить ни одного файла", "error")
                
            return redirect(url_for("index"))

        return render_template("upload.html")
    
    @app.route('/view/<int:file_id>')
    @login_required
    def view_file(file_id):
        file_record = File.query.get_or_404(file_id)
        content = None
        
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_record.storage_filename)
        
        file_size = 0
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            if file_record.file_size != file_size:
                file_record.file_size = file_size
                site.session.commit()
        
        filename = file_record.filename.lower()
        ext = filename.split('.')[-1] if '.' in filename else ''
        
        # Текстовые файлы(данунахуй)
        text_extensions = ['txt', 'py', 'js', 'css', 'html', 'xml', 'md', 'ini', 'cfg', 'log']
        
        if ext in text_extensions:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except Exception as e:
                content = f"Не удалось прочитать файл: {e}"
        
        elif ext == 'json':
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    raw_content = f.read()
                    try:
                        json_data = json.loads(raw_content)
                        content = json.dumps(json_data, indent=2, ensure_ascii=False)
                    except:
                        content = raw_content
            except Exception as e:
                content = f"Не удалось прочитать JSON: {e}"
        
        elif ext == 'csv':
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except Exception as e:
                content = f"Не удалось прочитать CSV: {e}"
        
        elif ext in ['url', 'webloc', 'desktop']:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    if ext == 'url':
                        for line in content.split('\n'):
                            if line.lower().startswith('url='):
                                content = line[4:].strip()
                                break
                    elif ext == 'webloc':
                        try:
                            with open(file_path, 'rb') as f:
                                plist = plistlib.load(f)
                                content = plist.get('URL', content)
                        except:
                            root = ET.fromstring(content)
                            for elem in root.iter():
                                if elem.tag == 'string' and 'http' in (elem.text or ''):
                                    content = elem.text
                                    break
            except Exception as e:
                content = f"Не удалось прочитать ссылку: {e}"
        
        elif ext == 'docx':
            if Document is None:
                content = "Предпросмотр DOCX недоступен: библиотека python-docx не установлена."
            else:
                try:
                    doc = Document(file_path)
                    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
                    content = "\n".join(paragraphs) if paragraphs else "Документ пуст."
                except Exception as e:
                    content = f"Не удалось прочитать DOCX: {e}"
        
        elif ext in ['doc', 'odt', 'ppt', 'pptx', 'xls', 'xlsx', 'ods']:
            content = f"Предпросмотр .{ext} файлов не поддерживается. Скачайте файл для просмотра."
        
        elif ext in ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac', 'mp4', 'webm', 'mov', 'avi', 'mkv',
                     'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', 'zip', 'rar', '7z', 'tar', 'gz']:
            pass
        
        else:
            content = f"Предпросмотр для .{ext} файлов не поддерживается."
        
        return render_template('view_file.html', 
                            file=file_record, 
                            content=content, 
                            file_size=file_size,
                            ext=ext)

    @app.route('/raw/<int:file_id>')
    @login_required
    def get_raw_file(file_id):
        file_record = File.query.get_or_404(file_id)
        name_to_serve = file_record.storage_filename or file_record.filename
        return send_from_directory(app.config['UPLOAD_FOLDER'], name_to_serve)

    @app.route('/download/<int:file_id>')
    @login_required
    def download_file(file_id):
        file_data = File.query.get_or_404(file_id)
        name_to_serve = file_data.storage_filename or file_data.filename
        return send_from_directory(
            app.config['UPLOAD_FOLDER'], 
            name_to_serve, 
            as_attachment=True, 
            download_name=file_data.filename
        )

    @app.route('/delete/<int:file_id>', methods=['POST'])
    @login_required
    def delete_file(file_id):
        file_record = File.query.get_or_404(file_id)
        
        if file_record.user_id != current_user.id and current_user.role != "admin":
            abort(403)

        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_record.storage_filename)
        if os.path.exists(file_path):
            os.remove(file_path)

        site.session.delete(file_record)
        site.session.commit()
        
        return redirect(url_for('index'))

    @app.route('/delete_batch', methods=['POST'])
    @login_required
    def delete_batch():
        batch_id = request.form.get('batch_id')
        
        if not batch_id:
            flash('Неверный идентификатор пакета', 'error')
            return redirect(url_for('index'))
        
        files = File.query.filter_by(batch_id=batch_id).all()
        
        if not files:
            flash('Пакет не найден', 'error')
            return redirect(url_for('index'))
        
        for file in files:
            if file.user_id != current_user.id and current_user.role != 'admin':
                abort(403)
        
        deleted_count = 0
        failed_count = 0
        
        for file in files:
            try:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.storage_filename)
                if os.path.exists(file_path):
                    os.remove(file_path)
                site.session.delete(file)
                deleted_count += 1
            except Exception as e:
                app.logger.error(f"Ошибка при удалении файла {file.id}: {e}")
                failed_count += 1
        
        site.session.commit()
        
        if failed_count > 0:
            flash(f'Удалено {deleted_count} файлов из {len(files)}. Ошибок: {failed_count}', 'warning')
        else:
            flash(f'Пакет успешно удалён! Удалено файлов: {deleted_count}', 'success')
        
        return redirect(url_for('index'))

    
    #все еще маршруты , но теперь уже с аватарками и прочей фигней(я пойму)
    @app.route('/edit_avatar', methods=['POST'])
    @login_required
    def edit_avatar():
        if 'avatar' not in request.files:
            return {"message": "Файл не найден"}, 400
        file = request.files['avatar']
        if file.filename == '':
            return {"message": "Файл не выбран"}, 400
        ext = file.filename.rsplit(".", 1)[1].lower()
        allowed = {"png", "jpg", "jpeg", "gif", "webp"}
        if ext not in allowed:
            return {"message": "Недопустимый формат"}, 400
        try:
            avatar_folder = app.config["AVATAR_FOLDER"]
            
            if ext == "gif":
                filename = f"user_{current_user.id}.gif"
                save_path = os.path.join(avatar_folder, filename)
                file.save(save_path)
            
            elif ext == "webp":
                if Image is None:
                    return {"message": "Pillow не установлен"}, 500
                img = Image.open(file)
                filename = f"user_{current_user.id}.webp"
                save_path = os.path.join(avatar_folder, filename)
                img.save(save_path, "WEBP", quality=90, lossless=False)
            
            elif ext == "png":
                if Image is None:
                    return {"message": "Pillow не установлен"}, 500
                img = Image.open(file)
                filename = f"user_{current_user.id}.png"
                save_path = os.path.join(avatar_folder, filename)
                img.save(save_path, "PNG", optimize=True)
            
            elif ext in ["jpg", "jpeg"]:
                if Image is None:
                    return {"message": "Pillow не установлен"}, 500
                img = Image.open(file)
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
                else:
                    img = img.convert('RGB')
                filename = f"user_{current_user.id}.jpg"
                save_path = os.path.join(avatar_folder, filename)
                img.save(save_path, "JPEG", quality=95)
            
            current_user.avatar = filename
            site.session.commit()
            return {"message": "Успешно"}, 200
        except Exception as e:
            print("Avatar error:", e)
            return {"message": "Ошибка обработки изображения"}, 400
    
    @app.route('/avatar/<filename>')
    def avatar(filename):
        return send_from_directory(app.config["AVATAR_FOLDER"], filename)

    
    #ссылочки кодики и прочая фигня
    @app.route("/share/<int:file_id>", methods=['GET', 'POST'])
    @login_required
    def share_file(file_id):
        file = File.query.get_or_404(file_id)

        if file.user_id != current_user.id and current_user.role != "admin":
            abort(403)

        if request.method == 'POST':
            expiry_days = request.form.get('expiry_days', type=int)
            max_downloads = request.form.get('max_downloads', type=int)
            
            if not file.share_token:
                file.share_token = secrets.token_urlsafe(32)
                file.is_public = True
                file.shared_at = datetime.utcnow()
            
            if expiry_days and expiry_days > 0:
                file.share_expiry = datetime.utcnow() + timedelta(days=expiry_days)
            else:
                file.share_expiry = None
            
            if max_downloads and max_downloads > 0:
                file.max_downloads = max_downloads
            else:
                file.max_downloads = None
            
            file.share_clicks = 0
            file.share_downloads = 0
            
            site.session.commit()
            flash("Настройки ссылки обновлены", "success")
            return redirect(url_for('share_file', file_id=file.id))

        if not file.share_token:
            file.share_token = secrets.token_urlsafe(32)
            file.is_public = True
            file.shared_at = datetime.utcnow()
            site.session.commit()

        link = url_for("public_file", token=file.share_token, _external=True)
        
        stats = {
            'clicks': file.share_clicks or 0,
            'downloads': file.share_downloads or 0,
            'created': file.shared_at,
            'expiry': file.share_expiry,
            'max_downloads': file.max_downloads
        }
        
        qr_code = None
        try:
            if qrcode:
                qr = qrcode.QRCode(version=1, box_size=10, border=5)
                qr.add_data(link)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                qr_code = base64.b64encode(buffer.getvalue()).decode()
        except Exception as e:
            print(f"QR generation error: {e}")

        return render_template("share.html", file=file, link=link, stats=stats, qr_code=qr_code, now=datetime.utcnow())
    
    @app.route("/share/<int:file_id>/revoke", methods=["POST"])
    @login_required
    def revoke_share(file_id):
        file = File.query.get_or_404(file_id)
        
        if file.user_id != current_user.id and current_user.role != "admin":
            abort(403)
        
        file.share_token = None
        file.is_public = False
        file.shared_at = None
        site.session.commit()
        
        flash("Публичная ссылка удалена", "success")
        return redirect(url_for('profile', user_id=current_user.id))

    @app.route("/s/<token>")
    def public_file(token):
        file = File.query.filter_by(share_token=token, is_public=True).first_or_404()
        
        if file.share_expiry and file.share_expiry < datetime.utcnow():
            abort(410)
        
        if file.max_downloads and file.share_downloads >= file.max_downloads:
            abort(403)
        
        file.share_clicks = (file.share_clicks or 0) + 1
        file.share_downloads = (file.share_downloads or 0) + 1
        file.last_accessed = datetime.utcnow()
        site.session.commit()

        return send_from_directory(
            app.config["UPLOAD_FOLDER"],
            file.storage_filename,
            as_attachment=True,
            download_name=file.filename
        )

    #поиск
    
    @app.route("/search")
    @login_required
    def search():
        query = request.args.get("q", "").strip().lower()
        
        if not query:
            return render_template("search.html", files=[], query=query)
        
        type_to_extensions = {
            'изображение': ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'],
            'изображения': ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'],
            'документ': ['pdf', 'docx', 'doc', 'odt', 'txt', 'md', 'csv', 'json'],
            'видео': ['mp4', 'webm', 'mov', 'avi', 'mkv'],
            'аудио': ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac'],
            'архив': ['zip', 'rar', '7z', 'tar', 'gz'],
            'код': ['html', 'css', 'js', 'py', 'xml', 'ini', 'cfg', 'log', 'json'],
            '3d': ['stl', 'obj', 'gltf', 'glb', 'ply', 'fbx', '3mf', 'dae'],
            'ссылка': ['url', 'webloc', 'desktop'],
        }
        
        extensions_to_search = []
        
        if query in type_to_extensions:
            extensions_to_search = type_to_extensions[query]
        elif query in ALLOWED_EXTENSIONS:
            extensions_to_search = [query]
        
        if extensions_to_search:
            conditions = []
            for ext in extensions_to_search:
                conditions.append(File.filename.ilike(f'%.{ext}'))
            files = File.query.filter(or_(*conditions)).order_by(File.upload_time.desc()).all()
        else:
            files = File.query.filter(
                File.filename.ilike(f"%{query}%")
            ).order_by(File.upload_time.desc()).all()
        
        return render_template("search.html", files=files, query=query)

    #двухфакторка и темы
    
    @app.route("/2fa", methods=["GET", "POST"])
    def two_factor_verify():
        user_id = session.get("2fa_user_id")
        if not user_id:
            return redirect(url_for("login"))
        user = User.query.get(user_id)
        if not user or not user.two_factor_secret:
            return redirect(url_for("login"))
        if request.method == "POST":
            code = request.form.get("code", "").strip()
            totp = pyotp.TOTP(user.two_factor_secret)
            if totp.verify(code, valid_window=1):
                login_user(user, remember=True)
                session.pop("2fa_user_id", None)
                flash("Успешная двухфакторная аутентификация", "success")
                return redirect(url_for("index"))
            flash("Неверный код", "danger")
        return render_template("2fa.html")
    
    @app.route("/enable-2fa")
    @login_required
    def enable_2fa():
        secret = pyotp.random_base32()
        session["temp_2fa_secret"] = secret
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(name=current_user.email, issuer_name="Space Share")
        img = qrcode.make(uri)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        qr_base64 = base64.b64encode(buffer.getvalue()).decode()
        return render_template("enable_2fa.html", qr_code=qr_base64)
   
    @app.route("/confirm-2fa", methods=["POST"])
    @login_required
    def confirm_2fa():
        code = request.form.get("code", "").strip()
        secret = session.get("temp_2fa_secret")
        if not secret:
            flash("Ошибка инициализации 2FA", "danger")
            return redirect(url_for("profile", user_id=current_user.id))
        totp = pyotp.TOTP(secret)
        if totp.verify(code, valid_window=1):
            current_user.two_factor_secret = secret
            current_user.two_factor_enabled = True
            site.session.commit()
            session.pop("temp_2fa_secret", None)
            flash("2FA успешно включена", "success")
            return redirect(url_for("profile", user_id=current_user.id))
        flash("Неверный код", "danger")
        return redirect(url_for("enable_2fa"))

    @app.route("/disable-2fa", methods=["POST"])
    @login_required
    def disable_2fa():
        current_user.two_factor_enabled = False
        current_user.two_factor_secret = None
        site.session.commit()
        flash("2FA отключена", "success")
        return redirect(url_for("profile", user_id=current_user.id))
       
    @app.route("/set_theme", methods=["POST"])
    @login_required
    def set_theme():
        data = request.get_json()
        if not data:
            return {"status": "error", "message": "Нет данных"}, 400
        
        theme = data.get("theme")
        allowed = ["default", "black", "slate", "ocean", "midnight", "neon", "custom"]
        
        if theme not in allowed:
            return {"status": "error", "message": "Недопустимая тема"}, 400
        
        current_user.theme = theme
        
        if theme == "custom":
            current_user.custom_accent = data.get("accent", "#38bdf8")
            current_user.custom_bg = data.get("bg", "#0b1120")
            current_user.custom_container = data.get("container", "#1e293b")
            current_user.custom_container_opacity = data.get("container_opacity", 70)
            current_user.custom_text = data.get("text", "#38bdf8")
            current_user.custom_text_muted = data.get("text_muted", "#94a3b8")
            current_user.custom_success = data.get("success", "#22c55e")
            current_user.custom_error = data.get("error", "#ef4444")
            current_user.custom_blur = data.get("blur", 10)
            current_user.custom_border_radius = data.get("border_radius", 8)
            current_user.custom_glow = data.get("glow", 15)
            current_user.custom_animation_speed = data.get("animation_speed", "0.6")
            current_user.custom_font_family = data.get("font_family", "'Inter', system-ui")
            current_user.custom_font_size = data.get("font_size", "16px")
            current_user.custom_line_height = data.get("line_height", 1.6)
        
        site.session.commit()
        return {"status": "ok"}

    #боль в моей попа дырка (3д модели)
    
    @app.route('/upload_texture/<int:model_id>', methods=['POST'])
    @login_required
    def upload_texture(model_id):
        model = File.query.get_or_404(model_id)
        if model.user_id != current_user.id and current_user.role != 'admin':
            abort(403)
        
        ext = model.filename.lower().split('.')[-1]
        if ext not in ['stl', 'obj', 'gltf', 'glb', 'ply', 'fbx', '3mf', 'dae']:
            flash('Текстуры можно добавлять только к 3D моделям', 'error')
            return redirect(url_for('view_file', file_id=model_id))
        
        if 'texture' not in request.files:
            flash('Файл текстуры не найден', 'error')
            return redirect(url_for('view_file', file_id=model_id))
        
        texture_file = request.files['texture']
        if texture_file.filename == '':
            flash('Файл не выбран', 'error')
            return redirect(url_for('view_file', file_id=model_id))
        
        texture_ext = texture_file.filename.lower().split('.')[-1]
        allowed_textures = ['jpg', 'jpeg', 'png', 'tga', 'dds', 'tiff', 'bmp', 'mtl']
        
        if texture_ext not in allowed_textures:
            flash(f'Недопустимый формат текстуры. Разрешены: {", ".join(allowed_textures)}', 'error')
            return redirect(url_for('view_file', file_id=model_id))
        
        texture_type = request.form.get('texture_type', 'diffuse')
        
        storage_name = f"texture_{uuid.uuid4().hex}.{texture_ext}"
        texture_path = os.path.join(app.config['UPLOAD_FOLDER'], storage_name)
        texture_file.save(texture_path)
        
        file_size = os.path.getsize(texture_path)
        
        new_texture = Texture(
            filename=texture_file.filename,
            storage_filename=storage_name,
            texture_type=texture_type,
            file_size=file_size,
            user_id=current_user.id,
            model_file_id=model.id
        )
        
        site.session.add(new_texture)
        site.session.commit()
        
        flash(f'Текстура "{texture_file.filename}" успешно загружена как {texture_type}', 'success')
        return redirect(url_for('view_file', file_id=model_id))

    @app.route('/upload_mtl/<int:model_id>', methods=['POST'])
    @login_required
    def upload_mtl(model_id):
        from models import Material
        
        model = File.query.get_or_404(model_id)
        if model.user_id != current_user.id and current_user.role != 'admin':
            abort(403)
        
        ext = model.filename.lower().split('.')[-1]
        if ext != 'obj':
            flash('MTL файлы можно загружать только для OBJ моделей', 'error')
            return redirect(url_for('view_file', file_id=model_id))
        
        if 'mtl_file' not in request.files:
            flash('MTL файл не найден', 'error')
            return redirect(url_for('view_file', file_id=model_id))
        
        mtl_file = request.files['mtl_file']
        if mtl_file.filename == '':
            flash('Файл не выбран', 'error')
            return redirect(url_for('view_file', file_id=model_id))
        
        mtl_ext = mtl_file.filename.lower().split('.')[-1]
        if mtl_ext != 'mtl':
            flash('Недопустимый формат. Ожидается .mtl файл', 'error')
            return redirect(url_for('view_file', file_id=model_id))
        
        storage_name = f"mtl_{uuid.uuid4().hex}.mtl"
        mtl_path = os.path.join(app.config['UPLOAD_FOLDER'], storage_name)
        mtl_file.save(mtl_path)
        
        file_size = os.path.getsize(mtl_path)
        
        mtl_record = File(
            filename=mtl_file.filename,
            storage_filename=storage_name,
            user_id=current_user.id,
            file_size=file_size,
            description=f"MTL материал для {model.filename}"
        )
        site.session.add(mtl_record)
        site.session.flush()
        
        materials = parse_mtl_file(mtl_path, mtl_record.id, model.id)
        
        for material_data in materials:
            material = Material(
                name=material_data['name'],
                mtl_file_id=mtl_record.id,
                model_file_id=model.id,
                ambient=material_data.get('Ka'),
                diffuse=material_data.get('Kd'),
                specular=material_data.get('Ks'),
                emission=material_data.get('Ke'),
                shininess=material_data.get('Ns', 0.0),
                transparency=material_data.get('d', 1.0),
                illumination=material_data.get('illum', 0),
                diffuse_map=material_data.get('map_Kd'),
                specular_map=material_data.get('map_Ks'),
                normal_map=material_data.get('map_Bump'),
                alpha_map=material_data.get('map_d')
            )
            site.session.add(material)
        
        site.session.commit()
        
        flash(f'MTL файл "{mtl_file.filename}" успешно загружен! Найдено {len(materials)} материалов.', 'success')
        return redirect(url_for('view_file', file_id=model_id))

    @app.route('/model_materials/<int:model_id>')
    @login_required
    def get_model_materials(model_id):
        from models import Material
        materials = Material.query.filter_by(model_file_id=model_id).all()
        materials_data = []
        for mat in materials:
            materials_data.append({
                'id': mat.id,
                'name': mat.name,
                'ambient': mat.ambient,
                'diffuse': mat.diffuse,
                'specular': mat.specular,
                'emission': mat.emission,
                'shininess': mat.shininess,
                'transparency': mat.transparency,
                'illumination': mat.illumination,
                'diffuse_map': mat.diffuse_map,
                'specular_map': mat.specular_map,
                'normal_map': mat.normal_map,
                'alpha_map': mat.alpha_map
            })
        return jsonify(materials_data)

    @app.route('/model_textures/<int:model_id>')
    @login_required
    def get_model_textures(model_id):
        model = File.query.get_or_404(model_id)
        textures = Texture.query.filter_by(model_file_id=model.id).all()
        textures_data = []
        for tex in textures:
            textures_data.append({
                'id': tex.id,
                'filename': tex.filename,
                'type': tex.texture_type,
                'url': url_for('get_raw_file', file_id=tex.id),
                'size': tex.file_size
            })
        return jsonify(textures_data)

    @app.route('/delete_texture/<int:texture_id>', methods=['POST'])
    @login_required
    def delete_texture(texture_id):
        texture = Texture.query.get_or_404(texture_id)
        if texture.user_id != current_user.id and current_user.role != 'admin':
            abort(403)
        
        texture_path = os.path.join(app.config['UPLOAD_FOLDER'], texture.storage_filename)
        if os.path.exists(texture_path):
            os.remove(texture_path)
        
        model_id = texture.model_file_id
        site.session.delete(texture)
        site.session.commit()
        
        flash('Текстура удалена', 'success')
        return redirect(url_for('view_file', file_id=model_id))

    @app.route('/delete_material/<int:material_id>', methods=['POST'])
    @login_required
    def delete_material(material_id):
        from models import Material
        material = Material.query.get_or_404(material_id)
        if material.mtl_file.user_id != current_user.id and current_user.role != 'admin':
            abort(403)
        site.session.delete(material)
        site.session.commit()
        return jsonify({'success': True, 'message': 'Материал удален'})

    @app.route('/delete_mtl/<int:mtl_file_id>', methods=['POST'])
    @login_required
    def delete_mtl(mtl_file_id):
        from models import Material, File
        mtl_record = File.query.get_or_404(mtl_file_id)
        if mtl_record.user_id != current_user.id and current_user.role != 'admin':
            abort(403)
        
        materials = Material.query.filter_by(mtl_file_id=mtl_file_id).all()
        for material in materials:
            site.session.delete(material)
        
        mtl_path = os.path.join(app.config['UPLOAD_FOLDER'], mtl_record.storage_filename)
        if os.path.exists(mtl_path):
            os.remove(mtl_path)
        
        site.session.delete(mtl_record)
        site.session.commit()
        
        return jsonify({'success': True, 'message': 'MTL файл и материалы удалены'})

    #мед для челов с манией величия
    
    @app.route("/admin")
    @login_required
    @admin_required
    def admin():
        users = User.query.order_by(User.id.desc()).all()
        total_users = User.query.count()
        total_files = File.query.count()

        last_week = datetime.utcnow() - timedelta(days=7)

        registrations_raw = (
            site.session.query(
                func.date(User.created_at),
                func.count(User.id)
            )
            .filter(User.created_at >= last_week)
            .group_by(func.date(User.created_at))
            .all()
        )
        registrations = [[str(row[0]), int(row[1])] for row in registrations_raw]

        uploads_raw = (
            site.session.query(
                func.date(File.upload_time),
                func.count(File.id)
            )
            .filter(File.upload_time >= last_week)
            .group_by(func.date(File.upload_time))
            .all()
        )
        uploads = [[str(row[0]), int(row[1])] for row in uploads_raw]

        roles_raw = (
            site.session.query(
                User.role,
                func.count(User.id)
            )
            .group_by(User.role)
            .all()
        )
        roles = [[str(row[0]), int(row[1])] for row in roles_raw]
        
        max_content_length = current_app.config.get('MAX_CONTENT_LENGTH', 10737418240)

        return render_template(
            "admin.html",
            users=users,
            total_users=total_users,
            total_files=total_files,
            registrations=registrations,
            uploads=uploads,
            roles=roles,
            max_content_length=max_content_length,
            now=datetime.utcnow()
        )

    @app.route("/admin/toggle-block/<int:user_id>", methods=["POST"])
    @login_required
    @admin_required
    def admin_toggle_block(user_id):
        user = User.query.get_or_404(user_id)
        if user.id == current_user.id:
            flash("Нельзя заблокировать самого себя", "danger")
            return redirect(url_for("admin"))
        user.is_blocked = not user.is_blocked
        site.session.commit()
        flash("Статус пользователя изменён", "success")
        return redirect(url_for("admin"))
        
    @app.route("/admin/delete-user/<int:user_id>", methods=["POST"])
    @login_required
    @admin_required
    def admin_delete_user(user_id):
        user = User.query.get_or_404(user_id)
        if user.id == current_user.id:
            flash("Нельзя удалить самого себя", "danger")
            return redirect(url_for("admin"))
        
        files = File.query.filter_by(user_id=user.id).all()
        for file in files:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.storage_filename)
            if os.path.exists(file_path):
                os.remove(file_path)
            site.session.delete(file)
        
        site.session.delete(user)
        site.session.commit()
        flash("Пользователь и его файлы удалены", "success")
        return redirect(url_for("admin"))
    
    @app.route("/admin/files")
    @login_required
    @admin_required
    def admin_all_files():
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        search = request.args.get('search', '', type=str)
        user_filter = request.args.get('user', '', type=str)
        ext_filter = request.args.get('ext', '', type=str)
        
        query = File.query
        
        if search:
            query = query.filter(File.filename.ilike(f'%{search}%'))
        if user_filter and user_filter.isdigit():
            query = query.filter(File.user_id == int(user_filter))
        if ext_filter:
            query = query.filter(File.filename.ilike(f'%.{ext_filter}'))
        
        files = query.order_by(File.upload_time.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        users = User.query.order_by(User.username).all()
        
        total_size = site.session.query(func.sum(File.file_size)).scalar() or 0
        total_size_mb = total_size / (1024 * 1024)
        total_files = File.query.count()
        
        extensions = {}
        all_files = File.query.all()
        for file in all_files:
            ext = file.filename.split('.')[-1].lower() if '.' in file.filename else 'без расширения'
            extensions[ext] = extensions.get(ext, 0) + 1
        top_extensions = sorted(extensions.items(), key=lambda x: x[1], reverse=True)[:10]
        
        size_stats = {'small': 0, 'medium': 0, 'large': 0, 'huge': 0}
        for file in all_files:
            size_mb = (file.file_size or 0) / (1024 * 1024)
            if size_mb < 1:
                size_stats['small'] += 1
            elif size_mb < 10:
                size_stats['medium'] += 1
            elif size_mb < 100:
                size_stats['large'] += 1
            else:
                size_stats['huge'] += 1
        
        return render_template(
            "admin_files.html", 
            files=files,
            users=users,
            total_size_mb=total_size_mb,
            total_files=total_files,
            top_extensions=top_extensions,
            size_stats=size_stats,
            search=search,
            user_filter=user_filter,
            ext_filter=ext_filter,
            now=datetime.utcnow()
        )
    
    @app.route("/admin/delete-file/<int:file_id>", methods=["POST"])
    @login_required
    @admin_required
    def admin_delete_file(file_id):
        file_record = File.query.get_or_404(file_id)

        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_record.storage_filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                app.logger.error(f"Error deleting file {file_path}: {e}")
        
        from models import Texture
        textures = Texture.query.filter_by(model_file_id=file_record.id).all()
        for texture in textures:
            texture_path = os.path.join(app.config['UPLOAD_FOLDER'], texture.storage_filename)
            if os.path.exists(texture_path):
                try:
                    os.remove(texture_path)
                except:
                    pass
            site.session.delete(texture)
        
        from models import Material
        materials = Material.query.filter_by(mtl_file_id=file_record.id).all()
        for material in materials:
            site.session.delete(material)
        
        site.session.delete(file_record)
        site.session.commit()

        flash("Файл удалён администратором", "success")
        return redirect(request.referrer or url_for("admin_all_files"))
    
    @app.route("/admin/files/bulk-delete", methods=["POST"])
    @login_required
    @admin_required
    def admin_bulk_delete_files():
        file_ids = request.form.getlist('file_ids')
        
        if not file_ids:
            flash('Файлы не выбраны', 'error')
            return redirect(request.referrer or url_for('admin_all_files'))
        
        deleted = 0
        failed = 0
        
        for file_id in file_ids:
            try:
                file_record = File.query.get(int(file_id))
                if file_record:
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_record.storage_filename)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    
                    from models import Texture
                    textures = Texture.query.filter_by(model_file_id=file_record.id).all()
                    for texture in textures:
                        texture_path = os.path.join(app.config['UPLOAD_FOLDER'], texture.storage_filename)
                        if os.path.exists(texture_path):
                            os.remove(texture_path)
                        site.session.delete(texture)
                    
                    from models import Material
                    materials = Material.query.filter_by(mtl_file_id=file_record.id).all()
                    for material in materials:
                        site.session.delete(material)
                    
                    site.session.delete(file_record)
                    deleted += 1
            except Exception as e:
                app.logger.error(f"Error deleting file {file_id}: {e}")
                failed += 1
        
        site.session.commit()
        
        flash(f'Удалено файлов: {deleted}. Ошибок: {failed}', 'success')
        return redirect(request.referrer or url_for('admin_all_files'))
    
    @app.route("/admin/files/export")
    @login_required
    @admin_required
    def admin_export_files():
        files = File.query.order_by(File.upload_time.desc()).all()
        
        output = StringIO()
        writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
        
        writer.writerow([
            'ID', 'Имя файла', 'Размер (байт)', 'Размер (МБ)', 
            'Пользователь ID', 'Имя пользователя', 'Email пользователя',
            'Дата загрузки', 'Расширение', 'Публичный', 'Скачиваний', 'Описание'
        ])
        
        for file in files:
            user = User.query.get(file.user_id)
            ext = file.filename.split('.')[-1].lower() if '.' in file.filename else 'без расширения'
            writer.writerow([
                file.id, file.filename, file.file_size or 0,
                f"{round((file.file_size or 0) / (1024 * 1024), 2)}",
                file.user_id, user.username if user else 'Unknown',
                user.email if user else 'Unknown',
                file.upload_time.strftime('%Y-%m-%d %H:%M:%S'),
                ext, 'Да' if file.is_public else 'Нет',
                file.share_downloads or 0, file.description or ''
            ])
        
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv; charset=utf-8-sig',
            headers={'Content-Disposition': 'attachment; filename=files_export.csv'}
        )
    
    @app.route("/admin/files/cleanup", methods=["POST"])
    @login_required
    @admin_required
    def admin_cleanup_files():
        days = request.form.get('days', 30, type=int)
        delete_orphaned = request.form.get('delete_orphaned', False, type=bool)
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        deleted_count = 0
        failed_count = 0
        
        if delete_orphaned:
            orphaned_files = File.query.filter(~File.user_id.in_(site.session.query(User.id))).all()
        else:
            orphaned_files = File.query.filter(
                or_(
                    File.last_accessed.is_(None),
                    File.last_accessed < cutoff_date
                ),
                File.upload_time < cutoff_date
            ).all()
        
        for file in orphaned_files:
            try:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.storage_filename)
                if os.path.exists(file_path):
                    os.remove(file_path)
                
                from models import Texture
                textures = Texture.query.filter_by(model_file_id=file.id).all()
                for texture in textures:
                    texture_path = os.path.join(app.config['UPLOAD_FOLDER'], texture.storage_filename)
                    if os.path.exists(texture_path):
                        os.remove(texture_path)
                    site.session.delete(texture)
                
                from models import Material
                materials = Material.query.filter_by(mtl_file_id=file.id).all()
                for material in materials:
                    site.session.delete(material)
                
                site.session.delete(file)
                deleted_count += 1
            except Exception as e:
                app.logger.error(f"Error cleaning up file {file.id}: {e}")
                failed_count += 1
        
        site.session.commit()
        
        flash(f'Очистка завершена. Удалено файлов: {deleted_count}. Ошибок: {failed_count}', 'success')
        return redirect(url_for('admin_all_files'))
    
    @app.route("/admin/files/stats")
    @login_required
    @admin_required
    def admin_files_stats():
        total_files = File.query.count()
        total_size = site.session.query(func.sum(File.file_size)).scalar() or 0
        public_files = File.query.filter_by(is_public=True).count()
        
        last_30_days = datetime.utcnow() - timedelta(days=30)
        daily_uploads = site.session.query(
            func.date(File.upload_time),
            func.count(File.id)
        ).filter(File.upload_time >= last_30_days).group_by(func.date(File.upload_time)).all()
        
        daily_data = [{'date': str(row[0]), 'count': int(row[1])} for row in daily_uploads]
        
        top_users = site.session.query(
            File.user_id,
            func.count(File.id).label('file_count'),
            func.sum(File.file_size).label('total_size')
        ).group_by(File.user_id).order_by(func.count(File.id).desc()).limit(10).all()
        
        users_data = []
        for user in top_users:
            user_obj = User.query.get(user[0])
            users_data.append({
                'user_id': user[0],
                'username': user_obj.username if user_obj else 'Unknown',
                'file_count': int(user[1]),
                'total_size_mb': round((user[2] or 0) / (1024 * 1024), 2)
            })
        
        extensions = {}
        all_files = File.query.all()
        for file in all_files:
            ext = file.filename.split('.')[-1].lower() if '.' in file.filename else 'без расширения'
            extensions[ext] = extensions.get(ext, 0) + 1
        extensions_data = [{'ext': k, 'count': v} for k, v in sorted(extensions.items(), key=lambda x: x[1], reverse=True)[:15]]
        
        return jsonify({
            'total_files': total_files,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'public_files': public_files,
            'daily_uploads': daily_data,
            'top_users': users_data,
            'top_extensions': extensions_data
        })

    #чатик
    @app.route('/chat')
    @login_required
    def lan_chat():
        messages = ChatMessage.query.order_by(ChatMessage.created_at.asc()).all()
        return render_template('lan_chat.html', messages=messages)

    @app.route('/chat/edit/<int:message_id>', methods=['POST'])
    @login_required
    def edit_chat_message(message_id):
        msg = ChatMessage.query.get_or_404(message_id)
        
        if msg.user_id != current_user.id:
            abort(403)
        
        new_message = request.form.get('message', '').strip()
        if not new_message:
            flash('Сообщение не может быть пустым', 'error')
            return redirect(url_for('lan_chat'))
        
        msg.message = escape(new_message)
        msg.edited_at = datetime.utcnow()
        site.session.commit()
        
        
        if msg.is_private and msg.recipient_id:
            socketio.emit('message_edited', {
                'id': msg.id,
                'message': new_message,
                'edited': True
            }, room=f"user_{msg.recipient_id}")
            socketio.emit('message_edited', {
                'id': msg.id,
                'message': new_message,
                'edited': True
            }, room=f"user_{msg.user_id}")
        else:
            socketio.emit('message_edited', {
                'id': msg.id,
                'message': new_message,
                'edited': True
            })
        
        flash('Сообщение изменено', 'success')
        return redirect(url_for('lan_chat'))

    @app.route('/chat/delete/<int:message_id>', methods=['POST'])
    @login_required
    def delete_chat_message(message_id):
        msg = ChatMessage.query.get_or_404(message_id)
        
        if current_user.role == 'admin' or msg.user_id == current_user.id:
            
            if msg.is_private and msg.recipient_id:
                socketio.emit('message_deleted', {'id': msg.id}, room=f"user_{msg.recipient_id}")
                socketio.emit('message_deleted', {'id': msg.id}, room=f"user_{msg.user_id}")
            else:
                socketio.emit('message_deleted', {'id': msg.id})
            
            site.session.delete(msg)
            site.session.commit()
            flash('Сообщение удалено', 'success')
        else:
            abort(403)
        
        return redirect(url_for('lan_chat'))

    @app.route('/chat/copy/<int:message_id>', methods=['GET'])
    @login_required
    def copy_chat_message(message_id):
        msg = ChatMessage.query.get_or_404(message_id)
        return jsonify({'message': msg.message})


    #api для чатика\
    @app.route('/api/users')
    @login_required
    def api_users():
        """Получить список всех пользователей для упоминаний"""
        users = User.query.all()
        return jsonify({
            'users': [{
                'id': u.id,
                'username': u.username,
                'avatar': url_for('avatar', filename=u.avatar) if u.avatar else url_for('static', filename='default_avatar.png')
            } for u in users if u.id != current_user.id]
        })

    @app.route('/api/chat/history')
    @login_required
    def api_chat_history():
        """Получить историю сообщений с пагинацией"""
        chat_type = request.args.get('chat_type', 'public')
        user_id = request.args.get('user_id', type=int)
        page = request.args.get('page', 0, type=int)
        limit = request.args.get('limit', 50, type=int)
        user_tz = request.headers.get('X-Timezone', 'Europe/Moscow')
        
        if chat_type == 'public':
            query = ChatMessage.query.filter_by(is_private=False)
        elif chat_type == 'dm' and user_id:
            query = ChatMessage.query.filter(
                ((ChatMessage.user_id == current_user.id) & (ChatMessage.recipient_id == user_id)) |
                ((ChatMessage.user_id == user_id) & (ChatMessage.recipient_id == current_user.id))
            ).filter(ChatMessage.is_private == True)
        else:
            return jsonify({'messages': [], 'has_more': False})
        
        messages = query.order_by(ChatMessage.created_at.desc()) \
                        .offset(page * limit) \
                        .limit(limit + 1) \
                        .all()
        
        has_more = len(messages) > limit
        messages = messages[:limit]
        
        result_messages = []
        for m in reversed(messages):
            utc_time = m.created_at.replace(tzinfo=timezone.utc)
            try:
                local_time = utc_time.astimezone(ZoneInfo(user_tz))
            except:
                local_time = utc_time.astimezone(ZoneInfo("Europe/Moscow"))
            
            result_messages.append({
                'id': m.id,
                'message': m.message,
                'username': m.user.username,
                'user_id': m.user.id,
                'avatar': url_for('avatar', filename=m.user.avatar) if m.user.avatar else url_for('static', filename='default_avatar.png'),
                'created_at': m.created_at.isoformat(),
                'time': local_time.strftime('%H:%M'),
                'full_date': local_time.strftime('%d.%m.%Y'),
                'full_datetime': local_time.strftime('%d.%m.%Y %H:%M:%S'),
                'is_private': m.is_private,
                'edited': m.edited_at is not None,
                'reply': m.reply,
                'recipient_id': m.recipient_id
            })
        
        return jsonify({
            'messages': result_messages,
            'has_more': has_more
        })

    @app.route('/api/dm/list')
    @login_required
    def api_dm_list():
        """список личных диалогов"""
        from sqlalchemy import or_, and_
        
        user_ids = set()
        
        sent_messages = ChatMessage.query.filter(
            ChatMessage.user_id == current_user.id,
            ChatMessage.is_private == True,
            ChatMessage.recipient_id.isnot(None)
        ).with_entities(ChatMessage.recipient_id).distinct().all()
        
        for msg in sent_messages:
            if msg.recipient_id:
                user_ids.add(msg.recipient_id)
        
       
        received_messages = ChatMessage.query.filter(
            ChatMessage.recipient_id == current_user.id,
            ChatMessage.is_private == True
        ).with_entities(ChatMessage.user_id).distinct().all()
        
        for msg in received_messages:
            user_ids.add(msg.user_id)
        
        result = []
        
        for other_user_id in user_ids:
            other_user = User.query.get(other_user_id)
            
            if not other_user:
                continue
            
            
            unread = ChatMessage.query.filter(
                ChatMessage.user_id == other_user_id,
                ChatMessage.recipient_id == current_user.id,
                ChatMessage.is_private == True,
                ChatMessage.is_read == False
            ).count()
            
          
            last_msg = ChatMessage.query.filter(
                or_(
                    and_(ChatMessage.user_id == current_user.id, ChatMessage.recipient_id == other_user_id),
                    and_(ChatMessage.user_id == other_user_id, ChatMessage.recipient_id == current_user.id)
                ),
                ChatMessage.is_private == True
            ).order_by(ChatMessage.created_at.desc()).first()
            
            result.append({
                'user_id': other_user.id,
                'username': other_user.username,
                'avatar': url_for('avatar', filename=other_user.avatar) if other_user.avatar else url_for('static', filename='default_avatar.png'),
                'unread': unread,
                'last_message': last_msg.message[:50] if last_msg else '',
                'last_time': last_msg.created_at.strftime('%H:%M') if last_msg else ''
            })
        
        
        result.sort(key=lambda x: x['last_time'], reverse=True)
        
        return jsonify({'dms': result})

    @app.route('/api/messages/read/<int:message_id>', methods=['POST'])
    @login_required
    def mark_message_read(message_id):
        """Отметить сообщение как прочитанное"""
        msg = ChatMessage.query.get_or_404(message_id)
        
        if msg.recipient_id == current_user.id and not msg.is_read:
            msg.is_read = True
            site.session.commit()
            return jsonify({'success': True})
        
        return jsonify({'success': False})
    
    @app.route('/api/set_timezone', methods=['POST'])
    @login_required
    def set_timezone():
        """Сохранить часовой пояс пользователя"""
        data = request.get_json()
        timezone_str = data.get('timezone', 'Europe/Moscow')
        
        
        try:
            ZoneInfo(timezone_str)
            current_user.timezone = timezone_str
            site.session.commit()
            return jsonify({'success': True, 'timezone': timezone_str})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 400

   
   #боль в дырка попа 2 (чанковая загрузка)
    chunk_manager.init_app(app)

    @app.route('/api/upload/init', methods=['POST'])
    @login_required
    def init_chunk_upload():
        """Инициализация чанковой загрузки"""
        data = request.get_json()
        
        filename = data.get('filename')
        file_size = data.get('file_size')
        total_chunks = data.get('total_chunks')
        
        if not filename or not file_size:
            return jsonify({'error': 'Не указаны параметры'}), 400
        
        
        max_size = app.config.get('MAX_FILE_SIZE', 100 * 1024 * 1024 * 1024)
        if file_size > max_size:
            return jsonify({
                'error': f'Файл слишком большой. Максимум {max_size // (1024**3)}GB'
            }), 400
        
        
        session_id = uuid.uuid4().hex
        
        
        session_dir = os.path.join(app.config['TEMP_UPLOAD_DIR'], session_id)
        os.makedirs(session_dir, exist_ok=True)
        
        import json
        info = {
            'session_id': session_id,
            'filename': filename,
            'file_size': file_size,
            'total_chunks': total_chunks,
            'uploaded_chunks': [],
            'created_at': datetime.utcnow().isoformat(),
            'last_update': datetime.utcnow().isoformat()
        }
        
        info_path = os.path.join(session_dir, 'info.json')
        with open(info_path, 'w', encoding='utf-8') as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
        
        return jsonify({
            'session_id': session_id,
            'chunk_size': app.config.get('CHUNK_SIZE', 5 * 1024 * 1024),
            'total_chunks': total_chunks
        })


    @app.route('/api/upload/chunk', methods=['POST'])
    @login_required
    def upload_chunk():
        """Загрузка чанка"""
        session_id = request.form.get('session_id')
        chunk_index = request.form.get('chunk_index', type=int)
        total_chunks = request.form.get('total_chunks', type=int)
        filename = request.form.get('filename')
        file_size = request.form.get('file_size', type=int)
        
        if 'chunk' not in request.files:
            return jsonify({'error': 'Чанк не найден'}), 400
        
        chunk = request.files['chunk']
        
        if not session_id or chunk_index is None:
            return jsonify({'error': 'Неверные параметры'}), 400
        
        try:
            result = chunk_manager.save_chunk(
                chunk=chunk,
                chunk_index=chunk_index,
                total_chunks=total_chunks,
                session_id=session_id,
                filename=filename,
                file_size=file_size
            )
            
            return jsonify(result)
            
        except Exception as e:
            app.logger.error(f"Chunk upload error: {e}")
            return jsonify({'error': str(e)}), 500


    @app.route('/api/upload/complete', methods=['POST'])
    @login_required
    def complete_chunk_upload():
        """сборка файла"""
        data = request.get_json()
        
        session_id = data.get('session_id')
        description = data.get('description')
        batch_id = data.get('batch_id')
        
        if not session_id:
            return jsonify({'error': 'Не указан session_id'}), 400
        
        try:
           
            new_file = chunk_manager.assemble_file(
                session_id=session_id,
                user_id=current_user.id,
                description=description,
                batch_id=batch_id
            )
            
            site.session.add(new_file)
            site.session.commit()
            
            return jsonify({
                'success': True,
                'file_id': new_file.id,
                'filename': new_file.filename,
                'redirect': url_for('index')
            })
            
        except Exception as e:
            app.logger.error(f"Complete upload error: {e}")
            site.session.rollback()
            return jsonify({'error': str(e)}), 500


    @app.route('/api/upload/progress/<session_id>', methods=['GET'])
    @login_required
    def get_upload_progress(session_id):
        """ прогресс загрузки"""
        progress = chunk_manager.get_progress(session_id)
        
        if not progress:
            return jsonify({'error': 'Сессия не найдена'}), 404
        
        return jsonify(progress)


    @app.route('/api/upload/abort/<session_id>', methods=['DELETE'])
    @login_required
    def abort_chunk_upload(session_id):
        """остановит загрузку"""
        success = chunk_manager.abort_upload(session_id)
        
        return jsonify({'success': success})


    @app.route('/api/upload/resume/<session_id>', methods=['GET'])
    @login_required
    def get_resume_info(session_id):
        """востановление процесса """
        info = chunk_manager.get_upload_session(session_id)
        
        if not info:
            return jsonify({'error': 'Сессия не найдена'}), 404
        
        return jsonify({
            'session_id': session_id,
            'filename': info['filename'],
            'file_size': info['file_size'],
            'total_chunks': info['total_chunks'],
            'uploaded_chunks': info['uploaded_chunks']
        })

   
 #авто отчистка чанков
    import atexit

    def cleanup_chunks_on_exit():
        """Очистка чанков """
        temp_dir = app.config.get('TEMP_UPLOAD_DIR', 'static/uploads/temp')
        if os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir)
            app.logger.info("Временные чанки очищены")

    atexit.register(cleanup_chunks_on_exit)

    
    def start_chunk_cleanup():
        """Фоновый поток для очистки чанков"""
        import threading
        import time
        
        def cleanup_loop():
            while True:
                time.sleep(3600)  
                with app.app_context():
                    cleaned = chunk_manager.cleanup_old_chunks(24)
                    if cleaned > 0:
                        app.logger.info(f"Очищено {cleaned} старых сессий чанков")
        
        thread = threading.Thread(target=cleanup_loop, daemon=True)
        thread.start()

    start_chunk_cleanup()

    #обработчики для чатика

    
    online_users_set = set()

    @socketio.on('connect')
    def handle_connect():
        app.logger.info(f"Client connected: {request.sid}")
        if current_user.is_authenticated:
            
            join_room(f"user_{current_user.id}")
            online_users_set.add(current_user.id)
            
            socketio.emit('user_online_update', {'users': list(online_users_set)})

    @socketio.on('disconnect')
    def handle_disconnect():
        app.logger.info(f"Client disconnected: {request.sid}")
        if current_user.is_authenticated:
            leave_room(f"user_{current_user.id}")
            online_users_set.discard(current_user.id)
            socketio.emit('user_online_update', {'users': list(online_users_set)})

    @socketio.on('send_message')
    def handle_send_message(data):
        if current_user.is_authenticated:
            message = data.get('message', '').strip()
            reply = data.get('reply')
            is_private = data.get('is_private', False)
            recipient_id = data.get('recipient_id')
            user_tz = data.get('timezone', 'Europe/Moscow')  
            
            if message:
                try:
                    
                    mentions = []
                    import re
                    mention_pattern = r'@(\w+)'
                    found_mentions = re.findall(mention_pattern, message)
                    for username in found_mentions:
                        user = User.query.filter_by(username=username).first()
                        if user and user.id != current_user.id:
                            mentions.append(user.id)
                    
                    new_msg = ChatMessage(
                        user_id=current_user.id,
                        message=message,
                        reply=reply,
                        is_private=is_private,
                        recipient_id=recipient_id if is_private else None,
                        mentions=json.dumps(mentions) if mentions else None
                    )
                    site.session.add(new_msg)
                    site.session.commit()
                    
                    
                    utc_time = new_msg.created_at.replace(tzinfo=timezone.utc)
                    try:
                        local_time = utc_time.astimezone(ZoneInfo(user_tz))
                    except:
                        local_time = utc_time.astimezone(ZoneInfo("Europe/Moscow"))
                    
                    msg_data = {
                        'id': new_msg.id,
                        'user_id': current_user.id,
                        'username': current_user.username,
                        'message': message,
                        'reply': reply,
                        'avatar': url_for('avatar', filename=current_user.avatar) if current_user.avatar else url_for('static', filename='default_avatar.png'),
                        'time': local_time.strftime("%H:%M"),
                        'full_datetime': local_time.strftime("%d.%m.%Y %H:%M:%S"),
                        'created_at': new_msg.created_at.isoformat(),
                        'edited': False,
                        'is_private': is_private,
                        'recipient_id': recipient_id,
                        'mentions': mentions
                    }
                    
                   
                    socketio.emit('message', msg_data, room=f"user_{current_user.id}")
                    
                  
                    if is_private and recipient_id:
                        recipient = User.query.get(recipient_id)
                        if recipient:
                            recipient_tz = getattr(recipient, 'timezone', 'Europe/Moscow')
                            try:
                                recipient_local = utc_time.astimezone(ZoneInfo(recipient_tz))
                            except:
                                recipient_local = utc_time.astimezone(ZoneInfo("Europe/Moscow"))
                            
                            msg_data_recipient = msg_data.copy()
                            msg_data_recipient['time'] = recipient_local.strftime("%H:%M")
                            msg_data_recipient['full_datetime'] = recipient_local.strftime("%d.%m.%Y %H:%M:%S")
                            
                            socketio.emit('message', msg_data_recipient, room=f"user_{recipient_id}")
                    else:
                        socketio.emit('message', msg_data)
                    
                    for mention_id in mentions:
                        if mention_id != current_user.id:
                            socketio.emit('mention_notification', {
                                'from_user': current_user.username,
                                'message': message[:100],
                                'message_id': new_msg.id
                            }, room=f"user_{mention_id}")
                    
                    app.logger.info(f"Message sent: {current_user.username}: {message[:50]}")
                    
                except Exception as e:
                    app.logger.error(f"Error sending message: {e}")
                    site.session.rollback()
        else:
            app.logger.warning("Unauthenticated user tried to send message")

    @socketio.on('typing')
    def handle_typing(data):
        if current_user.is_authenticated:
            is_private = data.get('is_private', False)
            recipient_id = data.get('recipient_id')
            
            typing_data = {
                'username': current_user.username,
                'user_id': current_user.id,
                'is_private': is_private
            }
            
            if is_private and recipient_id:
                socketio.emit('typing', typing_data, room=f"user_{recipient_id}")
            else:
                socketio.emit('typing', typing_data)
            
            socketio.emit('typing', typing_data, room=f"user_{current_user.id}")

    @socketio.on('stop_typing')
    def handle_stop_typing(data):
        if current_user.is_authenticated:
            is_private = data.get('is_private', False)
            recipient_id = data.get('recipient_id')
            
            typing_data = {
                'username': current_user.username,
                'user_id': current_user.id,
                'is_private': is_private,
                'stopped': True
            }
            
            if is_private and recipient_id:
                socketio.emit('typing_stopped', typing_data, room=f"user_{recipient_id}")
            else:
                socketio.emit('typing_stopped', typing_data)

    @socketio.on('check_online')
    def handle_check_online():
        if current_user.is_authenticated:
            socketio.emit('user_online_update', {'users': list(online_users_set)}, room=f"user_{current_user.id}")

    @socketio.on('edit_message')
    def handle_edit_message(data):
        if current_user.is_authenticated:
            msg_id = data.get('id')
            new_message = data.get('message', '').strip()
            
            if msg_id and new_message:
                msg = ChatMessage.query.get(msg_id)
                if msg and msg.user_id == current_user.id:
                    msg.message = new_message
                    msg.edited_at = datetime.utcnow()
                    site.session.commit()
                    
                    edit_data = {
                        'id': msg.id,
                        'message': new_message,
                        'edited': True
                    }
                    
                    if msg.is_private and msg.recipient_id:
                        socketio.emit('message_edited', edit_data, room=f"user_{msg.recipient_id}")
                        socketio.emit('message_edited', edit_data, room=f"user_{msg.user_id}")
                    else:
                        socketio.emit('message_edited', edit_data)
                    
                    app.logger.info(f"Message edited: {msg_id}")

    @socketio.on('delete_message')
    def handle_delete_message(data):
        if current_user.is_authenticated:
            msg_id = data.get('id')
            if msg_id:
                msg = ChatMessage.query.get(msg_id)
                if msg and (current_user.role == 'admin' or msg.user_id == current_user.id):
                    delete_data = {'id': msg.id}
                    
                    if msg.is_private and msg.recipient_id:
                        socketio.emit('message_deleted', delete_data, room=f"user_{msg.recipient_id}")
                        socketio.emit('message_deleted', delete_data, room=f"user_{msg.user_id}")
                    else:
                        socketio.emit('message_deleted', delete_data)
                    
                    site.session.delete(msg)
                    site.session.commit()
                    app.logger.info(f"Message deleted: {msg_id}")

    @socketio.on('join_dm_room')
    def handle_join_dm_room(data):
        """Присоединение к комнате личного чата"""
        if current_user.is_authenticated:
            other_user_id = data.get('user_id')
            if other_user_id:
                room_name = f"dm_{min(current_user.id, other_user_id)}_{max(current_user.id, other_user_id)}"
                join_room(room_name)
                app.logger.info(f"User {current_user.id} joined DM room {room_name}")

    @socketio.on('leave_dm_room')
    def handle_leave_dm_room(data):
        """Выход из комнаты личного чата"""
        if current_user.is_authenticated:
            other_user_id = data.get('user_id')
            if other_user_id:
                room_name = f"dm_{min(current_user.id, other_user_id)}_{max(current_user.id, other_user_id)}"
                leave_room(room_name)
                app.logger.info(f"User {current_user.id} left DM room {room_name}")

    @socketio.on('mark_read')
    def handle_mark_read(data):
        """Отметить сообщения как прочитанные"""
        if current_user.is_authenticated:
            message_ids = data.get('message_ids', [])
            for msg_id in message_ids:
                msg = ChatMessage.query.get(msg_id)
                if msg and msg.recipient_id == current_user.id and not msg.is_read:
                    msg.is_read = True
            site.session.commit()

   #УРААААаАААа победа , инициируем все это дермо
    
    socketio.init_app(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        ping_timeout=60,
        ping_interval=25,
        manage_session=False,
        path='/socket.io'
    )
    
    chunk_manager.init_app(app)

    with app.app_context():
        site.create_all()
    
    return app