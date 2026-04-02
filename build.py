# build.py
"""
Скрипт сборки Space Share с помощью PyInstaller
Создает единый исполняемый файл с иконкой и всеми ресурсами
Оптимизирован для минимального размера
"""

import os
import sys
import shutil
import platform
import subprocess
from pathlib import Path

# ============================================================================
# КОНФИГУРАЦИЯ СБОРКИ
# ============================================================================

APP_NAME = "SpaceShare"
APP_VERSION = "2.0.0"
APP_AUTHOR = "Space Share Team"
APP_DESCRIPTION = "Система обмена файлами в локальной сети"

# Путь к UPX (если установлен)
UPX_PATH = r"C:\Users\Fedor\Downloads\upx-5.1.1-win64"
USE_UPX = True

# Директории
CURRENT_DIR = Path(__file__).parent.absolute()
DIST_DIR = CURRENT_DIR / "dist"
BUILD_DIR = CURRENT_DIR / "build"
SPEC_FILE = CURRENT_DIR / "SpaceShare.spec"

# Файлы для включения
TEMPLATES_DIR = CURRENT_DIR / "templates"
STATIC_DIR = CURRENT_DIR / "static"
REQUIREMENTS_FILE = CURRENT_DIR / "requirements.txt"
ICON_FILE = CURRENT_DIR / "static" / "favicon.ico"

# Иконки для разных платформ
ICON_WINDOWS = CURRENT_DIR / "static" / "icon.ico"
ICON_MACOS = CURRENT_DIR / "static" / "icon.icns"
ICON_LINUX = CURRENT_DIR / "static" / "icon.png"

# Папки для исключения из сборки
EXCLUDED_FOLDERS = [
    'uploads',           # Загруженные пользователями файлы
    '__pycache__',
    '.git',
    '.svn',
    'node_modules',
    'venv',
    'env',
]

# Расширения файлов для исключения
EXCLUDED_EXTENSIONS = [
    '.pyc', '.pyo', '.psd', '.ai', '.map', '.scss', '.less',
    '.mp4', '.avi', '.mkv', '.mov',  # Видео (если есть)
    '.mp3', '.wav', '.flac',         # Аудио (если есть)
    '.zip', '.rar', '.7z', '.tar',   # Архивы
]

# Максимальный размер файла для включения в сборку (в байтах)
MAX_FILE_SIZE_MB = 5  # 5 MB
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Модули для исключения (уменьшают размер)
EXCLUDED_MODULES = [
    'tkinter',
    'matplotlib',
    'numpy',
    'pandas',
    'scipy',
    'test',
    'unittest',
    'pytest',
    'setuptools',
    'distutils',
    'pip',
    'idlelib',
    'turtle',
    'curses',
    'dbm',
    'sqlite3.test',
    'ctypes.test',
    'ensurepip',
    'venv',
]

# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def check_upx():
    """Проверка наличия UPX"""
    if not USE_UPX:
        return None
    
    if platform.system() == "Windows":
        upx_exe = Path(UPX_PATH) / "upx.exe"
    else:
        upx_exe = Path(UPX_PATH) / "upx"
    
    if upx_exe.exists():
        print(f"  ✓ UPX найден: {upx_exe}")
        return str(upx_exe.parent)
    else:
        print(f"  ⚠ UPX не найден в {UPX_PATH}, сжатие будет без UPX")
        return None

def clean_build():
    """Очистка старых сборок"""
    print("\n🧹 Очистка старых сборок...")
    
    for dir_path in [DIST_DIR, BUILD_DIR]:
        if dir_path.exists():
            shutil.rmtree(dir_path)
            print(f"  Удалена: {dir_path}")
    
    # Удаляем старые .spec файлы
    for spec in CURRENT_DIR.glob("*.spec"):
        spec.unlink()
        print(f"  Удален: {spec}")
    
    # Очищаем кэш __pycache__
    for pycache in CURRENT_DIR.glob("**/__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)
    
    print("✅ Очистка завершена")


def check_resource_files():
    """Проверка наличия ресурсов"""
    print("\n📁 Проверка ресурсов...")
    
    resources = {
        "templates": TEMPLATES_DIR,
        "static": STATIC_DIR,
        "app.py": CURRENT_DIR / "app.py",
        "wsgi.py": CURRENT_DIR / "wsgi.py",
        "models.py": CURRENT_DIR / "models.py",
        "config.py": CURRENT_DIR / "config.py"
    }
    
    missing = []
    for name, path in resources.items():
        if path.exists():
            print(f"  ✓ {name}")
        else:
            missing.append(str(path))
            print(f"  ✗ {name} - не найден")
    
    if missing:
        print(f"\n  ❌ Отсутствуют ресурсы:")
        for m in missing:
            print(f"     {m}")
        return False
    
    print("✅ Все ресурсы найдены")
    return True


def get_folder_size(path):
    """Получить размер папки в байтах"""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file():
                total += entry.stat().st_size
            elif entry.is_dir():
                total += get_folder_size(entry.path)
    except Exception:
        pass
    return total


def check_static_size():
    """Проверка размера папки static и предупреждение о больших файлах"""
    print("\n📊 Проверка размера статических файлов...")
    
    if not STATIC_DIR.exists():
        print("  ⚠ Папка static не найдена")
        return
    
    # Проверяем размер всей папки static
    static_size = get_folder_size(STATIC_DIR)
    static_size_mb = static_size / (1024 * 1024)
    
    print(f"  📁 Размер папки static: {static_size_mb:.2f} MB")
    
    if static_size_mb > 100:
        print(f"  ⚠ ВНИМАНИЕ! Папка static очень большая ({static_size_mb:.2f} MB)!")
        print("     Это значительно увеличит размер сборки.")
        print("     Рекомендуется очистить папку static/uploads от больших файлов.")
    
    # Ищем большие файлы
    large_files = []
    for root, dirs, files in os.walk(STATIC_DIR):
        # Исключаем uploads из проверки (потому что их и так исключим)
        if 'uploads' in dirs:
            dirs.remove('uploads')
        
        for file in files:
            file_path = os.path.join(root, file)
            try:
                size = os.path.getsize(file_path)
                if size > 10 * 1024 * 1024:  # >10 MB
                    large_files.append((file_path, size))
            except Exception:
                pass
    
    if large_files:
        print(f"\n  ⚠ Найдены большие файлы (>10 MB):")
        for file_path, size in large_files[:10]:
            size_mb = size / (1024 * 1024)
            rel_path = os.path.relpath(file_path, STATIC_DIR)
            print(f"     - {rel_path}: {size_mb:.2f} MB")
        
        if len(large_files) > 10:
            print(f"     ... и еще {len(large_files) - 10} файлов")
    
    print("✅ Проверка завершена")


def clean_uploads_folder():
    """Очистка папки uploads от больших файлов (опционально)"""
    uploads_dir = STATIC_DIR / "uploads"
    
    if not uploads_dir.exists():
        return
    
    print("\n🗑 Проверка папки uploads...")
    
    uploads_size = get_folder_size(uploads_dir)
    uploads_size_mb = uploads_size / (1024 * 1024)
    
    print(f"  📁 Размер папки static/uploads: {uploads_size_mb:.2f} MB")
    
    if uploads_size_mb > 50:
        print(f"  ⚠ Папка uploads очень большая! ({uploads_size_mb:.2f} MB)")
        print("  Эти файлы НЕ будут включены в сборку (папка uploads исключена).")
        print("  Это правильно, так как uploads - это пользовательские данные.")
    
    # Считаем количество файлов в uploads
    file_count = 0
    for root, dirs, files in os.walk(uploads_dir):
        file_count += len(files)
    
    if file_count > 0:
        print(f"  📄 Найдено файлов в uploads: {file_count}")
        print("  ✅ Папка uploads будет исключена из сборки!")


def create_icon():
    """Создание иконки, если её нет"""
    if ICON_WINDOWS.exists():
        return str(ICON_WINDOWS)
    
    # Создаем простую иконку, если нет файла
    try:
        from PIL import Image, ImageDraw
        
        # Создаем иконку 256x256
        img = Image.new('RGB', (256, 256), color='#0b1120')
        draw = ImageDraw.Draw(img)
        
        # Рисуем круг
        draw.ellipse([48, 48, 208, 208], fill='#2563eb')
        
        # Рисуем "S"
        draw.text((100, 100), "S", fill='white', font=None)
        
        # Сохраняем как ICO
        ICON_WINDOWS.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(ICON_WINDOWS), format='ICO', sizes=[(256, 256)])
        print(f"  ✓ Создана иконка: {ICON_WINDOWS}")
        return str(ICON_WINDOWS)
    except Exception as e:
        print(f"  ⚠ Не удалось создать иконку: {e}")
        return None


def optimize_static_files():
    """Оптимизация статических файлов перед сборкой"""
    print("\n🖼 Оптимизация статических файлов...")
    
    if not STATIC_DIR.exists():
        print("  ⚠ Папка static не найдена")
        return
    
    # Оптимизируем изображения в static, если есть PIL
    try:
        from PIL import Image
        
        optimized = 0
        for img_path in STATIC_DIR.glob("**/*.png"):
            # Пропускаем папку uploads
            if 'uploads' in str(img_path):
                continue
            try:
                img = Image.open(img_path)
                img.save(img_path, optimize=True, compress_level=9)
                optimized += 1
            except Exception:
                pass
        
        for img_path in STATIC_DIR.glob("**/*.jpg"):
            if 'uploads' in str(img_path):
                continue
            try:
                img = Image.open(img_path)
                img.save(img_path, optimize=True, quality=85)
                optimized += 1
            except Exception:
                pass
        
        for img_path in STATIC_DIR.glob("**/*.jpeg"):
            if 'uploads' in str(img_path):
                continue
            try:
                img = Image.open(img_path)
                img.save(img_path, optimize=True, quality=85)
                optimized += 1
            except Exception:
                pass
        
        for img_path in STATIC_DIR.glob("**/*.gif"):
            if 'uploads' in str(img_path):
                continue
            try:
                img = Image.open(img_path)
                img.save(img_path, optimize=True)
                optimized += 1
            except Exception:
                pass
        
        if optimized > 0:
            print(f"  ✓ Оптимизировано изображений: {optimized}")
    except ImportError:
        print("  ⚠ PIL не установлен, пропускаем оптимизацию изображений")
    
    # Удаляем ненужные файлы в статике (кроме uploads)
    patterns_to_remove = ['*.psd', '*.ai', '*.svg', '*.map', '*.scss', '*.less']
    for pattern in patterns_to_remove:
        for file in STATIC_DIR.glob(f"**/{pattern}"):
            if 'uploads' in str(file):
                continue
            try:
                file.unlink()
                print(f"  ✓ Удален: {file.name}")
            except Exception:
                pass
    
    print("✅ Оптимизация завершена")


def generate_spec_file():
    """Генерация оптимизированного spec файла для PyInstaller"""
    print("\n📝 Генерация оптимизированного spec файла...")
    
    icon_path = create_icon()
    icon_arg = f", icon='{icon_path}'" if icon_path else ""
    
    # Формируем список исключаемых модулей для вставки в spec файл
    excludes_list = ",\n    ".join([f"'{mod}'" for mod in EXCLUDED_MODULES])
    
    # Формируем список исключаемых папок для вставки в spec файл
    excluded_folders_list = ",\n    ".join([f"'{folder}'" for folder in EXCLUDED_FOLDERS])
    
    # Формируем список расширений для вставки в spec файл
    excluded_extensions_list = ",\n    ".join([f"'{ext}'" for ext in EXCLUDED_EXTENSIONS])
    
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec файл для {APP_NAME} v{APP_VERSION}
Оптимизирован для минимального размера
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Оптимизированный сбор данных - только необходимые файлы
datas = []

# Собираем только необходимые данные Flask
try:
    flask_datas = collect_data_files('flask')
    for src, dst in flask_datas:
        # Исключаем тестовые и ненужные файлы
        if not any(x in src for x in ['/test/', '/tests/', 'example', 'locale']):
            datas.append((src, dst))
except:
    pass

# Собираем только необходимые данные для шаблонов и статики
EXCLUDED_FOLDERS = {{
    {excluded_folders_list}
}}

EXCLUDED_EXTENSIONS = {{
    {excluded_extensions_list}
}}

MAX_FILE_SIZE_BYTES = {MAX_FILE_SIZE_BYTES}

def add_resources(resource_dir, target_dir):
    """Добавление ресурсов с фильтрацией"""
    if os.path.exists(resource_dir):
        for root, dirs, files in os.walk(resource_dir):
            # Исключаем ненужные папки (включая uploads)
            dirs[:] = [d for d in dirs if d not in EXCLUDED_FOLDERS]
            
            for file in files:
                # Исключаем файлы по расширению
                if any(file.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
                    continue
                
                # Исключаем слишком большие файлы
                file_path = os.path.join(root, file)
                try:
                    if os.path.getsize(file_path) > MAX_FILE_SIZE_BYTES:
                        continue
                except:
                    pass
                
                src = os.path.join(root, file)
                dst = os.path.join(target_dir, os.path.relpath(src, resource_dir))
                datas.append((src, dst))

# Добавляем шаблоны и статику
add_resources('templates', 'templates')
add_resources('static', 'static')

a = Analysis(
    ['wsgi.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # Только необходимые модули
        'flask',
        'flask_socketio',
        'flask_login',
        'flask_wtf',
        'flask_migrate',
        'sqlalchemy',
        'sqlalchemy.ext.declarative',
        'sqlalchemy.orm',
        'alembic',
        'pyotp',
        'qrcode',
        'PIL',
        'PIL._imaging',
        'markupsafe',
        'jinja2',
        'werkzeug',
        'wtforms',
        'engineio.async_drivers.threading',
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[
        {excludes_list}
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Оптимизированный EXE с включенным UPX сжатием
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='{APP_NAME}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False{icon_arg},
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Для Windows создаем консольную версию для отладки
if sys.platform == 'win32':
    console_exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='{APP_NAME}_console',
        debug=False,
        bootloader_ignore_signals=False,
        strip=True,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=True{icon_arg},
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
'''
    
    with open(SPEC_FILE, 'w', encoding='utf-8') as f:
        f.write(spec_content)
    
    print(f"✅ Оптимизированный spec файл создан: {SPEC_FILE}")
    return True

def run_pyinstaller():
    """Запуск PyInstaller с оптимизированными параметрами"""
    print("\n🚀 Запуск PyInstaller с оптимизацией...")
    print("   Это может занять несколько минут...")
    
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--clean',
        '--noconfirm',
        str(SPEC_FILE)
    ]
    
    if USE_UPX:
        upx_dir = check_upx()
        if upx_dir:
            cmd.insert(-1, '--upx-dir')
            cmd.insert(-1, upx_dir)
    
    try:
        env = os.environ.copy()
        env['PYINSTALLER_COMPRESS'] = '1'
        
        print(f"   Команда: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, cwd=str(CURRENT_DIR), env=env, capture_output=False)
        
        if result.returncode == 0:
            print("\n✅ Сборка завершена успешно!")
            return True
        else:
            print("\n❌ Ошибка при сборке!")
            return False
            
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        return False


def copy_additional_files():
    """Копирование дополнительных файлов в dist"""
    print("\n📋 Копирование дополнительных файлов...")
    
    if platform.system() == 'Windows':
        dist_exe_dir = DIST_DIR
    else:
        dist_exe_dir = DIST_DIR / APP_NAME
    
    if not dist_exe_dir.exists():
        dist_exe_dir.mkdir(parents=True, exist_ok=True)
    
    readme_path = CURRENT_DIR / "README.md"
    if readme_path.exists():
        shutil.copy2(readme_path, dist_exe_dir / "README.md")
        print("  ✓ README.md")
    
    license_path = CURRENT_DIR / "LICENSE"
    if license_path.exists():
        shutil.copy2(license_path, dist_exe_dir / "LICENSE")
        print("  ✓ LICENSE")
    
    version_file = dist_exe_dir / "version.txt"
    with open(version_file, 'w', encoding='utf-8') as f:
        f.write(f"{APP_NAME} v{APP_VERSION}\n")
        f.write(f"Собрано: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Платформа: {platform.platform()}\n")
        
        exe_path = DIST_DIR / f"{APP_NAME}.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            f.write(f"Размер: {size_mb:.2f} MB\n")
    print("  ✓ version.txt")
    
    print("✅ Копирование завершено")


def print_summary():
    """Вывод итоговой информации"""
    print("\n" + "="*60)
    print(f"🎉 Сборка {APP_NAME} v{APP_VERSION} завершена!")
    print("="*60)
    
    exe_path = DIST_DIR / f"{APP_NAME}.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\n📁 Исполняемый файл: {exe_path}")
        print(f"   Размер: {size_mb:.2f} MB")
        
        if size_mb > 100:
            print("   ⚠ Файл довольно большой. Рекомендации:")
            print("     • Установите UPX для дополнительного сжатия")
            print("     • Проверьте, что все библиотеки действительно нужны")
            print("     • Используйте виртуальное окружение с минимальными зависимостями")
        elif size_mb > 50:
            print("   ✓ Приемлемый размер")
        else:
            print("   🎉 Отличный результат!")
    
    print(f"\n📂 Директория сборки: {DIST_DIR}")
    
    print("\n🔧 Проверка:")
    print("   1. Запустите полученный .exe файл")
    print("   2. Откроется графическое окно панели управления")
    print("   3. Нажмите 'Запустить сервер'")
    print("   4. Откройте браузер по адресу http://localhost:5000")
    
    print("\n📝 Примечания по оптимизации:")
    print("   • Для максимального сжатия установите UPX")
    print("   • Используйте виртуальное окружение с минимальными зависимостями")
    print("   • Исключены тяжелые библиотеки (numpy, pandas, matplotlib)")
    print("   • Папка static/uploads исключена из сборки")
    print("   • Файлы больше 5 MB не включаются в сборку")
    print("   • Включено удаление отладочной информации (--strip)")
    
    print("\n" + "="*60)


# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ
# ============================================================================

def main():
    """Основная функция сборки"""
    print("="*60)
    print(f"🔨 Сборка {APP_NAME} v{APP_VERSION} (оптимизированная)")
    print(f"   Платформа: {platform.platform()}")
    print(f"   Python: {platform.python_version()}")
    print("="*60)
    
    # Проверка размера static перед сборкой
    check_static_size()
    
    # Проверка папки uploads
    clean_uploads_folder()
    
    
    # Проверяем ресурсы
    if not check_resource_files():
        sys.exit(1)
    
    # Оптимизируем статические файлы
    optimize_static_files()
    
    # Очищаем старые сборки
    clean_build()
    
    # Генерируем spec файл
    if not generate_spec_file():
        sys.exit(1)
    
    # Запускаем PyInstaller
    if not run_pyinstaller():
        sys.exit(1)
    
    # Копируем дополнительные файлы
    copy_additional_files()
    
    # Выводим итоги
    print_summary()


if __name__ == "__main__":
    main()