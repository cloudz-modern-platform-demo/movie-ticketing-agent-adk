"""Main module."""

import asyncio
import logging
import sys

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)
from dotenv import load_dotenv

from movie_ticketing_agent_adk.executor.agent_executor import (
    MovieTicketingAgentExecutor,
)
from movie_ticketing_agent_adk.movie_ticketing_agent.agent import (
    root_agent as movie_ticketing_agent,
)
from movie_ticketing_agent_adk.movie_ticketing_agent.mcp_toolset import (
    movie_ticketing_mcp_toolset,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]


async def setup_server(host: str, port: int):
    """Setup the server configuration."""
    try:
        agent_executor = await MovieTicketingAgentExecutor.initialize(
            agent=movie_ticketing_agent,
            # tools=await movie_ticketing_mcp_toolset.get_tools(),
            # stream_mode="messages",
            stream_mode="values",
        )
        capabilities = AgentCapabilities(
            streaming=True if agent_executor.stream_mode == "messages" else False,
            pushNotifications=True,
        )

        skills = []

        for agent_tool in agent_executor.get_agent_tools():
            skills.append(
                AgentSkill(
                    id=agent_tool.name,
                    name=agent_tool.name,
                    description=agent_tool.description,
                    tags=[],
                    examples=[],
                )
            )
        agent_card = AgentCard(
            name="Movie Ticketing Agent",
            description="Helps with movie ticketing management",
            url=f"http://{host}:{port}/",
            version="1.0.0",
            default_input_modes=SUPPORTED_CONTENT_TYPES,
            default_output_modes=SUPPORTED_CONTENT_TYPES,
            capabilities=capabilities,
            skills=skills,
        )

        # --8<-- [start:DefaultRequestHandler]
        # httpx_client = httpx.AsyncClient(timeout=300)
        request_handler = DefaultRequestHandler(
            agent_executor=agent_executor,
            task_store=InMemoryTaskStore(),
            # push_notifier=InMemoryPushNotifier(httpx_client),
        )
        server = A2AStarletteApplication(
            agent_card=agent_card, http_handler=request_handler
        )

        return server

    except Exception as e:
        logger.error(f"An error occurred during server startup: {e}")
        sys.exit(1)


async def main():
    host = "0.0.0.0"
    port = 9300
    server = await setup_server(host=host, port=port)
    app = server.build()

    # Configure and run uvicorn server
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


def run():
    asyncio.run(main())
