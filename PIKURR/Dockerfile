# Раунд 7 (prompts/PROMPT_onnx_inference_round7.md): инференс переведён на
# ONNX Runtime + CUDAExecutionProvider — TensorFlow не поддерживает GPU
# Blackwell (RTX 5070 Ti, sm_120), см. project_pikurr_status.md.
#
# Базовый образ сменён с python:3.10-slim на CUDA-образ NVIDIA по двум
# причинам, обе подтверждены практически на Шаге 0 ТЗ:
# - onnxruntime-gpu нужен полноценный CUDA toolkit + cuDNN (cuBLAS и т.д.),
#   pip-экстры onnxruntime-gpu[cuda,cudnn] сами по себе не тянут cuBLAS —
#   на голом python-образе падает с libcublasLt.so.12: cannot open shared
#   object file;
# - onnxruntime-gpu>=1.24 не имеет колёс под Python 3.10 — нужен 3.11+.
#   ubuntu22.04-based CUDA-образы дают из коробки только 3.10, поэтому
#   базовый дистрибутив — ubuntu24.04 (Python 3.12).
FROM nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04

# 1. Системные зависимости: python3 (3.12), gdal-bin для ogr2ogr (subprocess),
# rsync/openssh для доставки пакетов.
# gdal-bin/libgdal-dev на ubuntu24.04 тянут за собой apt-пакет python3-numpy —
# он конфликтует с pip-версией numpy при установке requirements.txt в системный
# python (pip не может его удалить: "RECORD file not found", пакет от apt).
# Поэтому зависимости ставятся в venv, полностью изолированный от apt-пакетов.
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    gdal-bin \
    libgdal-dev \
    gcc \
    g++ \
    rsync \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# 2. Настройка переменных для GDAL (чтобы Python его нашел)
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal
ENV PYTHONUNBUFFERED=1

# venv на PATH — дальнейшие "python"/"pip" резолвятся сюда, обходя
# externally-managed системный python3 и apt-пакет python3-numpy
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 3. Рабочая директория
WORKDIR /app

# 4. Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Копируем весь код проекта
COPY . .


# 6. Указываем путь к коду, чтобы импорты работали
ENV PYTHONPATH=/app

ENV FORCE_REBUILD=2026-09-15-onnx-round7
# Команда по умолчанию (можно переопределить в docker-compose)
# CMD ["python", "pipeline.py"]
CMD ["streamlit", "run", "dashboard.py", "--server.address=0.0.0.0"]
