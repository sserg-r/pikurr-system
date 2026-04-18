import streamlit as st
import logging
import sys
import contextlib
from io import StringIO
import time

# Импорт задач и конфига
from src.core.config import settings
from src.tasks.initialize import InitializeTask
from src.tasks.download import DownloadTilesTask
from src.tasks.segmentate import SegmentationTask
from src.tasks.usability import UsabilityTask
from src.tasks.classify import ClassificationTask
from src.tasks.save_db import SaveStatsTask
from src.services.db import DatabaseService
from src.services.notifier import TelegramNotifier
from src.tasks.export import ExportTask
from src.tasks.package import PackageTask
from src.tasks.push import PushTask

# --- 1. НАСТРОЙКА СТРАНИЦЫ ---
st.set_page_config(
    page_title="PIKURR Admin",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded" # Сайдбар открыт
)

# --- 2. CSS СТИЛИ (КОМПАКТНОСТЬ) ---
st.markdown("""
    <style>
        /* Уменьшаем отступы */
        .block-container { padding-top: 1rem; padding-bottom: 2rem; }
        h1 { margin-bottom: 0.5rem; padding-bottom: 0rem; }
        /* Стиль для логов */
        .stCode { font-family: 'Consolas', monospace; font-size: 0.85rem; }
        /* Компактные алерты */
        .stAlert { padding: 0.5rem; margin-bottom: 0.5rem; }
    </style>
""", unsafe_allow_html=True)

st.title("🛰️ PIKURR: Панель управления")

# --- 3. БОКОВАЯ ПАНЕЛЬ (ИНФО О СИСТЕМЕ) ---
with st.sidebar:
    st.header("⚙️ Статус системы")
    
    # --- Проверка БД ---
    try:
        db = DatabaseService(settings)
        # Простой пинг базы
        db.execute_query("SELECT 1")
        st.success("✅ **Database:** Connected")
    except Exception as e:
        st.error(f"❌ **Database:** Error\n{e}")

    st.markdown("---")
    
    # --- Инфо о сервисах ---
    st.markdown("**🔌 Сервисы:**")
    # TF Serving (просто выводим конфиг, пинговать gRPC сложно из streamlit без клиента)
    st.info(f"✅ **TF Serving (GPU)**")
    
    # GEE
    project = settings.gee.project
    st.info(f"✅ **GEE Service Account**")

    st.markdown("---")

    # --- Пути ---
    st.markdown("**📂 Хранилище:**")
    st.caption("Input Data Dir:")
    st.code(str(settings.paths.data_input), language="bash")

        # --- Пути ---    
    st.caption("Output Data Dir:")
    st.code(str(settings.paths.data_output), language="bash")
    
    # st.caption("Tiles Cache:")
    # st.code(str(settings.paths.tiles_dir), language="bash")

# --- 4. ЛОГИКА ЛОГИРОВАНИЯ ---
class StreamlitLogHandler(logging.Handler):
    """Перехват логов logging"""
    def __init__(self, widget, buffer):
        super().__init__()
        self.widget = widget
        self.buffer = buffer

    def emit(self, record):
        msg = self.format(record)
        self.buffer.write(msg + "\n")
        self.widget.code(self.buffer.getvalue(), language="text")

class StreamlitStdout:
    """Перехват print()"""
    def __init__(self, widget, buffer):
        self.widget = widget
        self.buffer = buffer
    
    def write(self, data):
        clean = data.replace('\r', '').strip()
        if clean:
            # Добавляем метку времени для принтов
            timestamp = time.strftime("%H:%M:%S")
            self.buffer.write(f"[{timestamp}] [STDOUT] {clean}\n")
            self.widget.code(self.buffer.getvalue(), language="text")
            
    def flush(self): pass

# --- 5. ОСНОВНОЙ ИНТЕРФЕЙС ---
col_ctrl, col_logs = st.columns([4, 6])

with col_ctrl:
    st.subheader("🚀 Запуск пайплайна")
    
    import os
    delivery_configured = bool(os.environ.get('DELIVERY_HOST', ''))

    start_btn = st.button("ЗАПУСТИТЬ ПОЛНЫЙ ЦИКЛ (ETL)", type="primary", use_container_width=True)
    push_btn  = st.button(
        "📤 ОТПРАВИТЬ ПАКЕТ НА СЕРВЕР",
        use_container_width=True,
        disabled=not delivery_configured,
        help="Требует DELIVERY_HOST в .env" if not delivery_configured else "rsync последнего пакета на сервер"
    )

    st.markdown("### 📝 Этапы выполнения")

    # Сетка статусов (2 колонки)
    gc1, gc2 = st.columns(2)

    steps_ui = {
        1: gc1.empty(),
        2: gc2.empty(),
        3: gc1.empty(),
        4: gc2.empty(),
        5: gc1.empty(),
        6: gc2.empty(),
        7: gc1.empty(),
        8: gc2.empty(),
        9: gc1.empty(),
    }

    # Начальное состояние
    steps_ui[1].info("1. Инициализация")
    steps_ui[2].info("2. Загрузка тайлов")
    steps_ui[3].info("3. Сегментация (ML)")
    steps_ui[4].info("4. Анализ GEE")
    steps_ui[5].info("5. Классификация")
    steps_ui[6].info("6. Статистика БД")
    steps_ui[7].info("7. Публикация данных")
    steps_ui[8].info("8. Сбор пакета обновлений")
    if delivery_configured:
        steps_ui[9].info("9. Отправка на сервер")
    else:
        steps_ui[9].empty()

with col_logs:
    st.subheader("📋 Системный журнал")
    # Окно логов с фиксированной высотой (скролл)
    log_container = st.container(height=450)
    log_widget = log_container.empty()
    log_widget.code("Готов к работе...", language="text")

# --- 6. ФУНКЦИЯ ЗАПУСКА ---
def run_pipeline():
    # Инициализация оповещателя
    notifier = TelegramNotifier()

    log_buffer = StringIO()
    
    # Настройка логгера
    root_logger = logging.getLogger()
    for h in root_logger.handlers: root_logger.removeHandler(h)
    
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
    handler = StreamlitLogHandler(log_widget, log_buffer)
    handler.setFormatter(formatter)
    
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    try:
        notifier.send("🚀 Запущен полный цикл ETL обработки.", status="info")
        # Перехват stdout для print()
        with contextlib.redirect_stdout(StreamlitStdout(log_widget, log_buffer)):
            
            # --- STEP 1 ---
            steps_ui[1].warning("⏳ 1. Инициализация...")
            # InitializeTask(settings).run()
            InitializeTask().run()
            steps_ui[1].success("✅ 1. Инициализация: OK")

            # --- STEP 2 ---
            steps_ui[2].warning("⏳ 2. Загрузка тайлов...")
            DownloadTilesTask().run()
            # DownloadTilesTask(settings).run()
            steps_ui[2].success("✅ 2. Загрузка тайлов: OK")

            # --- STEP 3 ---
            steps_ui[3].warning("⏳ 3. Сегментация...")
            SegmentationTask().run()
            steps_ui[3].success("✅ 3. Сегментация: OK")

            # --- STEP 4 ---
            steps_ui[4].warning("⏳ 4. Анализ GEE...")
            UsabilityTask().run()
            steps_ui[4].success("✅ 4. Анализ GEE: OK")

            # --- STEP 5 ---
            steps_ui[5].warning("⏳ 5. Классификация...")
            ClassificationTask().run()
            steps_ui[5].success("✅ 5. Классификация: OK")

            # --- STEP 6 ---
            steps_ui[6].warning("⏳ 6. Сохранение...")
            SaveStatsTask().run()
            steps_ui[6].success("✅ 6. Статистика: OK")

            # --- STEP 7 ---
            steps_ui[7].warning("⏳ 7. Публикация...")
            ExportTask().run()
            steps_ui[7].success("✅ 7. Публикация: OK")

            # --- STEP 8 ---
            steps_ui[8].warning("⏳ 8. Архивация...")
            PackageTask().run()
            steps_ui[8].success("✅ 8. Архивация: OK")

            # --- STEP 9 (опционально) ---
            if delivery_configured:
                steps_ui[9].warning("⏳ 9. Отправка на сервер...")
                PushTask().run()
                steps_ui[9].success("✅ 9. Отправка: OK")

        st.balloons()
        st.success("🎉 Обработка завершена успешно!")

        notifier.send("🎉 Пайплайн успешно завершен!\nДанные обновлены в базе.", status="success")
        
        # Обновляем таблицу результатов внизу
        show_results()

    except Exception as e:
        st.error("ОШИБКА ВЫПОЛНЕНИЯ")
        # Пишем ошибку в лог тоже
        import traceback
        log_buffer.write(f"\nCRITICAL ERROR:\n{traceback.format_exc()}")
        log_widget.code(log_buffer.getvalue(), language="text")

        # Отправляем ошибку в Телеграм (обрезаем, если слишком длинная)
        short_error = str(e)[:200]
        notifier.send(f"Процесс аварийно остановлен!\n\nОшибка: `{short_error}`", status="error")

def show_results():
    st.markdown("---")
    st.subheader("📊 Результаты (5 последних записей из базы данных)")
    db = DatabaseService(settings)
    try:
        # Считаем общее кол-во
        count = db.execute_query("SELECT count(*) as c FROM assessment").iloc[0]['c']
        st.caption(f"Всего записей: {count}")
        
        # Показываем таблицу
        df = db.execute_query("""            
            SELECT id, fid_ext, year, 
                   TO_CHAR(updated_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Minsk', 'dd.mm.yyyy HH24:MI') as updated_at, 
                   stats 
            FROM assessment 
            ORDER BY updated_at DESC LIMIT 5
        """)
        st.dataframe(df, use_container_width=True)
    except:
        pass

def run_push():
    log_buffer = StringIO()
    root_logger = logging.getLogger()
    for h in root_logger.handlers: root_logger.removeHandler(h)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
    handler = StreamlitLogHandler(log_widget, log_buffer)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    try:
        steps_ui[9].warning("⏳ 9. Отправка на сервер...")
        with contextlib.redirect_stdout(StreamlitStdout(log_widget, log_buffer)):
            PushTask().run()
        steps_ui[9].success("✅ 9. Отправка: OK")
        st.success("📤 Пакет успешно отправлен на сервер!")
    except Exception as e:
        steps_ui[9].error("❌ 9. Ошибка отправки")
        import traceback
        log_buffer.write(f"\nERROR:\n{traceback.format_exc()}")
        log_widget.code(log_buffer.getvalue(), language="text")
        st.error(str(e))


# Обработка кнопок
if start_btn:
    log_widget.code("", language="text")
    run_pipeline()
elif push_btn:
    log_widget.code("", language="text")
    run_push()
else:
    show_results()