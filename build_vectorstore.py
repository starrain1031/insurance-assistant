import hashlib
import json
import logging
from pathlib import Path
from threading import Lock

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config
from document_loaders import SUPPORTED_EXTENSIONS, load_documents


logger = logging.getLogger(__name__)

# 与旧脚本的默认集合隔离。
# 更换嵌入模型或向量维度时，请换一个集合名称并重新建库。
COLLECTION_NAME = "insurance_qa_v2"

# 嵌入接口每次请求的文本条数，不是片段的字符数。
BATCH_SIZE = 20


class VectorStoreBuilder:
    def __init__(self):
        base_dir = Path(__file__).resolve().parent

        self.data_path = (base_dir / config.DATA_PATH).resolve()
        self.vectorstore_path = (
            base_dir / config.VECTORSTORE_PATH
        ).resolve()

        self.supported_extensions = {
            extension.lower()
            for extension in config.SUPPORTED_EXTENSIONS
        }

        unsupported = self.supported_extensions - SUPPORTED_EXTENSIONS
        if unsupported:
            raise ValueError(
                f"尚未实现以下文件类型的加载：{sorted(unsupported)}"
            )

        self.splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", "。", "；", "，", " ", ""],
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP,
        )

        self.embedding_model = OpenAIEmbeddings(
            model=config.EMBED_MODEL,
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL,
            check_embedding_ctx_length=False,
            chunk_size=BATCH_SIZE,
            model_kwargs={"encoding_format": "float"},
            request_timeout=60,
            max_retries=2,
        )

        self._store: Chroma | None = None
        self._store_lock = Lock()

    def _open_store(self, *, create: bool) -> Chroma:
        """延迟初始化并复用连接，避免并发请求重复创建。"""
        with self._store_lock:
            if self._store is None:
                self._store = Chroma(
                    collection_name=COLLECTION_NAME,
                    persist_directory=str(self.vectorstore_path),
                    embedding_function=self.embedding_model,
                    create_collection_if_not_exists=create,
                )
            return self._store

    def _chunk_id(self, document: Document) -> str:
        """根据内容和位置信息生成稳定 ID。"""
        metadata = dict(document.metadata)

        # 使用相对路径，避免项目移动后 ID 全部改变。
        metadata["source"] = (
            Path(metadata["source"])
            .relative_to(self.data_path)
            .as_posix()
        )

        payload = json.dumps(
            {
                "content": document.page_content,
                "metadata": metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _collect_chunks(self) -> dict[str, Document]:
        """先完成所有文件的解析和分块，再修改数据库。"""
        if not self.data_path.is_dir():
            raise NotADirectoryError(
                f"数据目录不存在或不是目录：{self.data_path}"
            )

        files = sorted(
            path
            for path in self.data_path.rglob("*")
            if path.is_file()
            and path.suffix.lower() in self.supported_extensions
        )

        if not files:
            raise ValueError(
                f"数据目录中没有支持的文件：{self.data_path}"
            )

        chunks_by_id: dict[str, Document] = {}

        for path in files:
            try:
                documents = load_documents(path)
                chunks = self.splitter.split_documents(documents)
                chunks = [
                    chunk
                    for chunk in chunks
                    if chunk.page_content.strip()
                ]

                if not chunks:
                    raise ValueError("文档分块结果为空")

                for chunk_index, chunk in enumerate(chunks):
                    chunk.metadata["chunk_index"] = chunk_index
                    chunks_by_id[self._chunk_id(chunk)] = chunk

                logger.info(
                    "读取 %s：%d 个文档，%d 个片段",
                    path.name,
                    len(documents),
                    len(chunks),
                )
            except Exception as exc:
                raise RuntimeError(
                    f"处理文件失败：{path}；原因：{exc}"
                ) from exc

        return chunks_by_id

    def build_store(self) -> Chroma:
        chunks_by_id = self._collect_chunks()
        db = self._open_store(create=True)

        existing_ids = set(db.get(include=["metadatas"])["ids"])
        current_ids = set(chunks_by_id)

        # 已存在且未变化的片段不再调用嵌入接口。
        new_ids = sorted(current_ids - existing_ids)

        for start in range(0, len(new_ids), BATCH_SIZE):
            batch_ids = new_ids[start:start + BATCH_SIZE]

            db.add_documents(
                documents=[
                    chunks_by_id[document_id]
                    for document_id in batch_ids
                ],
                ids=batch_ids,
            )

            logger.info(
                "新增入库：%d/%d",
                min(start + BATCH_SIZE, len(new_ids)),
                len(new_ids),
            )

        # 新片段全部写入成功后，再清理旧片段。
        # 包括内容修改，以及源文件删除后留下的记录。
        stale_ids = sorted(existing_ids - current_ids)

        for start in range(0, len(stale_ids), BATCH_SIZE):
            db.delete(ids=stale_ids[start:start + BATCH_SIZE])

        logger.info(
            "建库完成：当前 %d 个片段，新增 %d 个，删除旧片段 %d 个",
            len(current_ids),
            len(new_ids),
            len(stale_ids),
        )

        return db

    def query_store(self, query: str) -> list[Document]:
        query = query.strip()

        if not query:
            raise ValueError("查询内容不能为空")

        if config.TOP_K <= 0:
            raise ValueError("TOP_K 必须大于 0")

        if not self.vectorstore_path.is_dir():
            raise FileNotFoundError(
                "向量数据库目录不存在，请先运行 build_store()"
            )

        # 查询时不自动创建空集合。
        db = self._open_store(create=False)

        return db.similarity_search(
            query=query,
            k=config.TOP_K,
        )

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    VectorStoreBuilder().build_store()
