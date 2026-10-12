import asyncio
import json
import logging
from contextlib import aclosing, asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.cors import CORSMiddleware

from insurance_qa import InsuranceQA


logger = logging.getLogger(__name__)
STREAM_HEARTBEAT_SECONDS = 10.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化一次，后续请求复用，保留进程内的会话记忆。
    app.state.qa_assistant = await run_in_threadpool(InsuranceQA)

    # 同一会话的请求依次执行，避免同时修改同一份聊天历史。
    # 这份映射与当前内存会话一样，保留到进程退出。
    app.state.thread_locks = {}

    try:
        yield
    finally:
        app.state.thread_locks.clear()
        app.state.qa_assistant = None


app = FastAPI(
    title="保险智能问答助手",
    description="具备上下文记忆功能的保险问答系统",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 页面、业务脚本和 vendor 文件由同一服务提供。
app.mount(
    "/frontend",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "frontend")),
    name="frontend",
)


class ChatRequest(BaseModel):
    # 先去除首尾空白，再检查最小长度。
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(min_length=1)
    thread_id: str = Field(
        default_factory=lambda: uuid4().hex,
        min_length=1,
        description="首次可不传；后续追问必须复用返回的会话 ID",
    )


class ChatResponse(BaseModel):
    answer: str
    thread_id: str
    status: str = "success"


async def run_agent_chat(
    http_request: Request,
    payload: ChatRequest,
) -> str:
    """在线程池中执行带记忆的同步问答。"""
    state = http_request.app.state

    lock = state.thread_locks.setdefault(
        payload.thread_id,
        asyncio.Lock(),
    )

    try:
        async with lock:
            return await run_in_threadpool(
                state.qa_assistant.chat_with_agent,
                message=payload.message,
                thread_id=payload.thread_id,
            )
    except Exception as exc:
        logger.exception("智能体问答失败")
        raise HTTPException(
            status_code=500,
            detail="处理消息失败，请查看服务端日志。",
        ) from exc


@app.get("/")
async def root():
    return {
        "message": "保险智能问答助手 API",
        "status": "running",
    }


@app.post("/chat", response_model=ChatResponse)
async def chat_with_memory(
    payload: ChatRequest,
    http_request: Request,
):
    """带记忆的智能体问答。"""
    answer = await run_agent_chat(http_request, payload)

    return ChatResponse(
        answer=answer,
        thread_id=payload.thread_id,
    )


@app.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    http_request: Request,
):
    """将智能体生成的文本增量立即发送给客户端。"""
    state = http_request.app.state

    # 和普通 /chat 使用同一套锁，避免同一会话并发更新历史。
    lock = state.thread_locks.setdefault(
        payload.thread_id,
        asyncio.Lock(),
    )

    def encode_event(data: dict) -> str:
        return (
            "data: "
            + json.dumps(data, ensure_ascii=False)
            + "\n\n"
        )

    async def generate_stream():
        # 有界队列提供背压，避免客户端接收较慢时积累全部回答。
        events = asyncio.Queue(maxsize=1)

        async def produce():
            try:
                # 排队和检索期间由外层生成器持续发送心跳。
                async with lock:
                    stream = state.qa_assistant.stream_chat_with_agent(
                        message=payload.message,
                        thread_id=payload.thread_id,
                    )
                    has_text = False
                    async with aclosing(stream):
                        async for text in stream:
                            if not text:
                                continue
                            has_text = has_text or bool(text.strip())
                            await events.put({
                                "thread_id": payload.thread_id,
                                "content": text,
                            })
                    if not has_text:
                        raise RuntimeError("智能体没有生成文本回答")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("流式问答失败")
                await events.put({
                    "thread_id": payload.thread_id,
                    "error": "回答生成失败，请稍后重试。",
                })
            await events.put(None)

        producer = asyncio.create_task(produce())
        try:
            yield encode_event({
                "thread_id": payload.thread_id,
                "content": "",
            })
            while True:
                try:
                    event = await asyncio.wait_for(
                        events.get(), timeout=STREAM_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    # SSE 注释：保持连接，但不作为回答正文。
                    yield ": ping\n\n"
                    continue
                if event is None:
                    yield "data: [DONE]\n\n"
                    return
                yield encode_event(event)
        finally:
            # 断线、取消或关闭生成器时，同步清理模型任务并释放会话锁。
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/simple_ask", response_model=ChatResponse)
async def simple_ask(
    payload: ChatRequest,
    http_request: Request,
):
    """直接 RAG 问答，不读写聊天历史。"""
    try:
        answer = await run_in_threadpool(
            http_request.app.state.qa_assistant.ask_question,
            payload.message,
        )
    except Exception as exc:
        logger.exception("直接 RAG 问答失败")
        raise HTTPException(
            status_code=500,
            detail="处理问题失败，请查看服务端日志。",
        ) from exc

    # 此接口仅回传 thread_id，不使用它保存会话记忆。
    return ChatResponse(
        answer=answer,
        thread_id=payload.thread_id,
    )


@app.get("/health")
async def health_check():
    """存活检查，不验证模型 API 或向量数据库是否可用。"""
    return {
        "status": "alive",
        "service": "保险智能问答助手",
    }


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # 当前使用 InMemorySaver，运行单个 worker。
    uvicorn.run(app, host="0.0.0.0", port=8000)
