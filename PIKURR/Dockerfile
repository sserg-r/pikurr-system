# Используем slim версию Python, она легче
FROM python:3.10-slim

# 1. Устанавливаем системные зависимости
# gdal-bin нужен для команды ogr2ogr, которую мы используем в subprocess
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 2. Настройка переменных для GDAL (чтобы Python его нашел)
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal
ENV PYTHONUNBUFFERED=1 

# 3. Рабочая директория
WORKDIR /app

# 4. Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Копируем весь код проекта
COPY . .


# 6. Указываем путь к коду, чтобы импорты работали
ENV PYTHONPATH=/app

ENV FORCE_REBUILD=2025-12-16-v1
# Команда по умолчанию (можно переопределить в docker-compose)
# CMD ["python", "pipeline.py"]
CMD ["streamlit", "run", "dashboard.py", "--server.address=0.0.0.0"]