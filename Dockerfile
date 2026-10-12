# 使用官方Python运行时作为父镜像
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 设置工作目录为/app
WORKDIR /app

# 安装requirements.txt中指定的任何所需包
COPY requirements.txt requirements.lock.txt ./

RUN python -m pip install --no-cache-dir \
    -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
    && python -m pip check

# 将当前目录内容复制到容器中
COPY . .

EXPOSE 8000

# 在容器启动时运行python脚本
CMD ["python", "./main.py"]