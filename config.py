# config.py
# 项目配置文件

import os

# 路径配置
DATA_PATH = "./data"
VECTORSTORE_PATH = "./chroma_vsdb"
# 支持的文件类型
SUPPORTED_EXTENSIONS = ['.txt', '.pdf', '.csv']

# 分割参数
CHUNK_SIZE = 150
CHUNK_OVERLAP = 20

# 检索参数
TOP_K = 3

# LLM 模型配置
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL_NAME = "qwen3.7-flash-2026-07-15"
EMBED_MODEL = "qwen3.7-text-embedding"
