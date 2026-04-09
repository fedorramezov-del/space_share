// upload.js - отдельный файл для логики загрузки
document.addEventListener('DOMContentLoaded', () => {
    const fileInput = document.getElementById('file-input');
    const dropZone = document.getElementById('drop-zone');
    const selectFilesBtn = document.getElementById('select-files-btn');
    const fileNameDisplay = document.getElementById('file-name');
    const previewContainer = document.getElementById('preview-container');
    const uploadForm = document.getElementById('upload-form');
    const progressWrapper = document.getElementById('progress-wrapper');
    const progressBar = document.getElementById('progress-bar');
    const progressPercent = document.getElementById('progress-percent');
    const progressStatus = document.getElementById('progress-status');
    const submitBtn = document.getElementById('submit-btn');
    const fileCountSpan = document.getElementById('file-count');
    const limitWarning = document.getElementById('file-limit-warning');

    const MAX_FILES = 10; // Максимальное количество файлов

    // =====================================
    // КНОПКА ВЫБОРА ФАЙЛОВ (отдельно от drag and drop)
    // =====================================
    if (selectFilesBtn && fileInput) {
        selectFilesBtn.addEventListener('click', () => {
            if (!dropZone.classList.contains('limit-reached')) {
                fileInput.click();
            } else {
                showLimitNotification('Достигнут лимит в 10 файлов');
            }
        });
    }

    // =====================================
    // DRAG AND DROP ТОЛЬКО ДЛЯ ЗОНЫ
    // =====================================
    if (dropZone && fileInput) {
        // Предотвращаем стандартное поведение браузера
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            document.body.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
            });
        });

        // Подсветка при наведении на зону
        dropZone.addEventListener('dragenter', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (!dropZone.classList.contains('limit-reached')) {
                dropZone.classList.add('drag-active');
            }
        });

        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (!dropZone.classList.contains('limit-reached')) {
                dropZone.classList.add('drag-active');
            }
        });

        dropZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove('drag-active');
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove('drag-active');

            // Если лимит достигнут - не принимаем файлы
            if (dropZone.classList.contains('limit-reached')) {
                showLimitNotification('Достигнут лимит в 10 файлов');
                return;
            }

            // Получаем файлы из события drop
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                // Проверяем не превысит ли лимит
                const totalFiles = fileInput.files.length + files.length;
                if (totalFiles > MAX_FILES) {
                    showLimitNotification(`Можно загрузить не более ${MAX_FILES} файлов`);
                    return;
                }
                
                // Создаем новый FileList с добавленными файлами
                const newFiles = combineFileLists(fileInput.files, files);
                fileInput.files = newFiles;
                handleFileSelect(newFiles);
            }
        });

        // Клик по зоне не вызывает выбор файлов
        // (мы используем отдельную кнопку)
    }

    // =====================================
    // ОБРАБОТКА ВЫБОРА ФАЙЛОВ
    // =====================================
    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            const files = e.target.files;
            if (files.length > MAX_FILES) {
                showLimitNotification(`Можно выбрать не более ${MAX_FILES} файлов`);
                // Ограничиваем количество файлов
                const limitedFiles = limitFileList(files, MAX_FILES);
                fileInput.files = limitedFiles;
                handleFileSelect(limitedFiles);
            } else {
                handleFileSelect(files);
            }
        });
    }

    // Функция для объединения двух FileList объектов
    function combineFileLists(list1, list2) {
        const dataTransfer = new DataTransfer();
        
        // Добавляем файлы из первого списка
        for (let i = 0; i < list1.length; i++) {
            if (i < MAX_FILES) {
                dataTransfer.items.add(list1[i]);
            }
        }
        
        // Добавляем файлы из второго списка
        for (let i = 0; i < list2.length; i++) {
            if (dataTransfer.files.length < MAX_FILES) {
                dataTransfer.items.add(list2[i]);
            }
        }
        
        return dataTransfer.files;
    }

    // Функция для ограничения количества файлов
    function limitFileList(files, max) {
        const dataTransfer = new DataTransfer();
        for (let i = 0; i < Math.min(files.length, max); i++) {
            dataTransfer.items.add(files[i]);
        }
        return dataTransfer.files;
    }

    function handleFileSelect(files) {
        if (!fileNameDisplay || !previewContainer || !fileCountSpan) return;

        previewContainer.innerHTML = '';

        if (!files || files.length === 0) {
            fileNameDisplay.textContent = "Файлы не выбраны";
            fileCountSpan.textContent = "0";
            dropZone.classList.remove('limit-reached');
            if (selectFilesBtn) selectFilesBtn.disabled = false;
            if (submitBtn) submitBtn.disabled = false;
            if (limitWarning) limitWarning.style.display = 'none';
            return;
        }

        const fileCount = files.length;
        fileCountSpan.textContent = fileCount;
        
        // Обновляем отображение счетчика
        fileNameDisplay.textContent = `Выбрано файлов: ${fileCount}`;

        // Проверяем достижение лимита
        if (fileCount >= MAX_FILES) {
            dropZone.classList.add('limit-reached');
            if (selectFilesBtn) selectFilesBtn.disabled = true;
            if (limitWarning) limitWarning.style.display = 'inline';
        } else {
            dropZone.classList.remove('limit-reached');
            if (selectFilesBtn) selectFilesBtn.disabled = false;
            if (limitWarning) limitWarning.style.display = 'none';
        }

        // Блокируем кнопку отправки если нет файлов
        if (submitBtn) {
            submitBtn.disabled = fileCount === 0;
        }

        Array.from(files).forEach(file => {
            const fileCard = createFilePreviewCard(file);
            previewContainer.appendChild(fileCard);
        });
    }

    function createFilePreviewCard(file) {
        const fileCard = document.createElement('div');
        fileCard.style.display = "flex";
        fileCard.style.alignItems = "center";
        fileCard.style.gap = "12px";
        fileCard.style.padding = "10px";
        fileCard.style.marginBottom = "8px";
        fileCard.style.borderRadius = "8px";
        fileCard.style.background = "rgba(255,255,255,0.03)";
        fileCard.style.border = "1px solid var(--glass-border)";

        const ext = file.name.split('.').pop().toLowerCase();

        // Иконка в зависимости от типа
        const icon = document.createElement('div');
        icon.style.fontSize = "24px";
        icon.style.minWidth = "32px";
        icon.style.textAlign = "center";

        if (["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"].includes(ext)) {
            icon.innerHTML = "🖼️";
        } else if (["pdf"].includes(ext)) {
            icon.innerHTML = "📕";
        } else if (["zip", "rar", "7z", "tar", "gz"].includes(ext)) {
            icon.innerHTML = "🗜️";
        } else if (["txt", "doc", "docx", "odt", "rtf"].includes(ext)) {
            icon.innerHTML = "📄";
        } else if (["mp3", "wav", "ogg", "flac", "m4a"].includes(ext)) {
            icon.innerHTML = "🎵";
        } else if (["mp4", "avi", "mov", "mkv", "webm"].includes(ext)) {
            icon.innerHTML = "🎬";
        } else {
            icon.innerHTML = "📁";
        }

        fileCard.appendChild(icon);

        // Превью для изображений
        if (["png", "jpg", "jpeg", "gif", "webp"].includes(ext)) {
            const img = document.createElement('img');
            img.style.width = "50px";
            img.style.height = "50px";
            img.style.borderRadius = "6px";
            img.style.objectFit = "cover";
            img.style.border = "1px solid var(--glass-border)";

            const reader = new FileReader();
            reader.onload = (e) => img.src = e.target.result;
            reader.readAsDataURL(file);

            fileCard.appendChild(img);
        }

        // Информация о файле
        const fileInfo = document.createElement('div');
        fileInfo.style.flex = "1";
        fileInfo.style.overflow = "hidden";

        const fileName = document.createElement('div');
        fileName.style.fontWeight = "500";
        fileName.style.marginBottom = "4px";
        fileName.style.whiteSpace = "nowrap";
        fileName.style.overflow = "hidden";
        fileName.style.textOverflow = "ellipsis";
        fileName.textContent = file.name;

        const fileSize = document.createElement('div');
        fileSize.style.fontSize = "0.8rem";
        fileSize.style.opacity = "0.7";
        fileSize.textContent = formatFileSize(file.size);

        fileInfo.appendChild(fileName);
        fileInfo.appendChild(fileSize);
        fileCard.appendChild(fileInfo);

        return fileCard;
    }

    function formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    // Функция для показа уведомления о превышении лимита
    function showLimitNotification(message) {
        // Создаем уведомление
        const notification = document.createElement('div');
        notification.className = 'limit-notification';
        notification.textContent = message;
        document.body.appendChild(notification);

        // Анимируем зону drop
        dropZone.classList.add('limit-reached');
        setTimeout(() => {
            dropZone.classList.remove('limit-reached');
        }, 500);

        // Удаляем уведомление через 3 секунды
        setTimeout(() => {
            notification.style.animation = 'slideIn 0.3s ease reverse';
            setTimeout(() => {
                notification.remove();
            }, 300);
        }, 3000);
    }

    // =====================================
    // ОТПРАВКА ФОРМЫ
    // =====================================
    if (uploadForm) {
        uploadForm.addEventListener('submit', (e) => {
            e.preventDefault();

            const files = fileInput.files;
            
            // Проверка на пустой список
            if (!files || files.length === 0) {
                showLimitNotification('Выберите файлы для загрузки');
                return;
            }

            // Проверка на превышение лимита (на всякий случай)
            if (files.length > MAX_FILES) {
                showLimitNotification(`Не более ${MAX_FILES} файлов за раз`);
                return;
            }

            const formData = new FormData(uploadForm);
            const xhr = new XMLHttpRequest();

            // Показываем прогресс
            if (progressWrapper) progressWrapper.style.display = 'block';
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.style.opacity = '0.5';
                submitBtn.textContent = 'Загрузка...';
            }
            if (selectFilesBtn) selectFilesBtn.disabled = true;

            // Прогресс загрузки
            xhr.upload.addEventListener('progress', (event) => {
                if (event.lengthComputable && progressBar && progressPercent) {
                    const percent = Math.round((event.loaded / event.total) * 100);
                    progressBar.style.width = percent + '%';
                    progressPercent.textContent = percent + '%';

                    if (progressStatus) {
                        if (percent === 100) {
                            progressStatus.textContent = 'Обработка сервером...';
                        } else {
                            progressStatus.textContent = 'Загрузка...';
                        }
                    }
                }
            });

            // Завершение
            xhr.addEventListener('load', () => {
                if (xhr.status === 200 || xhr.status === 302) {
                    window.location.href = window.location.origin + '/';
                } else {
                    let errorMsg = 'Ошибка при загрузке';
                    try {
                        const response = JSON.parse(xhr.responseText);
                        if (response.message) errorMsg = response.message;
                    } catch (e) {
                        if (xhr.responseText) errorMsg = xhr.responseText;
                    }
                    alert(errorMsg);
                    resetUI();
                }
            });

            xhr.addEventListener('error', () => {
                alert('Ошибка сети. Проверьте подключение к серверу.');
                resetUI();
            });

            function resetUI() {
                if (progressWrapper) progressWrapper.style.display = 'none';
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.style.opacity = '1';
                    submitBtn.textContent = 'Загрузить';
                }
                if (selectFilesBtn) selectFilesBtn.disabled = false;
                if (progressBar) progressBar.style.width = '0%';
                if (progressPercent) progressPercent.textContent = '0%';
                if (progressStatus) progressStatus.textContent = 'Загрузка...';
            }

            xhr.open('POST', uploadForm.action, true);
            xhr.send(formData);
        });
    }

    // =====================================
    // ЗАЩИТА ОТ СЛУЧАЙНОГО ПЕРЕТАСКИВАНИЯ
    // =====================================
    // Предотвращаем перетаскивание файлов на всю страницу
    document.addEventListener('dragover', (e) => e.preventDefault());
    document.addEventListener('drop', (e) => e.preventDefault());
});