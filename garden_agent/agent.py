import os
from google.adk.agents import Agent
from google.adk.tools.mcp_tool import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

CONNECTION_STRING = os.environ["MDB_MCP_CONNECTION_STRING"]

root_agent = Agent(
    model="gemini-2.5-flash",
    name="garden_agent",
    instruction=(
        "You manage a personal garden. Use the MongoDB tools to read and write "
        "plant records and sensor readings in the 'garden' database, and use vector "
        "search over the 'care_knowledge' collection to ground your care advice. "
        "Always store new sensor readings; never invent data."
    ),
    tools=[
        MCPToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="npx",
                    args=[
                        "-y", "mongodb-mcp-server",
                        "--previewFeatures", "search",
                    ],
                    env={
                        **os.environ,
                        "MDB_MCP_CONNECTION_STRING": CONNECTION_STRING,
                        "MDB_MCP_DISABLED_TOOLS": "drop-database,drop-collection",
                    },
                ),
                timeout=60,
            ),
        )
    ],
)
