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
from google.adk.agents.llm_agent import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.base_tool import BaseTool
from google.genai import types


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

        session_service = InMemorySessionService()

        await session_service.create_session(
            app_name=self.agent.name, user_id=user_id, session_id=context_id
        )

        # Create a runner for agent
        ticketing_runner = Runner(
            agent=self.agent,
            app_name=self.agent.name,
            session_service=session_service,
        )

        user_content = types.Content(role="user", parts=[types.Part(text=query)])

        final_response_content = None
        async for event in ticketing_runner.run_async(
            user_id=user_id, session_id=context_id, new_message=user_content
        ):
            logger.info(f"Event: {event}")

            # print(f"Event: {event.type}, Author: {event.author}") # Uncomment for detailed logging
            if event.is_final_response() and event.content and event.content.parts:
                final_response_content = event.content.parts[0].text

                logger.info(f"{self.agent.name} Task completed")
                yield {
                    "is_task_complete": True,
                    "require_user_input": False,
                    "content": final_response_content,
                }
