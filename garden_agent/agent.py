import os
from google.adk.agents import Agent
from google.adk.tools.mcp_tool import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

from garden_agent.tools import get_weather, get_plant_care, read_sensors

CONNECTION_STRING = os.environ["MDB_MCP_CONNECTION_STRING"]

root_agent = Agent(
    model="gemini-2.5-flash",
    name="garden_agent",
    instruction=(
        "You are a personal garden management assistant. You have four capabilities:\n"
        "1. MongoDB tools — read/write plant records, sensor logs, and watering tasks "
        "in the 'garden' database; use vector search on 'care_knowledge' for advice.\n"
        "2. get_weather(location) — real-time temperature, humidity, and rainfall.\n"
        "3. get_plant_care(plant_name) — look up watering frequency, sunlight, and "
        "care level from the Perenual plant database.\n"
        "4. read_sensors(plant_id) — soil moisture %, soil temperature °C, and light "
        "level % from the plant's sensor. Always call this instead of guessing values.\n\n"
        "Workflow for a garden status check:\n"
        "  • Call read_sensors() for each plant mentioned.\n"
        "  • Call get_weather() for the garden's location.\n"
        "  • Cross-reference with get_plant_care() to assess if conditions are healthy.\n"
        "  • Store every sensor reading in MongoDB (collection: sensor_readings).\n"
        "  • Provide a concise summary and any care actions needed.\n\n"
        "Rules: never invent sensor or weather data; always persist new readings; "
        "when recommending watering or fertilising, log it as a task in MongoDB."
    ),
    tools=[
        get_weather,
        get_plant_care,
        read_sensors,
        MCPToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="npx",
                    args=["-y", "mongodb-mcp-server"],
                    env={
                        **os.environ,
                        "MDB_MCP_CONNECTION_STRING": CONNECTION_STRING,
                        "MDB_MCP_DISABLED_TOOLS": "drop-database,drop-collection",
                    },
                ),
                timeout=60,
            ),
        ),
    ],
)
