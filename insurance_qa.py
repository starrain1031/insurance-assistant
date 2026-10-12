from collections.abc import AsyncIterator
from contextlib import aclosing

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from app import InsuranceQA as BaseInsuranceQA
from prompts import AGENT_SYSTEM_PROMPT, NO_ANSWER


class InsuranceQA(BaseInsuranceQA):
    """支持直接 RAG 问答和带会话记忆的智能体问答。"""

    def __init__(self):
        # 复用 app.py 中的：
        # vector_store、model、chain、ask_question、_format_documents。
        super().__init__()

        # 同一个实例、同一个 thread_id 才能延续此处的会话记忆。
        self.checkpointer = InMemorySaver()

        @tool
        def retrieve_insurance_knowledge(query: str) -> str:
            """检索保险产品、条款、投保、退保和理赔等知识。

            query 应是包含必要上下文的完整问题或明确关键词。
            """
            if not query.strip():
                return "检索问题不能为空，请补充明确的问题。"

            return self._retrieve_context(query.strip()) or NO_ANSWER

        self.agent_executor = create_agent(
            model=self.model,
            tools=[retrieve_insurance_knowledge],
            checkpointer=self.checkpointer,
            system_prompt=AGENT_SYSTEM_PROMPT,
        )

    @staticmethod
    def _prepare_agent_input(
        message: str, thread_id: str
    ) -> tuple[dict, RunnableConfig]:
        """统一校验输入并构造同步、流式调用共用的参数。"""
        if not isinstance(message, str) or not message.strip():
            raise ValueError("消息必须是非空字符串")
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise ValueError("thread_id 必须是非空字符串")

        inputs = {"messages": [{"role": "user", "content": message.strip()}]}
        config: RunnableConfig = {"configurable": {"thread_id": thread_id.strip()}}
        return inputs, config

    def chat_with_agent(self, message: str, thread_id: str) -> str:
        """在指定会话中进行带记忆的智能体问答。"""
        inputs, config = self._prepare_agent_input(message, thread_id)
        result = self.agent_executor.invoke(inputs, config=config)

        messages = result.get("messages", [])
        if not messages:
            raise RuntimeError("智能体没有返回消息")

        last_message = messages[-1]

        if not isinstance(last_message, AIMessage):
            raise RuntimeError("智能体未返回最终回答")

        if last_message.tool_calls:
            raise RuntimeError("智能体仍有未完成的工具调用")

        answer = str(last_message.text).strip()
        if not answer:
            raise RuntimeError("智能体返回了空回答")

        return answer

    async def stream_chat_with_agent(
        self, message: str, thread_id: str
    ) -> AsyncIterator[str]:
        """逐步返回模型文本（包括工具调用前的说明），保留会话记忆。"""
        inputs, config = self._prepare_agent_input(message, thread_id)
        stream = self.agent_executor.astream(
            inputs,
            config=config,
            stream_mode="messages",
            version="v1",
        )

        # 外部取消或提前退出时，关闭内部异步生成器。
        async with aclosing(stream):
            async for chunk, metadata in stream:
                # 只处理模型节点，避免把工具结果直接输出给用户。
                if metadata.get("langgraph_node") != "model":
                    continue

                # AIMessageChunk 也是 AIMessage 的子类。
                if not isinstance(chunk, AIMessage):
                    continue

                # .text 提取文本，不输出工具参数或推理内容块。
                text = str(chunk.text)

                # 不要 strip()，否则会丢失片段间的空格和换行。
                if text:
                    yield text
