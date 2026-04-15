from redis_agent_kit.mcp import create_server

server = create_server(
    redis_url="redis://localhost:6379",
    name="rak-minimal-demo",
)
