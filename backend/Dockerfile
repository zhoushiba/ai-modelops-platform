# AI ModelOps Platform · 后端镜像
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 先装依赖，利用镜像层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt "PyMySQL==1.1.1"

# 再拷贝业务代码
COPY app ./app
COPY samples ./samples
COPY scripts ./scripts

# 运行时目录（compose 会挂载具名卷覆盖 storage）
RUN mkdir -p /app/data /app/storage/models /app/storage/datasets /app/storage/eval

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=10 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
