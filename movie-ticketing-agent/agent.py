from datetime import datetime

from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from .prompts import instruction_prompt
from .mcp_toolset import movie_ticketing_mcp_toolset


root_agent = LlmAgent(
    name="movie_ticketing_agent",
    # model=LiteLlm(model="openai/gpt-4.1"),
    model=LiteLlm(model="anthropic/claude-sonnet-4-5-20250929"),
    description="This agent is a movie ticketing agent that can help users book tickets for movies.",
    tools=[movie_ticketing_mcp_toolset],
    instruction=instruction_prompt.format(
        system_time=datetime.now().isoformat(),
    ),
)
