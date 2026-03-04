"""
Composio tool integration for AI agent capabilities.

Provides seamless integration with Composio's 150+ tool actions including:
- GitHub (repo management, issues, PRs)
- Slack (messaging, channel management)
- Notion (page creation, database operations)
- Google Workspace (Docs, Sheets, Gmail)
- And many more...

Documentation: https://docs.composio.dev/
"""

import os
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import composio, but make it optional
try:
    from composio import Composio, Action, App, Tag
    from composio.client.collections import ConnectionModel
    COMPOSIO_AVAILABLE = True
except ImportError:
    COMPOSIO_AVAILABLE = False
    logger.warning(
        "Composio not installed. Install with: pip install composio-core composio-openai"
    )


@dataclass
class ToolConnection:
    """Represents a connected tool integration."""
    tool_name: str
    connection_id: str
    status: str
    available_actions: List[str] = field(default_factory=list)
    connected_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "connection_id": self.connection_id,
            "status": self.status,
            "available_actions": self.available_actions,
            "connected_at": self.connected_at.isoformat(),
            "metadata": self.metadata,
        }


class ToolIntegrationManager:
    """
    Manages tool integrations for AI agents via Composio.
    
    Features:
    - Connect/disconnect tools (GitHub, Slack, Notion, etc.)
    - Execute tool actions with proper authentication
    - Per-sandbox tool configuration
    - Automatic OAuth token management
    
    Usage:
        tool_manager = ToolIntegrationManager(api_key="your_composio_api_key")
        
        # Setup tools for a sandbox
        await tool_manager.setup_agent_tools(
            sandbox_id="sandbox_123",
            agent_id="agent_456",
            tools=["github", "slack", "notion"],
        )
        
        # Execute a tool action
        result = await tool_manager.execute_tool_action(
            sandbox_id="sandbox_123",
            action_name="github_create_issue",
            params={
                "repo": "owner/repo",
                "title": "Bug report",
                "body": "Found a bug...",
            },
        )
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the tool integration manager.
        
        Args:
            api_key: Composio API key. If not provided, reads from COMPOSIO_API_KEY env var.
        """
        if not COMPOSIO_AVAILABLE:
            raise ImportError(
                "Composio is not installed. "
                "Install with: pip install composio-core composio-openai"
            )
        
        self.api_key = api_key or os.getenv("COMPOSIO_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Composio API key not provided. "
                "Set COMPOSIO_API_KEY environment variable or pass api_key parameter."
            )
        
        self.client = Composio(api_key=self.api_key)
        self._active_connections: Dict[str, Dict[str, ToolConnection]] = {}
        self._entity_cache: Dict[str, Any] = {}
    
    async def setup_agent_tools(
        self, 
        sandbox_id: str, 
        agent_id: str,
        tools: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Set up tool connections for an agent in a sandbox.
        
        Args:
            sandbox_id: The sandbox where tools will be available.
            agent_id: The agent identifier (used for entity tracking).
            tools: List of tool names (e.g., ["github", "slack", "notion"]).
            
        Returns:
            Dict mapping tool names to connection status and available actions.
            
        Example:
            result = await tool_manager.setup_agent_tools(
                sandbox_id="sandbox_123",
                agent_id="coder_agent",
                tools=["github", "slack"],
            )
            # Returns:
            # {
            #     "github": {
            #         "status": "connected",
            #         "connection_id": "conn_abc123",
            #         "available_actions": ["github_create_issue", "github_create_pr", ...]
            #     },
            #     "slack": {
            #         "status": "error",
            #         "error": "OAuth required"
            #     }
            # }
        """
        connections = {}
        
        for tool_name in tools:
            try:
                # Get available actions for this tool
                actions = self._get_available_actions(tool_name)
                
                # Get or create entity for this agent
                entity = self._get_entity(agent_id)
                
                # Try to get existing connection or create new one
                connection = self._get_or_create_connection(
                    tool_name=tool_name,
                    entity_id=agent_id,
                    entity=entity,
                )
                
                if connection:
                    tool_connection = ToolConnection(
                        tool_name=tool_name,
                        connection_id=connection.id if hasattr(connection, 'id') else str(connection),
                        status="connected",
                        available_actions=[a.name for a in actions] if actions else [],
                        metadata={
                            "entity_id": agent_id,
                            "sandbox_id": sandbox_id,
                        },
                    )
                    
                    # Store connection
                    if sandbox_id not in self._active_connections:
                        self._active_connections[sandbox_id] = {}
                    self._active_connections[sandbox_id][tool_name] = tool_connection
                    
                    connections[tool_name] = tool_connection.to_dict()
                else:
                    connections[tool_name] = {
                        "status": "auth_required",
                        "error": f"OAuth authentication required for {tool_name}",
                        "auth_url": f"https://app.composio.dev/apps/{tool_name}",
                    }
                    
            except Exception as e:
                logger.error(f"Failed to setup tool {tool_name}: {e}")
                connections[tool_name] = {
                    "status": "error",
                    "error": str(e),
                }
        
        return connections
    
    def _get_available_actions(self, tool_name: str) -> List[Any]:
        """Get available actions for a tool."""
        try:
            app = App(tool_name)
            actions = self.client.actions.get_actions(app=app)
            return actions
        except Exception as e:
            logger.warning(f"Could not get actions for {tool_name}: {e}")
            return []
    
    def _get_entity(self, entity_id: str) -> Any:
        """Get or create a Composio entity for an agent."""
        if entity_id not in self._entity_cache:
            self._entity_cache[entity_id] = self.client.get_entity(id=entity_id)
        return self._entity_cache[entity_id]
    
    def _get_or_create_connection(
        self, 
        tool_name: str, 
        entity_id: str,
        entity: Any,
    ) -> Optional[Any]:
        """Get existing connection or create new one."""
        try:
            # Try to get existing connections
            connections = entity.get_connections(app=App(tool_name))
            if connections:
                return connections[0]
            
            # No existing connection - would need OAuth flow
            # For now, return None to indicate auth is required
            return None
            
        except Exception as e:
            logger.debug(f"Connection check for {tool_name} failed: {e}")
            return None
    
    async def execute_tool_action(
        self, 
        sandbox_id: str, 
        action_name: str, 
        params: Dict[str, Any],
        entity_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a tool action in the context of a sandbox.
        
        Args:
            sandbox_id: The sandbox identifier.
            action_name: The Composio action name (e.g., "github_create_issue").
            params: Action parameters as a dictionary.
            entity_id: Optional entity ID (defaults to sandbox_id).
            
        Returns:
            Dict with execution result:
            - success: bool
            - result: action result data
            - error: error message if failed
            
        Example:
            result = await tool_manager.execute_tool_action(
                sandbox_id="sandbox_123",
                action_name="github_create_issue",
                params={
                    "repo": "owner/repo",
                    "title": "New feature",
                    "body": "Implementing a new feature",
                },
            )
            if result["success"]:
                issue_url = result["result"]["data"]["html_url"]
        """
        if sandbox_id not in self._active_connections:
            return {
                "success": False,
                "error": f"No tools configured for sandbox {sandbox_id}",
            }
        
        entity_id = entity_id or sandbox_id
        
        try:
            # Determine which tool this action belongs to
            tool_name = self._infer_tool_from_action(action_name)
            
            # Check if tool is connected
            if tool_name not in self._active_connections[sandbox_id]:
                return {
                    "success": False,
                    "error": f"Tool '{tool_name}' not connected for this sandbox",
                }
            
            # Get entity
            entity = self._get_entity(entity_id)
            
            # Execute the action
            action = Action(action_name)
            result = entity.execute(
                action=action,
                params=params,
            )
            
            logger.info(f"Executed action {action_name} for sandbox {sandbox_id}")
            
            return {
                "success": True,
                "result": result,
                "action": action_name,
                "tool": tool_name,
            }
            
        except Exception as e:
            logger.error(f"Action execution failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "action": action_name,
            }
    
    def _infer_tool_from_action(self, action_name: str) -> str:
        """
        Infer the tool name from an action name.
        
        Composio action names are typically formatted as:
        - "github_create_issue"
        - "slack_send_message"
        - "notion_create_page"
        
        Args:
            action_name: The action name.
            
        Returns:
            The inferred tool name (e.g., "github" from "github_create_issue").
        """
        if "_" in action_name:
            return action_name.split("_")[0]
        return action_name
    
    async def get_available_tools(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all available tools and their capabilities.
        
        Returns:
            Dict mapping tool names to their metadata and available actions.
        """
        tools = {}
        
        try:
            # Get all available apps
            apps = self.client.get_apps()
            
            for app in apps:
                try:
                    actions = self.client.actions.get_actions(app=app)
                    tools[app.name] = {
                        "name": app.name,
                        "description": getattr(app, "description", ""),
                        "logo": getattr(app, "logo", ""),
                        "actions_count": len(actions),
                        "actions": [a.name for a in actions[:20]],  # Limit to first 20
                    }
                except Exception:
                    continue
                    
        except Exception as e:
            logger.error(f"Failed to get available tools: {e}")
        
        return tools
    
    async def teardown_tools(self, sandbox_id: str) -> None:
        """
        Clean up tool connections when a sandbox is destroyed.
        
        Note: This doesn't disconnect the tools from Composio,
        it just removes them from the active connections cache.
        
        Args:
            sandbox_id: The sandbox identifier.
        """
        if sandbox_id in self._active_connections:
            # Log disconnection
            tools_disconnected = list(self._active_connections[sandbox_id].keys())
            logger.info(
                f"Cleaning up tool connections for sandbox {sandbox_id}: "
                f"{tools_disconnected}"
            )
            
            # Remove from active connections
            del self._active_connections[sandbox_id]
        
        # Clean up entity cache if needed
        # (keep this minimal to avoid memory leaks)
        if len(self._entity_cache) > 1000:
            self._entity_cache.clear()
    
    def get_connection_status(self, sandbox_id: str) -> Dict[str, Any]:
        """
        Get the connection status for all tools in a sandbox.
        
        Args:
            sandbox_id: The sandbox identifier.
            
        Returns:
            Dict with connection status for each tool.
        """
        if sandbox_id not in self._active_connections:
            return {"status": "no_connections", "tools": {}}
        
        return {
            "status": "connected",
            "tools": {
                name: conn.to_dict() 
                for name, conn in self._active_connections[sandbox_id].items()
            },
        }


# =============================================================================
# Pre-built Tool Configurations
# =============================================================================

COMMON_TOOL_SETS = {
    "developer": [
        "github",
        "gitlab",
        "linear",
        "slack",
        "notion",
    ],
    "data_analyst": [
        "google_sheets",
        "airtable",
        "slack",
        "notion",
        "gmail",
    ],
    "customer_support": [
        "zendesk",
        "slack",
        "gmail",
        "intercom",
        "notion",
    ],
    "marketing": [
        "twitter",
        "linkedin",
        "slack",
        "notion",
        "google_docs",
    ],
}


def get_recommended_tools_for_role(role: str) -> List[str]:
    """
    Get recommended tool set for a specific role.
    
    Args:
        role: Role name (e.g., "developer", "data_analyst").
        
    Returns:
        List of recommended tool names.
    """
    return COMMON_TOOL_SETS.get(role.lower(), COMMON_TOOL_SETS["developer"])


# =============================================================================
# FastAPI Integration Helper
# =============================================================================

def create_tool_integration_routes(app, tool_manager: ToolIntegrationManager):
    """
    Create FastAPI routes for tool integration management.
    
    Usage:
        from serverless_workers_sdk.tool_integration import (
            ToolIntegrationManager,
            create_tool_integration_routes,
        )
        
        tool_manager = ToolIntegrationManager()
        create_tool_integration_routes(app, tool_manager)
    """
    from fastapi import Depends, HTTPException
    from pydantic import BaseModel
    
    class ToolSetupRequest(BaseModel):
        tools: List[str]
        agent_id: Optional[str] = None
    
    class ToolActionRequest(BaseModel):
        action: str
        params: Dict[str, Any]
        entity_id: Optional[str] = None
    
    @app.post("/sandboxes/{sandbox_id}/tools/configure")
    async def configure_tools(
        sandbox_id: str,
        request: ToolSetupRequest,
    ):
        """Configure tool integrations for a sandbox."""
        agent_id = request.agent_id or sandbox_id
        result = await tool_manager.setup_agent_tools(
            sandbox_id=sandbox_id,
            agent_id=agent_id,
            tools=request.tools,
        )
        return {"sandbox_id": sandbox_id, "tools": result}
    
    @app.post("/sandboxes/{sandbox_id}/tools/execute")
    async def execute_tool(
        sandbox_id: str,
        request: ToolActionRequest,
    ):
        """Execute a tool action in a sandbox."""
        result = await tool_manager.execute_tool_action(
            sandbox_id=sandbox_id,
            action_name=request.action,
            params=request.params,
            entity_id=request.entity_id,
        )
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    
    @app.get("/sandboxes/{sandbox_id}/tools/status")
    async def get_tool_status(sandbox_id: str):
        """Get tool connection status for a sandbox."""
        return tool_manager.get_connection_status(sandbox_id)
    
    @app.get("/tools/available")
    async def list_available_tools():
        """List all available tools and their actions."""
        return await tool_manager.get_available_tools()
