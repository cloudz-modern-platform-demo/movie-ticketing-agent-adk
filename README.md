# Install dependency
```
uv sync
```

# Setup LLM API Key
```
cp .env.example .env
```

# Agent Run using the terminal
```
cd src/movie_ticketing_agent_adk

adk run ./movie_ticketing_agent
```

# Agent Run using the web playground
```
adk web --port 9200
```

# Run A2A Remote Agent
```
uv run movie-ticketing-remote-agent
```