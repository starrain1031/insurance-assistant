# Insurance QA Assistant (Bao Xiaobao)

[中文](README.md) | English

A question-answering app that searches your insurance documents before asking a chat model to generate an answer. It supports follow-up questions and streaming responses.

Built with FastAPI, LangChain, LangGraph, and Chroma. Both the embedding model and the chat model use a remote API and share one API key.

## Features

- Build a vector database from TXT, PDF, and CSV files in `data/`.
- Ask questions in a web interface with streaming answers and retrieved source references.
- Ask follow-up questions within the same conversation.
- Connect other applications through HTTP endpoints.

Use UTF-8 for TXT and CSV files. PDFs must contain extractable text. Run OCR on scanned PDFs first; OCR is not included in this project.

## Project structure

```text
insurance-qa-assistant/
├── data/                    # Insurance documents
├── frontend/                # Web page, scripts, and frontend dependencies
│   └── 保小宝.html
├── config.py                # Paths, models, and retrieval settings
├── document_loaders.py      # TXT, PDF, and CSV loaders
├── build_vectorstore.py     # Vector database building and search
├── prompts.py               # Prompts
├── app.py                   # Basic retrieval-based QA
├── insurance_qa.py          # QA agent with conversation memory
├── main.py                  # FastAPI entry point
├── requirements.txt         # Direct dependencies; references the lock file
├── requirements.lock.txt    # Dependency version constraints
├── Dockerfile               # Application image definition
├── .dockerignore            # Files excluded from the image build context
└── deploy.sh                # First deployment script for Linux
```

## First deployment on a Linux VM

### 1. Prepare Docker and the project

Install and start Docker using the [official installation guide](https://docs.docker.com/engine/install/). Your current user must have permission to run Docker commands.

Upload the entire project to the VM, including `data/`, `frontend/`, and hidden files such as `.dockerignore`. Enter the project directory:

```bash
cd /path/to/insurance-qa-assistant
docker version
```

`docker version` should show both Client and Server information. The VM needs access to the image registry, Python package index, and model API. Port 8000 must be available.

### 2. Check model settings and documents

Open `config.py` and check these settings against your model provider:

| Setting | Purpose |
| --- | --- |
| `OPENAI_BASE_URL` | The provider's OpenAI-compatible API endpoint |
| `MODEL_NAME` | Chat model name |
| `EMBED_MODEL` | Embedding model name |
| `DATA_PATH` | Document directory; defaults to `./data` |
| `VECTORSTORE_PATH` | Vector database directory; defaults to `./chroma_vsdb` |

The current default endpoint is Alibaba Cloud DashScope. Confirm that your API key can access both configured models, and put your insurance documents in `data/`.

Keep the API key setting as an environment variable lookup. Do not put the actual key in the source code:

```python
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
```

The script's volume mount matches the default `VECTORSTORE_PATH`. If you change that directory, update the mount path in the script too.

### 3. Run the script and enter your key

```bash
bash deploy.sh
```

The terminal prompts for an API key in Chinese. Input is hidden; paste or type your key and press Enter. Both models use this one entry. No `.env` file is needed.

The script then:

1. Builds the `insurance-qa-assistant` image.
2. Creates the `insurance-qa-data` volume.
3. Starts a temporary container to run `build_vectorstore.py`.
4. After initialization succeeds, starts the `insurance-qa` service container on port 8000.

The vector database is built after the image and stored in the volume. The script passes the API key when running containers; it does not write the key into the image or an `.env` file.

The script stops if a step fails. Read the error before retrying. It does not handle an existing service container with the same name; see “Update code or documents” before redeploying.

### 4. Check and open the app

```bash
docker ps -a --filter name=insurance-qa
docker logs --tail 100 insurance-qa
curl http://localhost:8000/health
```

Open these addresses in a browser, replacing `VM_IP` with your VM's IP:

| Page | Address |
| --- | --- |
| Chat interface | `http://VM_IP:8000/frontend/安心宝.html` |
| API documentation | `http://VM_IP:8000/docs` |
| Liveness check | `http://VM_IP:8000/health` |

The root path `/` returns API information, not the chat page. `/health` only checks whether the service is alive. Ask a question in the web interface to check retrieval and model access too.

If the app works inside the VM but not from your browser, check the VM network mode, port forwarding, and firewall or security-group rules for port 8000.

## Start, stop, and view logs

```bash
# Stop the service
docker stop insurance-qa

# Start the existing container
docker start insurance-qa

# Restart the service
docker restart insurance-qa

# Follow logs; press Ctrl+C to stop viewing them
docker logs -f --tail 100 insurance-qa
```

Normal restarts do not require another key entry or a vector database rebuild. The current script does not configure an automatic restart policy; check the container after rebooting the VM.

The vector database lives in `insurance-qa-data`. Removing the service container does not automatically remove this volume. Conversation history is stored in process memory and is lost when the service restarts. [Docker volume documentation](https://docs.docker.com/engine/storage/volumes/)

## Update code or documents

The current image includes `data/`. Editing files on the VM does not automatically update the running container.

After updating the project files, use this simple redeployment procedure. The service will be unavailable during the update:

```bash
# Stop and remove the old service container; keep the volume
docker stop insurance-qa
docker rm insurance-qa

# Enter the key again, rebuild the image, update the database, and start
bash deploy.sh
```

This applies to code or document updates that keep the same embedding model. Keep the complete document set in `data/`: the builder adds new content and removes vectors for content that is no longer present.

When switching embedding models, build the full database in a new empty volume. Do not mix old and new embeddings, even when their dimensions match. Replace every occurrence of `insurance-qa-data` in `deploy.sh` with a new volume name, then follow the redeployment procedure above. Keep the old volume as a backup initially.

## API overview

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Service liveness check |
| POST | `/simple_ask` | Retrieval-based QA without conversation memory |
| POST | `/chat` | QA with conversation memory |
| POST | `/chat/stream` | Streaming QA over SSE |

Example question request:

```json
{
  "message": "What is the eligible age range for this insurance product?",
  "thread_id": "demo-session"
}
```

You may omit `thread_id` in the first request; the service generates one. Reuse the returned ID for follow-up questions. `/simple_ask` does not use conversation memory.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Cannot connect to Docker / permission denied | Check that Docker is running and your user has permission to use it |
| Container name already in use | Check `docker ps -a` and follow the update procedure instead of rerunning the script directly |
| API authentication failure or model not found | Check the key, `OPENAI_BASE_URL`, and both model names; correct them and redeploy |
| Missing vector database or collection | Check that initialization succeeded and the service mounts the same volume |
| Script errors such as `$'\r'` or `bad interpreter` | Save `deploy.sh` as UTF-8 with LF line endings, then run `bash deploy.sh` |
| PDF has no usable text | Run OCR on scanned PDFs before placing them in `data/` |
| Python dependencies fail to install | Read the package/version error and check network and index access; the current lock was validated only on Windows x64 / Python 3.12, and Linux still needs an actual build check |

Keep a single service process while using the current in-memory conversation storage. Verify the Linux image build and real model calls on the target VM before considering deployment complete.
