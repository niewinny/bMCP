"""
MCP Protocol Handlers

Implements JSON-RPC handlers for all MCP protocol methods.
Used by both SSE (/sse) and stdio/plain HTTP (/http) transports.
"""

import traceback
from typing import Any, Optional

from .logger import RequestTimer, get_logger
from .utils.config import OUTPUT_SIZE_LIMIT

# Get logger for this module
logger = get_logger("bmcp-handlers")


async def handle_initialize(mcp_server, params: dict) -> dict:
    """
    Handle MCP initialize request.

    Args:
        mcp_server: MCPServer instance
        params: Initialize parameters

    Returns:
        dict: Server capabilities and metadata
    """
    client_protocol = params.get("protocolVersion", "unknown")

    # Use the protocol version the client requested (if we support it)
    # Both 2024-11-05 and 2025-06-18 are compatible with our implementation
    supported_versions = ["2024-11-05", "2025-06-18"]
    protocol_version = (
        client_protocol if client_protocol in supported_versions else "2024-11-05"
    )

    logger.info("Initialize: client=%s, using=%s", client_protocol, protocol_version)

    return {
        "protocolVersion": protocol_version,
        "serverInfo": {"name": mcp_server.name, "version": "1.0.0"},
        "capabilities": {
            "tools": {
                "listChanged": False,  # We don't send notifications when tools change
            },
            "resources": {
                "subscribe": False,  # Resource subscription not supported
                "listChanged": False,  # We don't send notifications when resources change
            },
            "prompts": {
                "listChanged": False,  # Dynamic prompt updates not supported
            },
        },
    }


async def handle_tools_list(mcp_server, params: Optional[dict] = None) -> dict:
    """
    Handle tools/list request - return all registered tools.

    Args:
        mcp_server: MCPServer instance
        params: Optional parameters (not used)

    Returns:
        dict: List of tools with schemas
    """
    tools = mcp_server.list_tools()
    logger.debug("tools/list: returning %d tools", len(tools))
    return {"tools": tools}


async def handle_tools_call(mcp_server, params: dict) -> dict:
    """
    Handle tools/call request - execute a tool.

    Args:
        mcp_server: MCPServer instance
        params: Tool call parameters (name, arguments)

    Returns:
        dict: Tool execution result

    Note:
        Per MCP spec, tool execution errors are returned as content with isError=True.
        This is different from JSON-RPC protocol errors which use the error field.
        Tool errors are "expected" errors (the tool ran but failed), while protocol
        errors are "unexpected" (malformed request, unknown method, etc.).
    """
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if not tool_name or not isinstance(tool_name, str) or not tool_name.strip():
        raise ValueError(f"Tool name is required and cannot be empty (received: {type(tool_name).__name__})")

    logger.info("Tool call: %s", tool_name)

    with RequestTimer(logger, f"tool/{tool_name}"):
        try:
            result = await mcp_server.call_tool(tool_name, arguments)

            # Convert result to string and validate size
            result_str = str(result)
            if len(result_str) > OUTPUT_SIZE_LIMIT:
                original_size = len(result_str)
                result_str = (
                    result_str[:OUTPUT_SIZE_LIMIT] +
                    f"\n\n[OUTPUT TRUNCATED]\n"
                    f"Original size: {original_size:,} bytes\n"
                    f"Limit: {OUTPUT_SIZE_LIMIT:,} bytes\n"
                    f"Truncated: {original_size - OUTPUT_SIZE_LIMIT:,} bytes"
                )
                logger.warning("Tool %s output truncated: %d -> %d bytes",
                             tool_name, original_size, OUTPUT_SIZE_LIMIT)

            # Format result according to MCP spec
            return {"content": [{"type": "text", "text": result_str}]}

        except Exception as e:
            # Log full error with traceback
            logger.error("Tool %s failed: %s\n%s", tool_name, e, traceback.format_exc())

            # Per MCP spec: tool errors are returned as content with isError=True
            # This indicates the tool executed but produced an error result
            # (as opposed to a protocol-level error which would use JSON-RPC error field)
            error_msg = f"Tool execution failed: {type(e).__name__}: {str(e)}"
            return {"content": [{"type": "text", "text": error_msg}], "isError": True}


async def handle_resources_list(mcp_server, params: Optional[dict] = None) -> dict:
    """
    Handle resources/list request - return all registered resources.

    Args:
        mcp_server: MCPServer instance
        params: Optional parameters (not used)

    Returns:
        dict: List of resources and resource templates (per MCP spec)
    """
    resources = mcp_server.list_resources()
    logger.debug("resources/list: returning %d resources", len(resources))
    return {
        "resources": resources,
        "resourceTemplates": [],  # Required by MCP spec, even if empty
    }


async def handle_resources_read(mcp_server, params: dict) -> dict:
    """
    Handle resources/read request - read a resource.

    Args:
        mcp_server: MCPServer instance
        params: Resource read parameters (uri)

    Returns:
        dict: Resource content

    Note:
        Resource read errors are raised as exceptions, which the transport layer
        converts to JSON-RPC error responses. This is appropriate because resource
        reads should either succeed or fail cleanly (unlike tools which may have
        partial success states).
    """
    uri = params.get("uri")

    if not uri or not isinstance(uri, str) or not uri.strip():
        raise ValueError(f"Resource URI is required and cannot be empty (received: {type(uri).__name__})")

    logger.info("Resource read: %s", uri)

    with RequestTimer(logger, f"resource/{uri}"):
        try:
            content = await mcp_server.read_resource(uri)

            # Format result according to MCP spec
            return {
                "contents": [{"uri": uri, "mimeType": "text/markdown", "text": content}]
            }

        except Exception as e:
            # Log full error with traceback
            logger.error("Resource %s failed: %s\n%s", uri, e, traceback.format_exc())

            # Re-raise the exception - let the transport layer handle it
            # as a proper JSON-RPC error response
            raise RuntimeError(f"Resource read failed: {type(e).__name__}: {str(e)}") from e


async def handle_prompts_list(mcp_server, params: Optional[dict] = None) -> dict:
    """
    Handle prompts/list request - return all registered prompts.

    Args:
        mcp_server: MCPServer instance
        params: Optional parameters (not used)

    Returns:
        dict: List of prompts with their arguments
    """
    prompts = mcp_server.list_prompts()
    logger.debug("prompts/list: returning %d prompts", len(prompts))
    return {"prompts": prompts}


async def handle_prompts_get(mcp_server, params: dict) -> dict:
    """
    Handle prompts/get request - get a prompt with arguments.

    Args:
        mcp_server: MCPServer instance
        params: Prompt get parameters (name, arguments)

    Returns:
        dict: Prompt result with description and messages
    """
    name = params.get("name")
    arguments = params.get("arguments", {})

    if not name or not isinstance(name, str) or not name.strip():
        raise ValueError(
            f"Prompt name is required and cannot be empty (received: {type(name).__name__})"
        )

    logger.info("Prompt get: %s", name)

    with RequestTimer(logger, f"prompt/{name}"):
        try:
            result = mcp_server.get_prompt(name, arguments)
            # result is {"description": str, "messages": [...]}
            return result

        except Exception as e:
            # Log full error with traceback
            logger.error("Prompt %s failed: %s\n%s", name, e, traceback.format_exc())

            # Re-raise as RuntimeError for proper JSON-RPC error response
            raise RuntimeError(
                f"Prompt get failed: {type(e).__name__}: {str(e)}"
            ) from e


async def handle_notifications_initialized(mcp_server, params: Optional[dict] = None) -> None:
    """
    Handle notifications/initialized notification.

    This is sent by clients after they receive the initialize response.
    It's a notification (no response expected).

    Args:
        mcp_server: MCPServer instance
        params: Optional parameters (not used)

    Returns:
        None (notifications don't return values)
    """
    logger.debug("Client initialization complete")
    return None


async def handle_notifications_cancelled(mcp_server, params: Optional[dict] = None) -> None:
    """
    Handle notifications/cancelled notification.

    Sent by clients when they cancel a pending request.

    Args:
        mcp_server: MCPServer instance
        params: Request ID that was cancelled

    Returns:
        None (notifications don't return values)
    """
    request_id = params.get("requestId") if params else None
    logger.debug("Client cancelled request: %s", request_id)
    return None


# Mapping of MCP methods to handlers
METHOD_HANDLERS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
    "resources/list": handle_resources_list,
    "resources/read": handle_resources_read,
    "prompts/list": handle_prompts_list,
    "prompts/get": handle_prompts_get,
    # Notifications (no response expected)
    "notifications/initialized": handle_notifications_initialized,
    "notifications/cancelled": handle_notifications_cancelled,
}


async def dispatch_request(mcp_server, method: str, params: Optional[dict] = None) -> Any:
    """
    Dispatch an MCP request to the appropriate handler.

    Args:
        mcp_server: MCPServer instance
        method: MCP method name
        params: Method parameters

    Returns:
        Method result

    Raises:
        ValueError: If method not found
    """
    logger.debug("Dispatch: %s", method)

    if method not in METHOD_HANDLERS:
        logger.warning("Unknown method: %s", method)
        raise ValueError(f"Method '{method}' not supported")

    handler = METHOD_HANDLERS[method]

    # Call handler with appropriate arguments
    if params is not None:
        return await handler(mcp_server, params)
    else:
        return await handler(mcp_server)
