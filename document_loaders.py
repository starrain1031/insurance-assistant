import csv
import logging
from pathlib import Path

from langchain_core.documents import Document
from pypdf import PdfReader


logger = logging.getLogger(__name__)


def load_txt(path: Path) -> list[Document]:
    """读取 UTF-8 文本，兼容带 BOM 的文件。"""
    return [
        Document(
            page_content=path.read_text(encoding="utf-8-sig"),
            metadata={"source": str(path)},
        )
    ]


def load_pdf(path: Path) -> list[Document]:
    """按页提取 PDF 文本；扫描件需要提前进行 OCR。"""
    documents = []

    with path.open("rb") as file:
        reader = PdfReader(file)

        for page_index, page in enumerate(reader.pages):
            text = page.extract_text() or ""

            if not text.strip():
                logger.warning(
                    "PDF 第 %d 页没有可提取文本：%s",
                    page_index + 1,
                    path.name,
                )
                continue

            documents.append(
                Document(
                    page_content=text,
                    metadata={
                        "source": str(path),
                        "page": page_index,  # 从 0 开始
                    },
                )
            )

    return documents


def load_csv(path: Path) -> list[Document]:
    """每条 CSV 数据生成一个 Document。"""
    documents = []

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        headers = None

        # 跳过空行，以及当前案例中特有的标题行。
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue

            if (
                row[0].strip() == "保险产品对比信息表"
                and all(not cell.strip() for cell in row[1:])
            ):
                continue

            headers = [cell.strip() for cell in row]
            break

        if not headers:
            raise ValueError(f"CSV 没有表头：{path}")

        if any(not header for header in headers):
            raise ValueError(f"CSV 存在空列名：{path}")

        if len(set(headers)) != len(headers):
            raise ValueError(f"CSV 存在重复列名：{path}")

        for row in reader:
            if not any(cell.strip() for cell in row):
                continue

            if len(row) != len(headers):
                raise ValueError(
                    f"CSV 第 {reader.line_num} 行列数不匹配："
                    f"应为 {len(headers)} 列，实际为 {len(row)} 列；"
                    f"文件：{path}"
                )

            content = "\n".join(
                f"{header}: {value.strip()}"
                for header, value in zip(headers, row)
            )

            documents.append(
                Document(
                    page_content=content,
                    metadata={
                        "source": str(path),
                        "row": len(documents),  # 数据记录编号，从 0 开始
                        # 如果字段包含换行，这是该记录的结束行号。
                        "line": reader.line_num,
                    },
                )
            )

    return documents


# 新增文件类型时，在这里注册对应函数。
_LOADERS = {
    ".txt": load_txt,
    ".pdf": load_pdf,
    ".csv": load_csv,
}

SUPPORTED_EXTENSIONS = frozenset(_LOADERS)


def load_documents(file_path: str | Path) -> list[Document]:
    """统一入口：检查文件、选择加载器、过滤空文档。"""
    path = Path(file_path).resolve()

    if not path.is_file():
        raise FileNotFoundError(f"文件不存在或不是普通文件：{path}")

    loader = _LOADERS.get(path.suffix.lower())
    if loader is None:
        raise ValueError(f"不支持的文件类型：{path.suffix}")

    documents = [
        document
        for document in loader(path)
        if document.page_content.strip()
    ]

    if not documents:
        raise ValueError(
            f"文件没有有效文本：{path}。"
            "如果是扫描 PDF，需要先进行 OCR。"
        )

    return documents