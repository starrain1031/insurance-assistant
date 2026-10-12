from pathlib import Path

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

import config
from build_vectorstore import VectorStoreBuilder
from prompts import INSURANCE_QA_PROMPT, NO_ANSWER


class InsuranceQA:
    def __init__(self):
        # 复用建库模块中的嵌入模型、数据库路径和集合名称。
        # 实例化不会执行建库，只有调用 build_store() 才会入库。
        self.vector_store = VectorStoreBuilder()

        self.model = ChatOpenAI(
            model=config.MODEL_NAME,
            base_url=config.OPENAI_BASE_URL,
            api_key=config.OPENAI_API_KEY,
            timeout=60,
            max_retries=2,
        )

        self.chain = INSURANCE_QA_PROMPT | self.model | StrOutputParser()

    @staticmethod
    def _format_documents(documents: list[Document]) -> str:
        """将文档整理为包含编号和来源的参考资料。"""
        sections = []

        for index, document in enumerate(documents, start=1):
            metadata = document.metadata
            source = metadata.get("source")
            source_name = Path(source).name if source else "未知来源"

            location = [f"来源：{source_name}"]

            if "page" in metadata:
                # 加载器保存的是从 0 开始的页码。
                location.append(f"第 {metadata['page'] + 1} 页")

            if "line" in metadata:
                location.append(f"CSV 第 {metadata['line']} 行")

            sections.append(
                f"[{index}] {'；'.join(location)}\n"
                f"{document.page_content.strip()}"
            )

        return "\n\n".join(sections)

    def _retrieve_context(self, query: str) -> str | None:
        """检索并格式化有效文档；没有正文时返回 None。"""
        documents = [
            document
            for document in self.vector_store.query_store(query)
            if document.page_content.strip()
        ]
        return self._format_documents(documents) if documents else None

    def ask_question(self, question: str) -> str:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("问题必须是非空字符串")

        question = question.strip()
        context = self._retrieve_context(question)
        if context is None:
            return NO_ANSWER

        return self.chain.invoke({"context": context, "question": question})
