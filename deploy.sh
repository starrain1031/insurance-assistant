#!/usr/bin/env bash
set -Eeuo pipefail

# 切换到脚本所在的项目目录
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

# 隐藏输入，两个模型共用同一个 Key
read -r -s -p "请输入 API Key（向量与聊天模型共用）: " OPENAI_API_KEY
printf '\n'

if [[ -z "${OPENAI_API_KEY//[[:space:]]/}" ]]; then
    echo "API Key 不能为空。" >&2
    exit 1
fi

export OPENAI_API_KEY
trap 'unset OPENAI_API_KEY' EXIT

# 1. 构建镜像
docker build -t insurance-qa-assistant .

# 2. 创建持久化数据卷
docker volume create insurance-qa-data

# 3. 初始化向量库
docker run --rm \
    --env OPENAI_API_KEY \
    -v insurance-qa-data:/app/chroma_vsdb \
    insurance-qa-assistant python build_vectorstore.py

# 4. 初始化成功后启动服务
docker run -d \
    --name insurance-qa \
    -p 8000:8000 \
    --env OPENAI_API_KEY \
    -v insurance-qa-data:/app/chroma_vsdb \
    insurance-qa-assistant

echo "容器已启动，可使用 docker logs insurance-qa 查看运行情况。"