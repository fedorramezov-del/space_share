document.addEventListener('DOMContentLoaded', () => {

    // =====================================
    // УТИЛИТА: получить accent-color в rgba
    // =====================================
    function getAccentRGBA(opacity) {
        const accent = getComputedStyle(document.documentElement)
            .getPropertyValue('--accent-color')
            .trim();

        if (!accent.startsWith("#")) return accent;

        const hex = accent.replace('#', '');
        const bigint = parseInt(hex, 16);

        const r = (bigint >> 16) & 255;
        const g = (bigint >> 8) & 255;
        const b = bigint & 255;

        return `rgba(${r}, ${g}, ${b}, ${opacity})`;
    }

    // =====================================
    // 1. Авто-скрытие flash
    // =====================================
    document.querySelectorAll('.flash').forEach(flash => {
        setTimeout(() => {
            flash.style.opacity = '0';
            flash.style.transition = 'opacity 0.5s ease';
            setTimeout(() => flash.remove(), 500);
        }, 5000);
    });

    // =====================================
    // 2. Активный пункт меню
    // =====================================
    const currentPath = window.location.pathname;
    document.querySelectorAll('nav a').forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });

    // =====================================
    // 3. Динамическая граница блоков
    // =====================================
    document.querySelectorAll('.action-btn').forEach(button => {

        button.addEventListener('mousedown', () => {
            button.style.transform = 'scale(0.95)';
        });

        button.addEventListener('mouseup', () => {
            button.style.transform = 'scale(1)';
        });

        button.addEventListener('mouseenter', () => {

            const parentBlock = button.closest('.file-batch');
            if (!parentBlock) return;

            const accent = getComputedStyle(document.documentElement)
                .getPropertyValue('--accent-color')
                .trim();

            parentBlock.style.setProperty('--dynamic-border', accent);
            parentBlock.classList.add('dynamic-border-active');
        });

        button.addEventListener('mouseleave', () => {
            const parentBlock = button.closest('.file-batch');
            if (!parentBlock) return;

            parentBlock.classList.remove('dynamic-border-active');
        });
    });

    // =====================================
    // 4. THEME DROPDOWN
    // =====================================
    const themeBtn = document.getElementById('theme-toggle-btn');
    const dropdown = document.getElementById('theme-dropdown');

    if (themeBtn && dropdown) {

        themeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.style.display =
                dropdown.style.display === 'block' ? 'none' : 'block';
        });

        document.addEventListener('click', (e) => {
            if (!e.target.closest('#theme-dropdown') &&
                !e.target.closest('#theme-toggle-btn')) {
                dropdown.style.display = 'none';
            }
        });
    }

    // =====================================
    // 5. THEME SWITCHER
    // =====================================
    const themeOptions = document.querySelectorAll('.theme-option');

    themeOptions.forEach(option => {
        option.addEventListener('click', async () => {

            const selectedTheme = option.dataset.theme;

            // применяем тему мгновенно
            document.documentElement.setAttribute('data-theme', selectedTheme);

            if (dropdown) dropdown.style.display = 'none';

            try {
                await fetch("/set_theme", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": document
                            .querySelector('meta[name="csrf-token"]')
                            ?.content
                    },
                    body: JSON.stringify({ theme: selectedTheme })
                });
            } catch (err) {
                console.error("Проблема с загрузкой темы:", err);
            }
        });
    });

    // =====================================
    // 6. THEME BUILDER
    // =====================================

    const builder = document.getElementById("theme-builder");
    const accentInput = document.getElementById("tb-accent");
    const bgInput = document.getElementById("tb-bg");
    const containerInput = document.getElementById("tb-container");
    const saveBtn = document.getElementById("save-custom-theme");

    // показываем builder если выбрали custom
    document.querySelectorAll('.theme-option').forEach(option => {
        option.addEventListener("click", () => {
            if (option.dataset.theme === "custom") {
                if (builder) builder.style.display = "flex";
            } else {
                if (builder) builder.style.display = "none";
            }
        });
    });

    // LIVE PREVIEW
    function applyCustomTheme() {
        if (accentInput) document.documentElement.style.setProperty("--custom-accent", accentInput.value);
        if (bgInput) document.documentElement.style.setProperty("--custom-bg", bgInput.value);
        if (containerInput) document.documentElement.style.setProperty("--custom-container", containerInput.value);
    }

    if (accentInput && bgInput && containerInput) {

        accentInput.addEventListener("input", applyCustomTheme);
        bgInput.addEventListener("input", applyCustomTheme);
        containerInput.addEventListener("input", applyCustomTheme);
    }

    // SAVE TO SERVER
    if (saveBtn) {
        saveBtn.addEventListener("click", async () => {

            saveBtn.classList.add("loading-btn");
            saveBtn.disabled = true;

            const themeData = {
                theme: "custom",
                accent: accentInput ? accentInput.value : '#38bdf8',
                bg: bgInput ? bgInput.value : '#0b1120',
                container: containerInput ? containerInput.value : '#1e293b'
            };

            try {
                await fetch("/set_theme", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": document
                            .querySelector('meta[name="csrf-token"]')
                            ?.content
                    },
                    body: JSON.stringify(themeData)
                });

                showToast("Тема сохранена 💾", "success");

            } catch (err) {

                showToast("Ошибка сохранения темы ❌", "error");
                console.error("Theme save error:", err);

            } finally {
                saveBtn.classList.remove("loading-btn");
                saveBtn.disabled = false;
            }
        });
    }
    
    // =====================================
    // 7. MICRO-FEEDBACK: TOAST SYSTEM
    // =====================================

    function showToast(message, type = "success") {

        let container = document.getElementById("toast-container");

        if (!container) {
            container = document.createElement("div");
            container.id = "toast-container";
            document.body.appendChild(container);
        }

        const toast = document.createElement("div");
        toast.className = `toast ${type}`;
        toast.innerText = message;

        container.appendChild(toast);

        setTimeout(() => {
            toast.remove();
        }, 4000);
    }
    
    // =====================================
    // 8. FLASH → TOAST
    // =====================================

    document.querySelectorAll(".flash").forEach(flash => {

        const type = flash.classList.contains("error") ? "error" : "success";
        showToast(flash.innerText, type);

        flash.remove();
    });
    
    // =====================================
    // 9. FORM LOADING STATE
    // =====================================

    document.querySelectorAll("form").forEach(form => {

        form.addEventListener("submit", function () {

            const btn = form.querySelector("button[type='submit']");

            if (btn) {
                btn.classList.add("loading-btn");
                btn.disabled = true;
            }
        });
    });


}); // ← закрытие DOMContentLoaded