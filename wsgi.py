import sys
import socket
import webbrowser
import os
import datetime
import shutil
import logging
import logging.handlers
import time
import threading
import functools
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, 
                             QTextEdit, QVBoxLayout, QWidget, QHBoxLayout,
                             QLabel, QFrame, QSizePolicy, QMessageBox,
                             QFileDialog, QProgressBar, QDialog, QListWidget,
                             QListWidgetItem, QTabWidget)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QFont, QPalette, QColor, QIcon, QPixmap, QAction

try:
    from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser, ServiceListener
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False
    print("Zeroconf не установлен, работаю без автообнаружения в сети")

from app import create_app
from app import socketio

# ============= КОНСТАНТЫ И КОНФИГУРАЦИЯ =============
APP_NAME = "Space Share"
APP_VERSION = "2.0.0"
DEFAULT_PORT = 5000
DEFAULT_HOST = '0.0.0.0'
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 5    
PORT_RANGE_START = 5000
PORT_RANGE_END = 5010
BROADCAST_PORT = 5001
DISCOVERY_MSG = "SPACE_SHARE_DISCOVERY"
RESPONSE_MSG = "SPACE_SHARE_RESPONSE"

# Определение пути к папке с приложением
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Пути к папкам
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

# Цвета для разных тем
COLORS = {
    'dark': {
        'bg': '#121212', 'fg': '#f0f0f0', 'success': '#4caf50',
        'error': '#f44336', 'warning': '#ff9800', 'info': '#2196f3'
    },
    'light': {
        'bg': '#f5f5f5', 'fg': '#333333', 'success': '#4caf50',
        'error': '#f44336', 'warning': '#ff9800', 'info': '#2196f3'
    }
}


# ============= ДЕКОРАТОРЫ =============
def safe_execution(func):
    """Декоратор для безопасного выполнения функций"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(f"Error in {func.__name__}: {e}", exc_info=True)
            if len(args) > 0 and hasattr(args[0], 'logger'):
                args[0].logger.error(f"Error in {func.__name__}: {e}")
            return None
    return wrapper


# ============= КЛАСС КОНФИГУРАЦИИ =============
class Config:
    """Централизованная конфигурация"""
    def __init__(self):
        self.base_dir = BASE_DIR
        self.templates_dir = TEMPLATES_DIR
        self.static_dir = STATIC_DIR
        self.logs_dir = LOGS_DIR
        self.port = DEFAULT_PORT
        self.host = DEFAULT_HOST
        self.theme = 'dark'
    
    def ensure_dirs(self):
        """Создание всех директорий"""
        folders_created = []
        for dir_path in [self.templates_dir, self.static_dir, self.logs_dir]:
            if not os.path.exists(dir_path):
                os.makedirs(dir_path, exist_ok=True)
                folders_created.append(os.path.basename(dir_path))
        return folders_created


# ============= КЛАСС ДЛЯ ЛОГИРОВАНИЯ =============
class ServerLogger:
    """Улучшенный логгер с ротацией и форматированием"""
    
    LEVEL_PREFIX = {
        'INFO': '[INFO]',
        'WARNING': '[WARNING]',
        'ERROR': '[ERROR]',
        'DEBUG': '[DEBUG]',
        'SECURITY': '[SECURITY]',
        'SERVER': '[SERVER]',
        'DISCOVERY': '[DISCOVERY]'
    }
    
    def debug(self, msg):
        self.log('DEBUG', msg)

    def __init__(self, config, gui_signal=None):
        self.config = config
        self.gui_signal = gui_signal
        self.loggers = {}
        self._setup_logging()
    
    def _setup_logging(self):
        """Настройка всех логгеров"""
        os.makedirs(self.config.logs_dir, exist_ok=True)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        for name in ['app', 'error', 'security', 'discovery']:
            logger = logging.getLogger(f'{APP_NAME}.{name}')
            logger.setLevel(logging.DEBUG)
            logger.propagate = False
            
            log_file = os.path.join(
                self.config.logs_dir, 
                f'{name}_{datetime.datetime.now().strftime("%Y%m%d")}.log'
            )
            handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=MAX_LOG_SIZE, 
                backupCount=LOG_BACKUP_COUNT, encoding='utf-8'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            
            self.loggers[name] = logger
    
    def log(self, level, message):
        """Универсальный метод логирования"""
        prefix = self.LEVEL_PREFIX.get(level, '[LOG]')
        timestamp = datetime.datetime.now().strftime('%H:%M:%S')
        
        if level.lower() in self.loggers:
            log_methods = {
                'INFO': 'info', 'WARNING': 'warning', 
                'ERROR': 'error', 'DEBUG': 'debug'
            }
            method_name = log_methods.get(level, 'info')
            getattr(self.loggers[level.lower()], method_name, lambda x: None)(message)
        
        if self.gui_signal:
            self.gui_signal.emit(f"{prefix} [{timestamp}] {message}")
    
    def info(self, msg): 
        self.log('INFO', msg)
    
    def warning(self, msg): 
        self.log('WARNING', msg)
    
    def error(self, msg, exc=False):
        """Логирование ошибки"""
        if exc:
            import traceback
            msg += f"\n{traceback.format_exc()}"
        self.log('ERROR', msg)
    
    def security(self, msg): 
        self.log('SECURITY', msg)
    
    def server(self, msg): 
        self.log('SERVER', msg)
    
    def discovery(self, msg):
        self.log('DISCOVERY', msg)


# ============= КЛАСС ДЛЯ ОБНАРУЖЕНИЯ СЕРВЕРОВ =============
class ZeroconfListener(ServiceListener):
    """Слушатель Zeroconf сервисов"""
    def __init__(self, parent):
        self.parent = parent
        self.services = {}
    
    def add_service(self, zc, type_, name):
        try:
            info = zc.get_service_info(type_, name)
            if info and info.addresses:
                ip = socket.inet_ntoa(info.addresses[0])
                port = info.port
                server_data = {
                    'id': f"{ip}:{port}",
                    'name': name,
                    'ip': ip,
                    'port': port,
                    'address': f"http://{ip}:{port}",
                    'type': 'zeroconf',
                    'properties': info.properties
                }
                self.parent.server_found.emit(server_data)
                self.services[name] = server_data
        except Exception as e:
            pass
    
    def remove_service(self, zc, type_, name):
        if name in self.services:
            self.parent.server_lost.emit(self.services[name]['id'])
            del self.services[name]
    
    def update_service(self, zc, type_, name):
        pass


class ServerDiscovery(QThread):
    """Поток для обнаружения других серверов в сети"""
    server_found = pyqtSignal(dict)
    server_lost = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    
    def __init__(self, local_port=5000):
        super().__init__()
        self.running = True
        self.local_port = local_port
        self.known_servers = {}
        self.zeroconf = None
        self.browser = None
        self.listener = None
        self.broadcast_socket = None
        self.local_ip = self._get_local_ip()
        
    def _get_local_ip(self):
        """Получение локального IP"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    def run(self):
        """Запуск обнаружения"""
        self.status_signal.emit("Запуск обнаружения серверов...")
        
        # Запускаем оба метода обнаружения
        if ZEROCONF_AVAILABLE:
            self._start_zeroconf_discovery()
        
        self._start_broadcast_listener()
        
        # Держим поток активным
        while self.running:
            time.sleep(1)
    
    def _start_zeroconf_discovery(self):
        """Обнаружение через Zeroconf"""
        try:
            self.zeroconf = Zeroconf()
            self.listener = ZeroconfListener(self)
            self.browser = ServiceBrowser(self.zeroconf, "_http._tcp.local.", self.listener)
            self.status_signal.emit("Zeroconf обнаружение активно")
        except Exception as e:
            self.status_signal.emit(f"Zeroconf ошибка: {e}")
    
    def _start_broadcast_listener(self):
        """Запуск UDP слушателя для широковещательных сообщений"""
        try:
            self.broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.broadcast_socket.bind(('', BROADCAST_PORT))
            self.broadcast_socket.settimeout(1)
            
            def listener():
                while self.running:
                    try:
                        data, addr = self.broadcast_socket.recvfrom(1024)
                        msg = data.decode('utf-8', errors='ignore')
                        
                        if msg == DISCOVERY_MSG:
                            # Нас обнаружили, отвечаем
                            self._send_broadcast_response(addr[0])
                        elif msg == RESPONSE_MSG:
                            # Нашли другой сервер
                            server_id = f"{addr[0]}:{BROADCAST_PORT}"
                            if server_id != f"{self.local_ip}:{BROADCAST_PORT}":
                                server_data = {
                                    'id': server_id,
                                    'name': f"Server at {addr[0]}",
                                    'ip': addr[0],
                                    'port': DEFAULT_PORT,  # Предполагаем стандартный порт
                                    'address': f"http://{addr[0]}:{DEFAULT_PORT}",
                                    'type': 'broadcast'
                                }
                                self.server_found.emit(server_data)
                    except socket.timeout:
                        continue
                    except Exception as e:
                        break
            
            listener_thread = threading.Thread(target=listener, daemon=True)
            listener_thread.start()
            self.status_signal.emit("Broadcast слушатель запущен")
            
            # Отправляем широковещательный запрос для активного поиска
            self._send_broadcast_discovery()
            
        except Exception as e:
            self.status_signal.emit(f"Broadcast ошибка: {e}")
    
    def _send_broadcast_discovery(self):
        """Отправка широковещательного запроса"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(1)
            sock.sendto(DISCOVERY_MSG.encode(), ('255.255.255.255', BROADCAST_PORT))
            sock.close()
        except Exception as e:
            pass
    
    def _send_broadcast_response(self, target_ip):
        """Отправка ответа на запрос обнаружения"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(RESPONSE_MSG.encode(), (target_ip, BROADCAST_PORT))
            sock.close()
        except Exception as e:
            pass
    
    def stop(self):
        """Остановка обнаружения"""
        self.running = False
        
        if self.browser:
            self.browser.cancel()
        
        if self.zeroconf:
            self.zeroconf.close()
        
        if self.broadcast_socket:
            try:
                self.broadcast_socket.close()
            except:
                pass


# ============= УПРАВЛЕНИЕ ФАЙЛАМИ =============
class FileManager:
    """Управление файловой системой"""
    
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
    
    @safe_execution
    def create_sample_files(self):
        """Создание примеров файлов с проверкой"""
        templates = {
            'base.html': self._get_base_template(),
            'index.html': self._get_index_template(),
            'login.html': self._get_login_template(),
            'view_file.html': self._get_view_template(),
            'upload.html': self._get_upload_template(),
            'profile.html': self._get_profile_template()
        }
        
        created = []
        for filename, content in templates.items():
            filepath = os.path.join(self.config.templates_dir, filename)
            if not os.path.exists(filepath):
                self._safe_write(filepath, content)
                created.append(filename)
        
        css_dir = os.path.join(self.config.static_dir, 'css')
        os.makedirs(css_dir, exist_ok=True)
        
        css_file = os.path.join(css_dir, 'styles.css')
        if not os.path.exists(css_file):
            self._safe_write(css_file, self._get_css_content())
            created.append('styles.css')
        
        js_dir = os.path.join(self.config.static_dir, 'js')
        os.makedirs(js_dir, exist_ok=True)
        
        return created
    
    def _safe_write(self, filepath, content):
        """Безопасная запись файла"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            self.logger.info(f"Создан: {os.path.basename(filepath)}")
        except Exception as e:
            self.logger.error(f"Не удалось создать {filepath}: {e}")
    
    def check_required_files(self):
        """Проверка наличия необходимых файлов"""
        missing = []
        
        required_templates = ['base.html', 'index.html', 'login.html', 
                             'view_file.html', 'upload.html', 'profile.html']
        for template in required_templates:
            if not os.path.exists(os.path.join(self.config.templates_dir, template)):
                missing.append(f"templates/{template}")
        
        if not os.path.exists(os.path.join(self.config.static_dir, 'css')):
            missing.append("static/css/")
        elif not os.path.exists(os.path.join(self.config.static_dir, 'css', 'styles.css')):
            missing.append("static/css/styles.css")
        
        return missing
    
    def cleanup_old_logs(self, days=7):
        """Очистка логов старше указанного количества дней"""
        removed = 0
        now = datetime.datetime.now()
        
        for filename in os.listdir(self.config.logs_dir):
            if filename.endswith('.log'):
                filepath = os.path.join(self.config.logs_dir, filename)
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(filepath))
                
                if (now - mtime).days > days:
                    os.remove(filepath)
                    removed += 1
        
        return removed
    
    def _get_base_template(self):
        return """<!DOCTYPE html>
<html>
<head>
    <title>{% block title %}Space Share{% endblock %}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/styles.css') }}">
    <meta charset="UTF-8">
</head>
<body>
    <nav>
        <a href="/">Главная</a>
        <a href="/upload">Загрузить</a>
        <a href="/search">Поиск</a>
        <a href="/chat">Чат</a>
        {% if current_user.is_authenticated %}
            <a href="{{ url_for('profile', user_id=current_user.id) }}">Профиль</a>
            <a href="/logout">Выход</a>
        {% else %}
            <a href="/login">Вход</a>
            <a href="/register">Регистрация</a>
        {% endif %}
    </nav>
    
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        {% block content %}{% endblock %}
    </div>
</body>
</html>"""
    
    def _get_index_template(self):
        return """{% extends "base.html" %}
{% block title %}Главная{% endblock %}
{% block content %}
<h1>Добро пожаловать в Space Share!</h1>
<p>Система обмена файлами в локальной сети</p>
{% endblock %}"""
    
    def _get_login_template(self):
        return """{% extends "base.html" %}
{% block title %}Вход{% endblock %}
{% block content %}
<h1>Вход в систему</h1>
<form method="POST">
    <input type="email" name="email" placeholder="Email" required>
    <input type="password" name="password" placeholder="Пароль" required>
    <button type="submit">Войти</button>
</form>
<p>Нет аккаунта? <a href="/register">Зарегистрироваться</a></p>
{% endblock %}"""
    
    def _get_view_template(self):
        return """{% extends "base.html" %}
{% block title %}Просмотр файла{% endblock %}
{% block content %}
<h1>{{ file.filename }}</h1>
<p>Размер: {{ (file.file_size / 1024 / 1024) | round(2) }} MB</p>
<p>Загружен: {{ file.upload_time }}</p>
{% if content %}
<pre>{{ content }}</pre>
{% endif %}
<a href="{{ url_for('download_file', file_id=file.id) }}">Скачать</a>
{% endblock %}"""
    
    def _get_upload_template(self):
        return """{% extends "base.html" %}
{% block title %}Загрузка{% endblock %}
{% block content %}
<h1>Загрузить файлы</h1>
<form method="POST" enctype="multipart/form-data">
    <input type="file" name="files" multiple required>
    <textarea name="description" placeholder="Описание"></textarea>
    <button type="submit">Загрузить</button>
</form>
{% endblock %}"""
    
    def _get_profile_template(self):
        return """{% extends "base.html" %}
{% block title %}Профиль{% endblock %}
{% block content %}
<h1>{{ user.username }}</h1>
<p>Email: {{ user.email }}</p>
<p>Дата регистрации: {{ user.created_at }}</p>
<a href="/profile/edit">Редактировать профиль</a>
{% endblock %}"""
    
    def _get_css_content(self):
        return """/* Основные стили */
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    background: #0a0a0a;
    color: #e0e0e0;
}

nav {
    background: #1a1a1a;
    padding: 1rem 2rem;
    border-bottom: 1px solid #333;
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
}

nav a {
    color: #e0e0e0;
    text-decoration: none;
    padding: 0.5rem 1rem;
    border-radius: 8px;
    transition: all 0.3s;
}

nav a:hover {
    background: #2563eb;
    color: white;
}

.container {
    max-width: 1200px;
    margin: 2rem auto;
    padding: 0 2rem;
}

h1 {
    color: #2563eb;
    margin-bottom: 1rem;
}

.alert {
    padding: 1rem;
    margin: 1rem 0;
    border-radius: 8px;
}

.alert-success {
    background: #1e4620;
    color: #8bc34a;
    border-left: 4px solid #8bc34a;
}

.alert-danger {
    background: #4a1e1e;
    color: #ff6b6b;
    border-left: 4px solid #ff6b6b;
}

form {
    background: #1a1a1a;
    padding: 2rem;
    border-radius: 12px;
    border: 1px solid #333;
}

input, textarea, button {
    display: block;
    width: 100%;
    margin: 1rem 0;
    padding: 0.75rem;
    background: #252525;
    border: 1px solid #333;
    border-radius: 8px;
    color: #e0e0e0;
    font-size: 1rem;
}

button {
    background: #2563eb;
    color: white;
    cursor: pointer;
    font-weight: bold;
    transition: all 0.3s;
}

button:hover {
    background: #3b82f6;
    transform: translateY(-2px);
}

button:disabled {
    background: #1e293b;
    cursor: not-allowed;
}

pre {
    background: #1a1a1a;
    padding: 1rem;
    border-radius: 8px;
    overflow-x: auto;
    border: 1px solid #333;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.9rem;
}"""


# ============= ПОТОК СЕРВЕРА =============
class ServerThread(QThread):
    """Поток сервера с поддержкой нескольких экземпляров"""
    
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(bool)
    error_signal = pyqtSignal(str)
    stats_signal = pyqtSignal(dict)
    port_changed = pyqtSignal(int)
    
    def __init__(self, config, logger):
        super().__init__()
        self.config = config
        self.logger = logger
        self.zeroconf = None
        self.zeroconf_available = ZEROCONF_AVAILABLE
        self.hostname = socket.gethostname()
        self.service_name = None
        self.info = None
        self.flask_app = None
        self.start_time = None
        self.broadcast_socket = None
        self._stats = {'requests': 0, 'connections': 0, 'errors': 0}
        self._lock = threading.Lock()
        self._actual_port = config.port
        
        if self.zeroconf_available:
            try:
                self.zeroconf = Zeroconf()
                self.logger.info("Zeroconf инициализирован")
            except Exception as e:
                self.zeroconf_available = False
                self.logger.warning(f"Zeroconf не доступен: {e}")
    
    def find_free_port(self):
        """Поиск свободного порта"""
        for port in range(PORT_RANGE_START, PORT_RANGE_END):
            if self.is_port_available(port):
                return port
        return None
    
    def is_port_available(self, port):
        """Проверка доступности порта"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return True
            except socket.error:
                return False
    
    def _start_broadcast_responder(self):
        """Запуск ответчика на широковещательные запросы"""
        try:
            self.broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.broadcast_socket.bind(('', BROADCAST_PORT))
            self.broadcast_socket.settimeout(1)
            
            def responder():
                local_ip = self.get_local_ip()
                while self.isRunning():
                    try:
                        data, addr = self.broadcast_socket.recvfrom(1024)
                        msg = data.decode('utf-8', errors='ignore')
                        
                        if msg == DISCOVERY_MSG:
                            # Отвечаем на запрос
                            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            sock.sendto(RESPONSE_MSG.encode(), addr)
                            sock.close()
                    except socket.timeout:
                        continue
                    except Exception:
                        break
            
            responder_thread = threading.Thread(target=responder, daemon=True)
            responder_thread.start()
            self.logger.info("Broadcast responder запущен")
        except Exception as e:
            self.logger.warning(f"Broadcast responder не запущен: {e}")
    
    def get_local_ip(self):
        """Получение локального IP"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return self.get_local_ip_fallback()
    
    def get_local_ip_fallback(self):
        """Получение локального IP без интернета"""
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if ip and not ip.startswith('127.'):
                return ip
        except:
            pass
        
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('192.168.1.1', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            pass
        
        return "127.0.0.1"
    
    def _start_zeroconf(self):
        """Запуск Zeroconf с уникальным именем"""
        if not self.zeroconf_available or not self.zeroconf:
            return
        
        try:
            local_ip = self.get_local_ip()
            self.service_name = f"Space Share - {self.hostname} ({self._actual_port})._http._tcp.local."
            
            self.info = ServiceInfo(
                "_http._tcp.local.",
                self.service_name,
                addresses=[socket.inet_aton(local_ip)],
                port=self._actual_port,
                properties={
                    'version': APP_VERSION,
                    'hostname': self.hostname,
                    'port': str(self._actual_port)
                },
                server=f"{self.hostname}.local",
            )
            self.zeroconf.register_service(self.info)
            self.logger.info(f"Zeroconf зарегистрирован: {self.service_name}")
        except Exception as e:
            self.logger.warning(f"Zeroconf ошибка: {e}")
    
    def _check_prerequisites(self):
        """Проверка условий запуска"""
        if not self.is_port_available(self._actual_port):
            raise RuntimeError(f"Порт {self._actual_port} уже используется")
        
        if not os.path.exists(self.config.templates_dir):
            raise RuntimeError(f"Директория не найдена: {self.config.templates_dir}")
        if not os.path.exists(self.config.static_dir):
            raise RuntimeError(f"Директория не найдена: {self.config.static_dir}")
    
    def run(self):
        """Запуск сервера"""
        try:
            if self.isInterruptionRequested():
                return
            
            # Автоматический выбор порта
            original_port = self.config.port
            if not self.is_port_available(self.config.port):
                new_port = self.find_free_port()
                if new_port:
                    self._actual_port = new_port
                    self.config.port = new_port
                    self.port_changed.emit(new_port)
                    self.logger.info(f"Порт {original_port} занят, использую {new_port}")
                    self.log_signal.emit(f"[СЕРВЕР] Порт {original_port} занят, использую порт {new_port}")
                else:
                    raise RuntimeError(f"Нет свободных портов в диапазоне {PORT_RANGE_START}-{PORT_RANGE_END}")
            else:
                self._actual_port = self.config.port
            
            self.start_time = datetime.datetime.now()
            
            self._check_prerequisites()
            local_ip = self.get_local_ip()
            
            # Запуск сервисов обнаружения
            self._start_broadcast_responder()
            
            if self.zeroconf_available:
                try:
                    self._start_zeroconf()
                except Exception as e:
                    self.logger.warning(f"Zeroconf не запущен: {e}")
            
            # Логирование
            self.logger.info(f"Сервер запущен на порту {self._actual_port}")
            self.logger.info(f"IP адрес: {local_ip}")
            self.logger.info(f"Имя хоста: {self.hostname}")
            
            self.log_signal.emit(f"[СЕРВЕР] Сервер запущен на порту {self._actual_port}")
            self.log_signal.emit(f"[СЕРВЕР] Локальный доступ: http://127.0.0.1:{self._actual_port}")
            self.log_signal.emit(f"[СЕРВЕР] Сетевой доступ: http://{local_ip}:{self._actual_port}")
            
            if self.zeroconf_available:
                self.log_signal.emit(f"[СЕРВЕР] Автообнаружение: {self.service_name}")
            
            self.status_signal.emit(True)
            
            # Запуск Flask
            self._start_flask()
            
        except Exception as e:
            error_msg = f"Ошибка сервера: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.log_signal.emit(f"[ОШИБКА] {error_msg}")
            self.error_signal.emit(str(e))
            self.status_signal.emit(False)
        finally:
            self.cleanup()
    
    def _start_flask(self):
        """Запуск Flask сервера"""
        self.flask_app = create_app(gui_signal=self.log_signal)
        self.flask_app.template_folder = self.config.templates_dir
        self.flask_app.static_folder = self.config.static_dir
        
        @self.flask_app.before_request
        def count_request():
            with self._lock:
                self._stats['requests'] += 1
        
        class QtLogHandler(logging.Handler):
            def __init__(self, signal):
                super().__init__()
                self.signal = signal
                self.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S'))
            
            def emit(self, record):
                msg = self.format(record)
                self.signal.emit(msg)
        
        qt_handler = QtLogHandler(self.log_signal)
        qt_handler.setLevel(logging.INFO)
        
        logging.getLogger('werkzeug').addHandler(qt_handler)
        logging.getLogger('SpaceShare').addHandler(qt_handler)
        
        socketio.run(
            self.flask_app, 
            host=self.config.host, 
            port=self._actual_port, 
            debug=False, 
            use_reloader=False, 
            allow_unsafe_werkzeug=True
        )
    
    def cleanup(self):
        """Очистка ресурсов"""
        if self.zeroconf and self.info:
            try:
                self.zeroconf.unregister_service(self.info)
                self.logger.info("Zeroconf сервис отключен")
            except Exception as e:
                pass
        
        if self.zeroconf:
            try:
                self.zeroconf.close()
            except:
                pass
        
        if self.broadcast_socket:
            try:
                self.broadcast_socket.close()
            except:
                pass
    
    def stop(self):
        """Остановка сервера"""
        self.logger.info("Остановка сервера...")
        
        if hasattr(self, 'flask_app') and self.flask_app:
            try:
                socketio.stop()
            except:
                pass
        
        self.cleanup()
        self.requestInterruption()
        self.wait(3000)
        
        if self.isRunning():
            self.logger.warning("Принудительное завершение")
            self.terminate()
            self.wait()
    
    def get_stats(self):
        """Получение статистики"""
        with self._lock:
            uptime = datetime.datetime.now() - self.start_time if self.start_time else datetime.timedelta(0)
            return {
                **self._stats,
                'uptime': str(uptime).split('.')[0],
                'port': self._actual_port,
                'host': self.hostname
            }


# ============= СОВРЕМЕННАЯ КНОПКА =============
class ModernButton(QPushButton):
    """Стилизованная кнопка"""
    
    def __init__(self, text, variant='default', icon=None, tooltip=None):
        super().__init__(text)
        self.variant = variant
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        
        if icon:
            self.setIcon(QIcon(icon))
        
        if tooltip:
            self.setToolTip(tooltip)
        
        self._setup_style()
    
    def _setup_style(self):
        styles = {
            'primary': """
                QPushButton {
                    background-color: #2563eb;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                    padding: 8px 20px;
                }
                QPushButton:hover { background-color: #3b82f6; }
                QPushButton:pressed { background-color: #1d4ed8; }
                QPushButton:disabled { 
                    background-color: #1e293b;
                    color: #64748b;
                }
            """,
            'danger': """
                QPushButton {
                    background-color: #dc2626;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                    padding: 8px 20px;
                }
                QPushButton:hover { background-color: #ef4444; }
                QPushButton:pressed { background-color: #b91c1c; }
            """,
            'success': """
                QPushButton {
                    background-color: #10b981;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                    padding: 8px 20px;
                }
                QPushButton:hover { background-color: #34d399; }
                QPushButton:pressed { background-color: #059669; }
            """,
            'default': """
                QPushButton {
                    background-color: #2d2d2d;
                    color: #e0e0e0;
                    border: 1px solid #404040;
                    border-radius: 8px;
                    padding: 8px 20px;
                }
                QPushButton:hover { background-color: #3d3d3d; }
                QPushButton:pressed { background-color: #252525; }
                QPushButton:disabled {
                    background-color: #1a1a1a;
                    color: #666666;
                    border-color: #333333;
                }
            """
        }
        self.setStyleSheet(styles.get(self.variant, styles['default']))


# ============= ГЛАВНОЕ ОКНО =============
class AdminWindow(QMainWindow):
    """Главное окно с поддержкой нескольких серверов"""
    
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.folders_created = self.config.ensure_dirs()
        self.logger = ServerLogger(self.config)
        self.file_manager = FileManager(self.config, self.logger)
        self.server_thread = None
        self.discovery_thread = None
        self.stats_timer = None
        self.discovered_servers = {}
        
        self.init_ui()
        self.apply_theme(self.config.theme)
        self.check_initial_setup()
        self.setup_connections()
        self.start_discovery()
        
        self.logger.info("Панель управления запущена")
        self.logger.info(f"Базовая директория: {BASE_DIR}")
        self.logger.info(f"Zeroconf доступен: {ZEROCONF_AVAILABLE}")
    
    def init_ui(self):
        """Инициализация интерфейса"""
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} - Панель управления")
        self.setMinimumSize(1200, 800)
        
        central = QWidget()
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setSpacing(15)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Создаем вкладки
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #333333;
                border-radius: 12px;
                background-color: #1a1a1a;
            }
            QTabBar::tab {
                background-color: #252525;
                color: #e0e0e0;
                padding: 10px 24px;
                margin-right: 4px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background-color: #2563eb;
                color: white;
            }
            QTabBar::tab:hover:!selected {
                background-color: #3d3d3d;
            }
        """)
        
        # Вкладка сервера
        self.server_tab = QWidget()
        self._setup_server_tab()
        self.tabs.addTab(self.server_tab, "🚀 Мой сервер")
        
        # Вкладка обнаружения
        self.discovery_tab = QWidget()
        self._setup_discovery_tab()
        self.tabs.addTab(self.discovery_tab, "🌐 Серверы в сети")
        
        self.main_layout.addWidget(self.tabs)
        self._create_status_bar()
    
    def _setup_server_tab(self):
        """Настройка вкладки сервера"""
        layout = QVBoxLayout(self.server_tab)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Заголовок
        header = QHBoxLayout()
        title = QLabel(f"{APP_NAME} Server")
        title.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff;")
        header.addWidget(title)
        
        self.status_container = QFrame()
        self.status_container.setStyleSheet("""
            QFrame {
                background-color: #252525;
                border-radius: 20px;
                padding: 5px 15px;
            }
        """)
        status_layout = QHBoxLayout(self.status_container)
        status_layout.setContentsMargins(10, 5, 15, 5)
        
        self.status_light = QLabel("●")
        self.status_light.setFont(QFont("Segoe UI", 14))
        self.status_light.setStyleSheet("color: #ef4444;")
        
        self.status_text = QLabel("Сервер остановлен")
        self.status_text.setFont(QFont("Segoe UI", 11))
        self.status_text.setStyleSheet("color: #a0a0a0;")
        
        status_layout.addWidget(self.status_light)
        status_layout.addWidget(self.status_text)
        
        header.addStretch()
        header.addWidget(self.status_container)
        layout.addLayout(header)
        
        # Информационная панель
        info_frame = QFrame()
        info_frame.setStyleSheet("""
            QFrame {
                background-color: #1a1a1a;
                border: 1px solid #333;
                border-radius: 12px;
                padding: 15px;
            }
        """)
        info_layout = QHBoxLayout(info_frame)
        
        location_icon = QLabel("📍")
        location_icon.setFont(QFont("Segoe UI", 12))
        info_layout.addWidget(location_icon)
        
        location_text = QLabel(f"Расположение: {BASE_DIR}")
        location_text.setFont(QFont("Segoe UI", 10))
        location_text.setStyleSheet("color: #90caf9; font-family: monospace;")
        info_layout.addWidget(location_text)
        
        info_layout.addStretch()
        
        self.stats_label = QLabel("Статистика: Запросов: 0 | Подключений: 0")
        self.stats_label.setStyleSheet("color: #888888;")
        info_layout.addWidget(self.stats_label)
        
        layout.addWidget(info_frame)
        
        # Логи
        log_header = QHBoxLayout()
        log_title = QLabel("Консоль сервера")
        log_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        log_title.setStyleSheet("color: #ffffff;")
        log_header.addWidget(log_title)
        log_header.addStretch()
        
        self.btn_clear_logs = ModernButton("Очистить", 'default')
        self.btn_clear_logs.clicked.connect(self.clear_logs)
        log_header.addWidget(self.btn_clear_logs)
        
        self.btn_copy_logs = ModernButton("Копировать", 'default')
        self.btn_copy_logs.clicked.connect(self.copy_logs)
        log_header.addWidget(self.btn_copy_logs)
        
        layout.addLayout(log_header)
        
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("JetBrains Mono", 10))
        self.log_view.setStyleSheet("""
            QTextEdit {
                background-color: #0a0a0a;
                color: #00ff00;
                border: 1px solid #333333;
                border-radius: 12px;
                padding: 16px;
                font-family: 'JetBrains Mono', monospace;
            }
        """)
        layout.addWidget(self.log_view)
        
        # Кнопки
        buttons_frame = QFrame()
        buttons_frame.setStyleSheet("""
            QFrame {
                background-color: #1e1e1e;
                border: 1px solid #333333;
                border-radius: 16px;
                padding: 20px;
            }
        """)
        buttons_layout = QVBoxLayout(buttons_frame)
        buttons_layout.setSpacing(12)
        
        main_buttons = QHBoxLayout()
        main_buttons.setSpacing(12)
        
        self.btn_start = ModernButton("Запустить сервер", 'primary')
        self.btn_start.clicked.connect(self.start_server)
        main_buttons.addWidget(self.btn_start)
        
        self.btn_stop = ModernButton("Остановить", 'danger')
        self.btn_stop.clicked.connect(self.stop_server)
        self.btn_stop.setEnabled(False)
        main_buttons.addWidget(self.btn_stop)
        
        self.btn_restart = ModernButton("Перезапустить", 'default')
        self.btn_restart.clicked.connect(self.restart_server)
        self.btn_restart.setEnabled(False)
        main_buttons.addWidget(self.btn_restart)
        
        self.btn_open = ModernButton("Открыть в браузере", 'default')
        self.btn_open.clicked.connect(self.open_browser)
        self.btn_open.setEnabled(False)
        main_buttons.addWidget(self.btn_open)
        
        buttons_layout.addLayout(main_buttons)
        
        extra_buttons = QHBoxLayout()
        extra_buttons.setSpacing(12)
        
        self.btn_open_folder = ModernButton("Открыть папку", 'default')
        self.btn_open_folder.clicked.connect(self.open_base_folder)
        extra_buttons.addWidget(self.btn_open_folder)
        
        self.btn_check_files = ModernButton("Проверить файлы", 'default')
        self.btn_check_files.clicked.connect(self.check_required_files)
        extra_buttons.addWidget(self.btn_check_files)
        
        self.btn_create_sample = ModernButton("Создать примеры", 'default')
        self.btn_create_sample.clicked.connect(self.create_sample_files)
        extra_buttons.addWidget(self.btn_create_sample)
        
        self.btn_view_logs = ModernButton("Просмотр логов", 'default')
        self.btn_view_logs.clicked.connect(self.view_logs)
        extra_buttons.addWidget(self.btn_view_logs)
        
        self.btn_cleanup_logs = ModernButton("Очистить логи", 'default')
        self.btn_cleanup_logs.clicked.connect(lambda: self.cleanup_old_logs(7))
        extra_buttons.addWidget(self.btn_cleanup_logs)
        
        extra_buttons.addStretch()
        
        self.btn_exit = ModernButton("Выход", 'default')
        self.btn_exit.clicked.connect(self.close)
        extra_buttons.addWidget(self.btn_exit)
        
        buttons_layout.addLayout(extra_buttons)
        layout.addWidget(buttons_frame)
    
    def _setup_discovery_tab(self):
        """Настройка вкладки обнаружения"""
        layout = QVBoxLayout(self.discovery_tab)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        title = QLabel("Обнаруженные серверы в локальной сети")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff;")
        layout.addWidget(title)
        
        info = QLabel(
            "Автоматически обнаруженные серверы Space Share в вашей сети.\n"
            "Двойной клик или нажмите 'Подключиться' для открытия сервера в браузере."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #888888; margin-bottom: 15px;")
        layout.addWidget(info)
        
        self.servers_list = QListWidget()
        self.servers_list.setStyleSheet("""
            QListWidget {
                background-color: #0a0a0a;
                border: 1px solid #333333;
                border-radius: 12px;
                padding: 10px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 12px;
                border-bottom: 1px solid #252525;
            }
            QListWidget::item:hover {
                background-color: #1a1a1a;
            }
            QListWidget::item:selected {
                background-color: #2563eb;
            }
        """)
        self.servers_list.itemDoubleClicked.connect(self.on_server_double_clicked)
        layout.addWidget(self.servers_list)
        
        btn_layout = QHBoxLayout()
        
        self.btn_refresh = ModernButton("Обновить список", 'primary')
        self.btn_refresh.clicked.connect(self.refresh_servers)
        btn_layout.addWidget(self.btn_refresh)
        
        self.btn_connect = ModernButton("Подключиться", 'default')
        self.btn_connect.clicked.connect(self.connect_to_selected)
        btn_layout.addWidget(self.btn_connect)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.discovery_status = QLabel("🔍 Поиск серверов...")
        self.discovery_status.setStyleSheet("color: #888888; margin-top: 10px;")
        layout.addWidget(self.discovery_status)
    
    def _create_status_bar(self):
        """Создание строки состояния"""
        self.statusBar().showMessage("Готов к работе")
        self.statusBar().setStyleSheet("""
            QStatusBar {
                background-color: #1a1a1a;
                color: #888888;
                border-top: 1px solid #333333;
                padding: 4px;
            }
        """)
    
    def setup_connections(self):
        """Настройка соединений"""
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.update_stats)
        self.stats_timer.start(2000)
    
    def start_discovery(self):
        """Запуск обнаружения серверов"""
        self.discovery_thread = ServerDiscovery(local_port=self.config.port)
        self.discovery_thread.server_found.connect(self.on_server_found)
        self.discovery_thread.server_lost.connect(self.on_server_lost)
        self.discovery_thread.status_signal.connect(self.on_discovery_status)
        self.discovery_thread.start()
        self.logger.discovery("Запущено обнаружение серверов")
    
    def on_server_found(self, server_data):
        """Найден сервер"""
        server_id = server_data['id']
        
        # Не добавляем себя
        if server_data['port'] == self.config.port:
            local_ip = self.get_local_ip()
            if server_data['ip'] == local_ip:
                return
        
        if server_id not in self.discovered_servers:
            self.discovered_servers[server_id] = server_data
            self.update_servers_list()
            self.logger.discovery(f"Найден сервер: {server_data['address']}")
            self.append_log(f"[ОБНАРУЖЕНИЕ] Найден сервер: {server_data['address']}")
    
    def on_server_lost(self, server_id):
        """Сервер пропал"""
        if server_id in self.discovered_servers:
            del self.discovered_servers[server_id]
            self.update_servers_list()
            self.logger.discovery(f"Сервер пропал: {server_id}")
    
    def on_discovery_status(self, status):
        """Обновление статуса обнаружения"""
        self.discovery_status.setText(f"🔍 {status}")
    
    def update_servers_list(self):
        """Обновление списка серверов"""
        self.servers_list.clear()
        
        if not self.discovered_servers:
            item = QListWidgetItem("❌ Серверы не найдены")
            item.setForeground(QColor("#888888"))
            self.servers_list.addItem(item)
            self.discovery_status.setText("🔍 Серверы не найдены")
            return
        
        count = len(self.discovered_servers)
        self.discovery_status.setText(f"✅ Найдено серверов: {count}")
        
        for server_id, data in sorted(self.discovered_servers.items()):
            text = f"🌐 {data['name']}\n   📍 Адрес: {data['address']}\n   🖥️ Тип: {data['type']}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, data)
            self.servers_list.addItem(item)
    
    def refresh_servers(self):
        """Обновление списка"""
        self.discovered_servers.clear()
        self.update_servers_list()
        self.logger.discovery("Обновление списка серверов")
    
    def on_server_double_clicked(self, item):
        """Двойной клик по серверу"""
        server_data = item.data(Qt.ItemDataRole.UserRole)
        if server_data:
            self.connect_to_server(server_data)
    
    def connect_to_selected(self):
        """Подключение к выбранному серверу"""
        current = self.servers_list.currentItem()
        if current:
            server_data = current.data(Qt.ItemDataRole.UserRole)
            if server_data:
                self.connect_to_server(server_data)
    
    def connect_to_server(self, server_data):
        """Подключение к серверу"""
        url = server_data['address']
        webbrowser.open(url)
        self.logger.info(f"Подключение к {url}")
        self.statusBar().showMessage(f"Подключение к {url}", 3000)
    
    def get_local_ip(self):
        """Получение локального IP"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    def update_stats(self):
        """Обновление статистики"""
        if self.server_thread and self.server_thread.isRunning():
            stats = self.server_thread.get_stats()
            self.stats_label.setText(
                f"Статистика: Запросов: {stats['requests']} | "
                f"Подключений: {stats['connections']} | "
                f"Время работы: {stats['uptime']} | "
                f"Порт: {stats['port']}"
            )
    
    def apply_theme(self, theme_name):
        """Применение темы"""
        colors = COLORS.get(theme_name, COLORS['dark'])
        
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors['bg']))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(colors['fg']))
        palette.setColor(QPalette.ColorRole.Base, QColor(24, 24, 24))
        palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(240, 240, 240))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(37, 99, 235))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        
        self.setPalette(palette)
    
    def check_initial_setup(self):
        """Проверка начальной настройки"""
        if self.folders_created:
            self.append_log(f"Созданы папки: {', '.join(self.folders_created)}")
        
        missing = self.file_manager.check_required_files()
        if missing:
            self.append_log("Отсутствуют некоторые файлы:")
            for file in missing:
                self.append_log(f"  - {file}")
            self.append_log("Нажмите 'Создать примеры' для создания базовых файлов")
        else:
            self.append_log("Все необходимые файлы найдены")
    
    def append_log(self, text):
        """Добавление в лог"""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted = f"<span style='color: #666666;'>[{timestamp}]</span> {text}"
        self.log_view.append(formatted)
        
        cursor = self.log_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.log_view.setTextCursor(cursor)
    
    def clear_logs(self):
        """Очистка логов"""
        self.log_view.clear()
        self.append_log("Логи очищены")
    
    def copy_logs(self):
        """Копирование логов"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.log_view.toPlainText())
        self.statusBar().showMessage("Логи скопированы", 2000)
    
    def open_base_folder(self):
        """Открытие папки"""
        os.startfile(BASE_DIR)
        self.logger.info(f"Открыта папка: {BASE_DIR}")
    
    def check_required_files(self):
        """Проверка файлов"""
        missing = self.file_manager.check_required_files()
        if missing:
            msg = "Отсутствуют файлы:\n\n" + "\n".join(missing)
            QMessageBox.warning(self, "Проверка файлов", msg)
        else:
            QMessageBox.information(self, "Проверка файлов", "Все файлы найдены!")
    
    def create_sample_files(self):
        """Создание примеров"""
        created = self.file_manager.create_sample_files()
        if created:
            self.append_log(f"Созданы: {', '.join(created)}")
            QMessageBox.information(self, "Успех", f"Созданы файлы: {', '.join(created)}")
        else:
            QMessageBox.information(self, "Информация", "Файлы уже существуют")
    
    def start_server(self):
        """Запуск сервера"""
        if not self.server_thread or not self.server_thread.isRunning():
            if not os.path.exists(TEMPLATES_DIR):
                QMessageBox.warning(self, "Ошибка", "Папка шаблонов не найдена!\nНажмите 'Создать примеры'")
                return
            
            self.server_thread = ServerThread(self.config, self.logger)
            self.server_thread.log_signal.connect(self.append_log)
            self.server_thread.status_signal.connect(self.update_status)
            self.server_thread.error_signal.connect(self.handle_server_error)
            self.server_thread.stats_signal.connect(self.update_stats)
            self.server_thread.port_changed.connect(self.on_port_changed)
            self.server_thread.start()
            
            self.append_log("Инициализация сервера...")
            self.logger.info("Запуск сервера...")
    
    def on_port_changed(self, new_port):
        """Обработка смены порта"""
        self.config.port = new_port
        self.append_log(f"[СЕРВЕР] Используется порт: {new_port}")
    
    def update_status(self, is_running):
        """Обновление статуса"""
        if is_running:
            self.status_light.setStyleSheet("color: #4caf50;")
            self.status_text.setText(f"Сервер запущен (порт {self.config.port})")
            self.status_text.setStyleSheet("color: #4caf50; font-weight: 500;")
            self.statusBar().showMessage(f"Сервер активен на порту {self.config.port}", 3000)
            self.btn_stop.setEnabled(True)
            self.btn_restart.setEnabled(True)
            self.btn_open.setEnabled(True)
            self.btn_start.setEnabled(False)
        else:
            self.status_light.setStyleSheet("color: #f44336;")
            self.status_text.setText("Сервер остановлен")
            self.status_text.setStyleSheet("color: #888888;")
            self.statusBar().showMessage("Сервер остановлен", 3000)
            self.btn_stop.setEnabled(False)
            self.btn_restart.setEnabled(False)
            self.btn_open.setEnabled(False)
            self.btn_start.setEnabled(True)
    
    def handle_server_error(self, error_msg):
        """Обработка ошибки"""
        self.logger.error(f"Ошибка: {error_msg}")
        QMessageBox.critical(self, "Ошибка сервера", f"Произошла ошибка:\n{error_msg}")
    
    def stop_server(self):
        """Остановка сервера"""
        if self.server_thread and self.server_thread.isRunning():
            reply = QMessageBox.question(self, 'Подтверждение', 
                                        'Остановить сервер?',
                                        QMessageBox.StandardButton.Yes | 
                                        QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                self.append_log("Остановка сервера...")
                self.logger.info("Остановка сервера...")
                self.server_thread.stop()
                self.server_thread.wait()
                self.append_log("Сервер остановлен")
    
    def restart_server(self):
        """Перезапуск сервера"""
        self.append_log("Перезапуск сервера...")
        
        if self.server_thread and self.server_thread.isRunning():
            self.server_thread.stop()
            if not self.server_thread.wait(5000):
                self.append_log("Сервер не остановился вовремя")
        
        old_thread = self.server_thread
        self.server_thread = None
        
        self.append_log("Очистка ресурсов...")
        QThread.msleep(1500)
        
        self.server_thread = ServerThread(self.config, self.logger)
        self.server_thread.log_signal.connect(self.append_log)
        self.server_thread.status_signal.connect(self.update_status)
        self.server_thread.error_signal.connect(self.handle_server_error)
        self.server_thread.stats_signal.connect(self.update_stats)
        self.server_thread.port_changed.connect(self.on_port_changed)
        
        self.append_log("Запуск сервера...")
        self.server_thread.start()
        QThread.msleep(500)
        
        if old_thread:
            old_thread.deleteLater()
    
    def open_browser(self):
        """Открытие браузера"""
        if self.server_thread:
            ip = self.server_thread.get_local_ip()
            webbrowser.open(f"http://{ip}:{self.config.port}")
            self.logger.info(f"Открыт браузер: http://{ip}:{self.config.port}")
    
    def view_logs(self):
        """Просмотр логов"""
        log_file = os.path.join(LOGS_DIR, f'app_{datetime.datetime.now().strftime("%Y%m%d")}.log')
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()[-50:]
                    log_text = ''.join(lines)
                
                dialog = QDialog(self)
                dialog.setWindowTitle("Просмотр логов")
                dialog.setMinimumSize(800, 500)
                
                layout = QVBoxLayout(dialog)
                text_edit = QTextEdit()
                text_edit.setReadOnly(True)
                text_edit.setFont(QFont("JetBrains Mono", 9))
                text_edit.setText(log_text)
                
                layout.addWidget(text_edit)
                
                btn_close = QPushButton("Закрыть")
                btn_close.clicked.connect(dialog.close)
                layout.addWidget(btn_close)
                
                dialog.exec()
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось прочитать логи: {e}")
        else:
            QMessageBox.information(self, "Логи", "Лог-файл не найден")
    
    def cleanup_old_logs(self, days=7):
        """Очистка старых логов"""
        count = self.file_manager.cleanup_old_logs(days)
        if count > 0:
            self.append_log(f"Очищено {count} старых лог-файлов")
            QMessageBox.information(self, "Очистка", f"Удалено {count} файлов")
        else:
            QMessageBox.information(self, "Очистка", "Старые логи не найдены")
    
    def closeEvent(self, event):
        """Закрытие окна"""
        if self.discovery_thread:
            self.discovery_thread.stop()
            self.discovery_thread.wait()
        
        if self.server_thread and self.server_thread.isRunning():
            reply = QMessageBox.question(self, 'Подтверждение', 
                                        'Сервер запущен. Завершить работу?',
                                        QMessageBox.StandardButton.Yes | 
                                        QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                self.append_log("Остановка сервера...")
                self.server_thread.stop()
                self.server_thread.wait()
                event.accept()
            else:
                event.ignore()
        else:
            self.logger.info("Завершение работы")
            event.accept()


# ============= ТОЧКА ВХОДА =============
def main():
    """Точка входа"""
    try:
        QApplication.setStyle('Fusion')
        app = QApplication(sys.argv)
        app.setFont(QFont("Segoe UI", 10))
        
        app_icon = QIcon()
        icon_paths = [
            os.path.join(BASE_DIR, 'icon.ico'),
            os.path.join(BASE_DIR, 'static', 'favicon.ico'),
            os.path.join(BASE_DIR, 'static', 'icon.ico'),
            os.path.join(BASE_DIR, 'static', 'img', 'icon.ico')
        ]
        
        icon_found = False
        for path in icon_paths:
            if os.path.exists(path):
                app_icon = QIcon(path)
                icon_found = True
                break
        
        if not icon_found:
            app_icon = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        
        app.setWindowIcon(app_icon)
        
        window = AdminWindow()
        window.setWindowIcon(app_icon)
        window.show()
        
        return app.exec()
        
    except Exception as e:
        logging.critical(f"Критическая ошибка: {e}", exc_info=True)
        
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Критическая ошибка")
        msg.setText(f"Произошла ошибка:\n{e}")
        msg.exec()
        
        return 1


if __name__ == '__main__':
    sys.exit(main())