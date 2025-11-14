"""MovieCatalogAgentExecutor."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterable, List, Literal
from uuid import uuid4

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    InternalError,
    InvalidParamsError,
    Part,
    TaskState,
    TextPart,
)
from a2a.utils import (
    new_agent_text_message,
    new_task,
)
from a2a.utils.errors import ServerError
from google.adk.tools.base_tool import BaseTool
from google.adk.agents.llm_agent import LlmAgent

# from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage, ToolMessageChunk
# from langchain_core.runnables.config import RunnableConfig
# from langchain_mcp_adapters.client import AIMessage
# from langgraph.graph.state import CompiledStateGraph

# from movie_catalog_agent_langgraph.agents.context import Context

logger = logging.getLogger(__name__)


class MovieTicketingAgentExecutor(AgentExecutor):
    """MovieTicketingAgentExecutor Example."""

    def __init__(
        self,
        agent: LlmAgent,
        # tools: List[BaseTool],
        stream_mode: Literal["values", "messages"] = "messages",
    ):
        """Initialize the MovieTicketingAgentExecutor."""
        self.agent: LlmAgent = agent
        self.tools: List[BaseTool] = None
        self.stream_mode: str = stream_mode

    @classmethod
    async def initialize(
        cls,
        *,
        agent: LlmAgent,
        # tools: List[BaseTool],
        stream_mode: Literal["values", "messages"] = "values",
    ) -> MovieTicketingAgentExecutor:
        """Initialize the MovieTicketingAgentExecutor."""
        instance = cls(agent, stream_mode)
        instance.tools = await instance.agent.canonical_tools()

        logger.info(
            f"MovieTicketingAgentExecutor initialized {instance.agent.name} with {len(instance.tools)} tools"
        )

        return instance

    def get_agent_tools(self) -> list[BaseTool]:
        """Get the agent tools."""
        return self.tools

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Execute the MovieTicketingAgentExecutor."""
        if not self.agent:
            raise ServerError(
                error=InvalidParamsError(message="Agent is not initialized")
            )

        logger.debug(f"context: {context}")
        logger.debug(f"context fields: {vars(context)}")
        logger.debug(f"event_queue: {event_queue}")

        error = self._validate_request(context)
        if error:
            raise ServerError(error=InvalidParamsError())

        # TODO: get user_id from context
        user_id = "skax-edu01"
        query = context.get_user_input()
        task = context.current_task
        logger.debug(f"task: {task}")

        if not task:
            task = new_task(context.message)  # type: ignore
            logger.debug(f"new task created: {task}")
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        await updater.submit()
        await updater.start_work()

        try:
            async for item in self.astream(
                query=query,
                context_id=task.context_id,
                user_id=user_id,
                stream_mode=self.stream_mode,
            ):
                is_task_complete = item["is_task_complete"]
                require_user_input = item["require_user_input"]

                if not is_task_complete and not require_user_input:
                    logger.debug(f"Updating task status to working: {item['content']}")
                    await updater.update_status(
                        TaskState.working,
                        new_agent_text_message(
                            item["content"],
                            task.context_id,
                            task.id,
                        ),
                    )
                elif require_user_input:
                    logger.debug(
                        f"Updating task status to input_required: {item['content']}"
                    )
                    await updater.update_status(
                        TaskState.input_required,
                        new_agent_text_message(
                            item["content"],
                            task.context_id,
                            task.id,
                        ),
                        final=True,
                    )
                    break
                else:
                    logger.debug(f"Adding artifact: {item['content']}")
                    await updater.add_artifact(
                        [Part(root=TextPart(text=item["content"]))],
                        name="conversion_result",
                    )
                    await updater.complete()
                    break

        except Exception as e:
            logger.error(f"An error occurred while streaming the response: {e}")
            if updater:
                try:
                    await updater.update_status(
                        TaskState.failed,
                        message=updater.new_agent_message(
                            parts=[
                                Part(
                                    root=TextPart(
                                        text=f"The task has been failed: {str(e)}"
                                    )
                                )
                            ]
                        ),
                        final=True,
                    )
                except Exception as update_error:
                    logger.error(f"Failed to update task status: {update_error}")
            raise ServerError(error=InternalError()) from e

    def _validate_request(self, context: RequestContext) -> bool:
        """Validate the request."""
        return False

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Cancel the MovieTicketingAgentExecutor."""
        task_id = context.task_id or str(uuid4())
        context_id = context.context_id or str(uuid4())
        task_updater = TaskUpdater(event_queue, task_id, context_id)
        await task_updater.update_status(
            TaskState.canceled,
            message=task_updater.new_agent_message(
                parts=[Part(root=TextPart(text="The task has been canceled."))]
            ),
            final=True,
        )

    async def astream(
        self,
        *,
        query: str,
        context_id: str,
        user_id: str,
        stream_mode: Literal["values", "messages"] = "messages",
    ) -> AsyncIterable[dict[str, Any]]:
        """Stream the agent response."""
        inputs = {"messages": [("user", query)]}
        config = RunnableConfig(
            recursion_limit=10,
        )
        context = Context(
            user_id=user_id,
            thread_id=context_id,
        )

        response = self.agent.astream(
            inputs, config, context=context, stream_mode=stream_mode
        )

        if stream_mode == "values":
            async for chunk_message in response:
                # item is a dict with keys: messages when stream_mode is "values"
                chunk_message = chunk_message["messages"][-1]
                if isinstance(chunk_message, AIMessage):
                    # for first turn with tool calls
                    if chunk_message.tool_calls and len(chunk_message.tool_calls) > 0:
                        tool_names = ", ".join(
                            [
                                tool_call["name"]
                                for tool_call in chunk_message.tool_calls
                            ]
                        )

                        logger.debug(
                            f"Looking up alert information... using tools: {tool_names}"
                        )
                        yield {
                            "is_task_complete": False,
                            "require_user_input": False,
                            "content": f"Looking up alert information... using tools: {tool_names}",
                        }
                    # for first turn without tool calls or result for user query
                    else:
                        logger.debug("Processing user query with data from tools")
                        yield {
                            "is_task_complete": False,
                            "require_user_input": False,
                            "content": chunk_message.content,
                        }
                elif isinstance(chunk_message, ToolMessage):
                    if chunk_message.status == "success":
                        logger.debug("Data retrieved successfully")
                        # TODO: consider adding tool message data to the content
                        yield {
                            "is_task_complete": False,
                            "require_user_input": False,
                            "content": "Data retrieved successfully",
                        }
                    elif chunk_message.status == "error":
                        logger.warning(
                            f"Error retrieving data. Error: {chunk_message.content}"
                        )
                        yield {
                            "is_task_complete": False,
                            "require_user_input": True,
                            "content": f"Error retrieving data. Error: {chunk_message.content}",
                        }
                elif isinstance(chunk_message, HumanMessage):
                    ...
                else:
                    logger.warning(f"Unknown message type: {type(chunk_message)}")
                    yield {
                        "is_task_complete": False,
                        "require_user_input": True,
                        "content": (
                            "We are unable to process your request at the moment. "
                            "Please try again."
                        ),
                    }

            logger.info(f"{self.agent.name} Task completed")
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": "Task completed",
            }
        elif stream_mode == "messages":
            async for chunk_message, _ in response:
                # item is a message object (AIMessageChunk, ToolMessage, HumanMessage)
                if isinstance(chunk_message, AIMessageChunk):
                    if chunk_message.content:
                        if isinstance(chunk_message.content, str):
                            yield {
                                "is_task_complete": False,
                                "require_user_input": False,
                                "content": chunk_message.content,
                            }
                        elif isinstance(chunk_message.content, list):
                            for content in chunk_message.content:
                                if isinstance(content, str):
                                    yield {
                                        "is_task_complete": False,
                                        "require_user_input": False,
                                        "content": content,
                                    }
                                elif isinstance(content, dict):
                                    if content.get("type") == "text":
                                        yield {
                                            "is_task_complete": False,
                                            "require_user_input": False,
                                            "content": content.get("text"),
                                        }
                                else:
                                    raise ValueError(
                                        f"Unknown content type: {type(content)}"
                                    )
                    if chunk_message.tool_call_chunks:
                        # TODO: consider adding tool call chunk to the content
                        for tool_call_chunk in chunk_message.tool_call_chunks:
                            if tool_call_chunk["id"]:
                                ...
                            if tool_call_chunk["name"]:
                                ...
                            if tool_call_chunk["args"]:
                                ...
                elif isinstance(chunk_message, ToolMessage):
                    if chunk_message.status == "success":
                        # TODO: consider adding tool message data to the content
                        yield {
                            "is_task_complete": False,
                            "require_user_input": False,
                            "content": "Data retrieved successfully\n",
                        }
                    elif chunk_message.status == "error":
                        yield {
                            "is_task_complete": False,
                            "require_user_input": True,
                            "content": f"Error retrieving data. Error: {chunk_message.content}",
                        }
                elif isinstance(chunk_message, HumanMessage):
                    ...
                elif isinstance(chunk_message, ToolMessageChunk):
                    ...
                else:
                    logger.warning(f"Unknown message type: {type(chunk_message)}")
                    yield {
                        "is_task_complete": False,
                        "require_user_input": True,
                        "content": (
                            "We are unable to process your request at the moment. "
                            "Please try again."
                        ),
                    }

            logger.info(f"{self.agent.name} Task completed")
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": "Task has been completed successfully",
            }
