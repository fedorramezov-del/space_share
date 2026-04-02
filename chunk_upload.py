# chunk_upload.py
import os
import uuid
import json
import shutil
import hashlib
import threading
from datetime import datetime, timedelta
from flask import current_app, jsonify
from werkzeug.utils import secure_filename

class ChunkUploadManager:
    """Менеджер для чанковой загрузки файлов"""
    
    def __init__(self, app=None):
        self.app = app
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Инициализация с приложением"""
        self.app = app
        self.temp_dir = app.config.get('TEMP_UPLOAD_DIR', 'static/uploads/temp')
        self.chunk_size = app.config.get('CHUNK_SIZE', 5 * 1024 * 1024)
        
        # Создаём временную директорию
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Запускаем фоновую очистку
        self._start_cleanup_thread()
    
    def _start_cleanup_thread(self):
        """Фоновый поток для очистки старых чанков"""
        def cleanup_worker():
            while True:
                import time
                time.sleep(3600)  # Каждый час
                self.cleanup_old_chunks()
        
        thread = threading.Thread(target=cleanup_worker, daemon=True)
        thread.start()
    
    def get_upload_session(self, session_id):
        """Получить информацию о сессии загрузки"""
        info_path = os.path.join(self.temp_dir, session_id, 'info.json')
        if os.path.exists(info_path):
            with open(info_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None
    
    def save_chunk(self, chunk, chunk_index, total_chunks, session_id, filename, file_size):
        """Сохранить один чанк"""
        # Создаём директорию для сессии
        session_dir = os.path.join(self.temp_dir, session_id)
        os.makedirs(session_dir, exist_ok=True)
        
        # Сохраняем чанк
        chunk_path = os.path.join(session_dir, f'chunk_{chunk_index:06d}')
        chunk.save(chunk_path)
        
        # Обновляем информацию о сессии
        info_path = os.path.join(session_dir, 'info.json')
        
        if os.path.exists(info_path):
            with open(info_path, 'r', encoding='utf-8') as f:
                info = json.load(f)
        else:
            info = {
                'session_id': session_id,
                'filename': filename,
                'file_size': file_size,
                'total_chunks': total_chunks,
                'uploaded_chunks': [],
                'created_at': datetime.now().isoformat(),
                'last_update': datetime.now().isoformat()
            }
        
        # Добавляем загруженный чанк
        if chunk_index not in info['uploaded_chunks']:
            info['uploaded_chunks'].append(chunk_index)
        
        info['last_update'] = datetime.now().isoformat()
        
        with open(info_path, 'w', encoding='utf-8') as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
        
        # Проверяем, все ли чанки загружены
        is_complete = len(info['uploaded_chunks']) == total_chunks
        
        return {
            'chunk_index': chunk_index,
            'uploaded': len(info['uploaded_chunks']),
            'total': total_chunks,
            'complete': is_complete,
            'session_id': session_id
        }
    
    def assemble_file(self, session_id, user_id, description=None, batch_id=None):
        """Собрать файл из чанков"""
        session_dir = os.path.join(self.temp_dir, session_id)
        info_path = os.path.join(session_dir, 'info.json')
        
        if not os.path.exists(info_path):
            raise Exception("Сессия не найдена")
        
        with open(info_path, 'r', encoding='utf-8') as f:
            info = json.load(f)
        
        # Проверяем, все ли чанки на месте
        total_chunks = info['total_chunks']
        uploaded_chunks = sorted(info['uploaded_chunks'])
        
        if len(uploaded_chunks) != total_chunks:
            raise Exception(f"Не все чанки загружены: {len(uploaded_chunks)}/{total_chunks}")
        
        # Проверяем последовательность
        for i in range(total_chunks):
            if i not in uploaded_chunks:
                raise Exception(f"Отсутствует чанк {i}")
        
        # Собираем файл
        original_filename = info['filename']
        ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else 'bin'
        storage_filename = f"{uuid.uuid4().hex}.{ext}"
        final_path = os.path.join(current_app.config['UPLOAD_FOLDER'], storage_filename)
        
        # Собираем чанки в один файл
        with open(final_path, 'wb') as outfile:
            for i in range(total_chunks):
                chunk_path = os.path.join(session_dir, f'chunk_{i:06d}')
                with open(chunk_path, 'rb') as infile:
                    outfile.write(infile.read())
        
        # Получаем размер
        file_size = os.path.getsize(final_path)
        
        # Очищаем временные файлы
        shutil.rmtree(session_dir)
        
        # Создаём запись в БД
        from models import File
        
        new_file = File(
            filename=original_filename,
            storage_filename=storage_filename,
            user_id=user_id,
            batch_id=batch_id,
            description=description,
            file_size=file_size
        )
        
        return new_file
    
    def get_progress(self, session_id):
        """Получить прогресс загрузки"""
        info = self.get_upload_session(session_id)
        if not info:
            return None
        
        total = info['total_chunks']
        uploaded = len(info['uploaded_chunks'])
        
        return {
            'session_id': session_id,
            'filename': info['filename'],
            'file_size': info['file_size'],
            'uploaded_chunks': uploaded,
            'total_chunks': total,
            'percent': (uploaded / total) * 100 if total > 0 else 0,
            'complete': uploaded == total
        }
    
    def abort_upload(self, session_id):
        """Прервать загрузку и очистить чанки"""
        session_dir = os.path.join(self.temp_dir, session_id)
        if os.path.exists(session_dir):
            shutil.rmtree(session_dir)
            return True
        return False
    
    def cleanup_old_chunks(self, max_age_hours=24):
        """Очистить старые незавершённые загрузки"""
        now = datetime.now()
        cleaned = 0
        
        for session_id in os.listdir(self.temp_dir):
            session_dir = os.path.join(self.temp_dir, session_id)
            if not os.path.isdir(session_dir):
                continue
            
            info_path = os.path.join(session_dir, 'info.json')
            if os.path.exists(info_path):
                try:
                    with open(info_path, 'r', encoding='utf-8') as f:
                        info = json.load(f)
                    
                    last_update = datetime.fromisoformat(info['last_update'])
                    age_hours = (now - last_update).total_seconds() / 3600
                    
                    if age_hours > max_age_hours:
                        shutil.rmtree(session_dir)
                        cleaned += 1
                except:
                    # Если файл повреждён - удаляем
                    shutil.rmtree(session_dir)
                    cleaned += 1
            else:
                # Нет info.json - удаляем
                shutil.rmtree(session_dir)
                cleaned += 1
        
        return cleaned

# Создаём глобальный экземпляр
chunk_manager = ChunkUploadManager()