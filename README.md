# 保险智能问答助手（安心宝）

中文 | [English](README.en.md)

一个基于本地保险资料的问答项目。系统先检索相关资料，再调用聊天模型生成回答，支持连续追问和流式输出。

使用 FastAPI、LangChain、LangGraph 和 Chroma。向量模型与聊天模型通过远程 API 调用，共用一个 API Key。

## 可以做什么

- 读取 `data/` 中的 TXT、PDF、CSV 资料，构建向量库。
- 在网页中提问，逐步显示回答，并展示检索到的资料来源。
- 在同一会话中连续追问。
- 通过 HTTP 接口接入其他应用。

TXT 和 CSV 请使用 UTF-8 编码。PDF 需要能够提取文本；扫描件请先进行 OCR，项目不自带 OCR。

## 项目结构

```text
insurance-qa-assistant/
├── data/                    # 保险资料
├── frontend/                # 网页、脚本和前端依赖
│   └── 安心宝.html
├── config.py                # 路径、模型和检索参数
├── document_loaders.py      # TXT、PDF、CSV 加载器
├── build_vectorstore.py     # 构建和查询向量库
├── prompts.py               # 提示词
├── app.py                   # 基础检索问答
├── insurance_qa.py          # 带会话记忆的问答智能体
├── main.py                  # FastAPI 服务入口
├── requirements.txt         # 直接依赖，自动引用 lock 文件
├── requirements.lock.txt    # 依赖版本约束
├── Dockerfile               # 构建应用镜像
├── .dockerignore            # 排除不需要进入镜像的文件
└── deploy.sh                # Linux 首次部署脚本
```

## Linux 虚拟机首次部署

### 1. 准备 Docker 和项目文件

按照 [Docker 官方安装说明](https://docs.docker.com/engine/install/) 安装并启动 Docker。当前用户需要有执行 Docker 命令的权限。

把整个项目上传到虚拟机，包括 `data/`、`frontend/` 和 `.dockerignore` 等隐藏文件，然后进入项目目录：

```bash
cd /你的项目路径/insurance-qa-assistant
docker version
```

`docker version` 应显示 Client 和 Server 信息。虚拟机需要能够访问镜像仓库、Python 包源和模型 API，8000 端口不能被其他程序占用。

### 2. 检查模型配置和资料

打开 `config.py`，确认这些配置与你的模型服务匹配：

| 配置 | 用途 |
| --- | --- |
| `OPENAI_BASE_URL` | 模型服务的 OpenAI 兼容接口地址 |
| `MODEL_NAME` | 聊天模型名称 |
| `EMBED_MODEL` | 向量模型名称 |
| `DATA_PATH` | 资料目录，默认 `./data` |
| `VECTORSTORE_PATH` | 向量库目录，默认 `./chroma_vsdb` |

当前默认使用阿里云 DashScope 兼容接口。请确认你的 API Key 能调用配置中的两个模型，并将保险资料放入 `data/`。

密钥配置应保持为读取环境变量，不要把实际密钥写入代码：

```python
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
```

部署脚本的数据卷路径与默认 `VECTORSTORE_PATH` 配套；修改这个目录时，也要修改脚本中的挂载路径。

### 3. 运行部署脚本并输入密钥

```bash
bash deploy.sh
```

终端会提示输入 API Key。输入时不会显示字符，输入完成后按 Enter。向量模型和聊天模型共用这一次输入，不需要创建 `.env` 文件。

脚本依次执行：

1. 构建 `insurance-qa-assistant` 镜像。
2. 创建 `insurance-qa-data` 数据卷。
3. 启动临时容器，执行 `build_vectorstore.py` 构建向量库。
4. 初始化成功后，启动名为 `insurance-qa` 的服务容器，映射 8000 端口。

向量库在镜像构建完成后生成，保存在数据卷中。API Key 在运行容器时传入，不会通过该脚本写入镜像或 `.env` 文件。

脚本某一步失败后会停止，请先查看报错。脚本不处理已有的同名服务容器；重复部署请看下方“更新代码或保险资料”。

### 4. 检查并访问

```bash
docker ps -a --filter name=insurance-qa
docker logs --tail 100 insurance-qa
curl http://localhost:8000/health
```

浏览器访问下面的地址，将 `虚拟机IP` 替换为实际 IP：

| 页面 | 地址 |
| --- | --- |
| 聊天页面 | `http://虚拟机IP:8000/frontend/安心宝.html` |
| API 文档 | `http://虚拟机IP:8000/docs` |
| 存活检查 | `http://虚拟机IP:8000/health` |

根路径 `/` 返回 API 信息，不是聊天页面。`/health` 只检查服务是否存活；最后请在网页中提问一次，确认检索和模型调用也正常。

如果虚拟机内能访问、外部浏览器不能访问，请检查虚拟机网络模式、端口转发以及防火墙或安全组的 8000 端口规则。

## 日常启停

```bash
# 停止服务
docker stop insurance-qa

# 启动已有容器
docker start insurance-qa

# 重启服务
docker restart insurance-qa

# 持续查看日志，Ctrl+C 退出日志查看
docker logs -f --tail 100 insurance-qa
```

普通启停不需要重新输入密钥，也不需要重建向量库。当前脚本没有配置开机自动重启策略，虚拟机重启后请检查容器状态。

向量库保存在 `insurance-qa-data`，删除服务容器不会自动删除这个数据卷。聊天历史保存在服务进程内存中，服务重启后会丢失。[Docker 数据卷说明](https://docs.docker.com/engine/storage/volumes/)

## 更新代码或保险资料

当前 `data/` 随镜像复制，修改虚拟机上的文件不会自动更新运行中的容器。

更新项目文件后，可以按下面的简单流程重新部署。这期间服务会暂时不可用：

```bash
# 停止并删除旧服务容器，保留数据卷
docker stop insurance-qa
docker rm insurance-qa

# 重新输入密钥，构建镜像、更新向量库并启动服务
bash deploy.sh
```

适用于保持同一个向量模型时的代码或资料更新；请保留资料目录的完整内容，构建脚本会同步新增内容并清理已移除资料对应的向量。

更换向量模型时，应使用新的空数据卷完整构建，即使新旧模型维度相同也不要混用旧向量。可将 `deploy.sh` 中所有 `insurance-qa-data` 改为一个新名称，再执行上述重新部署流程；旧卷先保留备份。

## API 简介

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 服务存活检查 |
| POST | `/simple_ask` | 不带会话记忆的检索问答 |
| POST | `/chat` | 带会话记忆的问答 |
| POST | `/chat/stream` | SSE 流式问答 |

问答请求示例：

```json
{
  "message": "这款保险的投保年龄是多少？",
  "thread_id": "demo-session"
}
```

首次请求可以省略 `thread_id`，服务会自动生成；连续追问时复用返回的 ID。`/simple_ask` 不使用会话记忆。

## 常见问题

| 问题 | 处理方法 |
| --- | --- |
| 无法连接 Docker / 权限不足 | 确认 Docker 已启动，当前用户有 Docker 权限 |
| 容器名称已被占用 | 检查 `docker ps -a`，按更新流程处理旧容器，不要直接重复运行脚本 |
| API 鉴权失败或模型不存在 | 检查输入的 Key、`OPENAI_BASE_URL` 和两个模型名称；修正后重新部署 |
| 找不到向量库或集合 | 确认初始化步骤成功，且服务挂载同一个数据卷 |
| `$'\r'`、`bad interpreter` 等脚本错误 | 将 `deploy.sh` 保存为 UTF-8、LF 换行，再用 `bash deploy.sh` 执行 |
| PDF 没有有效文本 | 对扫描 PDF 先做 OCR，再放入 `data/` |
| Python 依赖安装失败 | 查看具体包和版本的错误，同时检查网络和包源；当前 lock 仅经过 Windows x64 / Python 3.12 验证，Linux 还需实际构建验证 |

当前使用进程内会话记忆，请保持单个服务进程运行。Linux 镜像构建和真实模型调用是否成功，以目标虚拟机上的部署及问答结果为准。
