"""
MCP Server Core - Custom Implementation

Provides @tool and @resource decorators using base MCP SDK.
Implements decorator-based registration with automatic schema generation.
"""

import inspect
import sys
import types
from typing import Any, Callable, Union, get_args, get_origin

from .logger import get_logger
from .utils.validators import get_cached_type_hints

# Get logger for this module
logger = get_logger("bmcp-core")


class MCPServer:
    """
    Custom MCP server implementation with decorator support.

    Uses cached registries for fast lookups, synced from decorator registries.
    External addons can trigger re-sync after registering new tools/resources.
    """

    def __init__(self, name: str):
        self.name = name
        self._tool_cache = {}  # Cached for fast lookup
        self._resource_cache = {}  # Cached for fast lookup
        self._prompt_cache = {}  # Cached for fast lookup

    def sync_tools(self):
        """
        Sync tool cache from decorator registry.

        Call this after external addons register new tools to make them available.
        Caches handler signature info to avoid expensive inspection on every call.
        """
        from .tools._internal.registry import iter_tools

        self._tool_cache.clear()

        for reg in iter_tools():
            tool_name = reg.name or reg.handler.__name__
            tool_desc = reg.description or (reg.handler.__doc__ or "").strip()
            schema = self._generate_schema(reg.handler)

            # Cache whether handler expects ctx as first parameter
            # This avoids expensive inspect.signature() on every tool call
            sig = inspect.signature(reg.handler)
            params = list(sig.parameters.keys())
            first_param = next((p for p in params if p not in ("self", "cls")), None)
            needs_ctx = first_param == "ctx"

            self._tool_cache[tool_name] = {
                "handler": reg.handler,
                "name": tool_name,
                "description": tool_desc,
                "inputSchema": schema,
                "needs_ctx": needs_ctx,  # Cached signature info
            }

    def sync_resources(self):
        """
        Sync resource cache from decorator registry.

        Call this after external addons register new resources to make them available.
        """
        from .resources._internal.registry import iter_resources

        self._resource_cache.clear()

        for reg in iter_resources():
            resource_name = reg.name or getattr(reg.handler, "__name__", reg.uri.split("/")[-1])
            resource_name = resource_name.replace("_", " ").title()
            resource_desc = reg.description or (reg.handler.__doc__ or "").strip()

            self._resource_cache[reg.uri] = {
                "handler": reg.handler,
                "uri": reg.uri,
                "name": resource_name,
                "description": resource_desc,
                "mimeType": "text/markdown",
            }
            logger.debug("  Synced resource: %s -> %s", reg.uri, resource_name)

    def sync_prompts(self):
        """
        Sync prompt cache from decorator registry.

        Call this after external addons register new prompts to make them available.
        """
        from .prompts._internal.registry import iter_prompts

        self._prompt_cache.clear()

        for reg in iter_prompts():
            # Convert PromptArgument objects to dicts for MCP format
            arguments = [
                {
                    "name": arg.name,
                    "description": arg.description,
                    "required": arg.required,
                }
                for arg in reg.arguments
            ]

            self._prompt_cache[reg.name] = {
                "handler": reg.handler,
                "name": reg.name,
                "title": reg.title or "",
                "description": reg.description or "",
                "arguments": arguments,
            }
            logger.debug("  Synced prompt: %s", reg.name)

    def clear(self):
        """Clear all cached tools, resources, and prompts (called on server stop)."""
        self._tool_cache.clear()
        self._resource_cache.clear()
        self._prompt_cache.clear()

    def _generate_schema(self, func: Callable[..., Any]) -> dict:
        """
        Generate JSON Schema from function signature and type hints.

        Args:
            func: Function to analyze

        Returns:
            dict: JSON Schema for function parameters
        """
        sig = inspect.signature(func)

        # Use cached type hints to avoid expensive re-parsing
        # (validators.py already caches during decoration, we reuse that cache)
        hints = get_cached_type_hints(func)
        if not hints:
            func_name = getattr(func, "__name__", str(func))
            logger.debug(
                "No type hints available for %s. Schema will use default types.",
                func_name
            )

        properties = {}
        required = []

        # Process each parameter
        for param_name, param in sig.parameters.items():
            # Skip self/cls/ctx - these are injected, not from MCP client
            if param_name in ("self", "cls", "ctx"):
                continue

            # Get type hint
            param_type = hints.get(param_name, Any)

            # Convert Python type to JSON Schema
            properties[param_name] = self._type_to_schema(param_type)

            # Extract description from docstring if available
            if func.__doc__:
                # Simple extraction - look for "param_name: description" pattern
                for line in func.__doc__.split("\n"):
                    if param_name in line and ":" in line:
                        desc = line.split(":", 1)[1].strip()
                        if desc:
                            properties[param_name]["description"] = desc
                        break

            # Check if parameter is required (no default value)
            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        schema = {"type": "object", "properties": properties}

        if required:
            schema["required"] = required

        return schema

    def _type_to_schema(self, python_type: Any) -> dict:
        """
        Convert Python type hint to JSON Schema.

        Args:
            python_type: Python type annotation

        Returns:
            dict: JSON Schema type definition
        """
        # Handle None/NoneType
        if python_type is type(None):
            return {"type": "null"}

        # Handle basic types
        if python_type is str or python_type == "str":
            return {"type": "string"}
        elif python_type is int or python_type == "int":
            return {"type": "integer"}
        elif python_type is float or python_type == "float":
            return {"type": "number"}
        elif python_type is bool or python_type == "bool":
            return {"type": "boolean"}

        # Handle generic types
        origin = get_origin(python_type)
        args = get_args(python_type)

        # Handle Optional (Union with None)
        if origin is type(None) or (
            hasattr(python_type, "__origin__")
            and str(python_type).startswith("typing.Optional")
        ):
            # Optional[X] is Union[X, None]
            if args:
                # Return schema for the non-None type
                return self._type_to_schema(args[0])
            return {"type": "string"}

        # Handle Union types (both typing.Union and Python 3.10+ types.UnionType)
        is_union = origin is Union

        # Python 3.10+ union syntax (str | None)
        if sys.version_info >= (3, 10) and not is_union:
            if isinstance(python_type, types.UnionType):
                is_union = True
                # For types.UnionType, we need to get args differently
                args = get_args(python_type)

        if is_union:
            # For Union types, handle properly with anyOf schema
            non_none_types = [t for t in args if t is not type(None)]
            has_none = type(None) in args

            if len(non_none_types) == 0:
                return {"type": "null"}
            elif len(non_none_types) == 1 and not has_none:
                # Single type without None - just return that type's schema
                return self._type_to_schema(non_none_types[0])
            elif len(non_none_types) == 1 and has_none:
                # Optional[X] case - include null type in anyOf for MCP client compatibility
                # This properly represents Optional[str] as anyOf: [{type: string}, {type: null}]
                return {
                    "anyOf": [
                        self._type_to_schema(non_none_types[0]),
                        {"type": "null"}
                    ]
                }
            else:
                # Multiple non-None types: use anyOf schema
                # This properly represents Union[str, int] as anyOf: [{type: string}, {type: integer}]
                schemas = [self._type_to_schema(t) for t in non_none_types]
                if has_none:
                    schemas.append({"type": "null"})
                return {"anyOf": schemas}

        # Handle list
        if origin is list:
            if args:
                return {"type": "array", "items": self._type_to_schema(args[0])}
            return {"type": "array"}

        # Handle dict
        elif origin is dict:
            if args and len(args) >= 2:
                # Dict[str, X] - additionalProperties pattern
                return {
                    "type": "object",
                    "additionalProperties": self._type_to_schema(args[1])
                }
            return {"type": "object"}

        # Handle tuple
        elif origin is tuple:
            if args:
                # Fixed-length tuple with known types
                return {
                    "type": "array",
                    "items": [self._type_to_schema(t) for t in args],
                    "minItems": len(args),
                    "maxItems": len(args)
                }
            return {"type": "array"}

        # Default to string for unknown types
        return {"type": "string"}

    def list_tools(self) -> list[dict]:
        """
        List all cached tools (fast lookup from synced cache).

        Returns:
            list: Tool definitions in MCP format
        """
        tools = []
        for tool_data in self._tool_cache.values():
            tools.append(
                {
                    "name": tool_data["name"],
                    "description": tool_data["description"],
                    "inputSchema": tool_data["inputSchema"],
                }
            )
        return tools

    def list_resources(self) -> list[dict]:
        """
        List all cached resources (fast lookup from synced cache).

        Returns:
            list: Resource definitions in MCP format
        """
        resources = []
        for resource_data in self._resource_cache.values():
            resources.append(
                {
                    "uri": resource_data["uri"],
                    "name": resource_data["name"],
                    "description": resource_data["description"],
                    "mimeType": resource_data["mimeType"],
                }
            )
        return resources

    def list_prompts(self) -> list[dict]:
        """
        List all cached prompts (fast lookup from synced cache).

        Returns:
            list: Prompt definitions in MCP format
        """
        prompts = []
        for prompt_data in self._prompt_cache.values():
            prompt_entry = {
                "name": prompt_data["name"],
                "description": prompt_data["description"],
                "arguments": prompt_data["arguments"],
            }
            # Include title if present (optional per MCP spec)
            if prompt_data.get("title"):
                prompt_entry["title"] = prompt_data["title"]
            prompts.append(prompt_entry)
        return prompts

    def get_prompt(self, name: str, arguments: dict) -> dict:
        """
        Execute a prompt handler and return messages.

        Args:
            name: Prompt name
            arguments: Prompt arguments

        Returns:
            dict: Prompt result with description and messages
        """
        if name not in self._prompt_cache:
            raise ValueError(f"Prompt '{name}' not found")

        prompt_data = self._prompt_cache[name]
        handler = prompt_data["handler"]

        # Call handler with arguments
        messages = handler(**arguments)

        return {"description": prompt_data["description"], "messages": messages}

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """
        Execute a tool with automatic ctx injection (fast cache lookup).

        Uses cached signature info to avoid expensive inspection on every call.

        Args:
            tool_name: Name of tool to execute
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        if tool_name not in self._tool_cache:
            raise ValueError(f"Tool '{tool_name}' not found")

        tool_data = self._tool_cache[tool_name]
        handler = tool_data["handler"]

        # Use cached needs_ctx flag instead of inspecting signature every call
        if tool_data.get("needs_ctx", False):
            # Import here to avoid circular dependency
            from .tools._internal.context import get_context

            ctx = get_context()
            return await handler(ctx, **arguments)
        else:
            return await handler(**arguments)

    async def read_resource(self, uri: str) -> str:
        """
        Read a resource via the get_resources operator (fast cache lookup).

        Resources are executed on Blender's main thread via the operator.

        Args:
            uri: Resource URI to read

        Returns:
            str: Resource content
        """
        if uri not in self._resource_cache:
            raise ValueError(f"Resource '{uri}' not found")

        # Execute resource via operator on main thread
        from .resources._internal.executor import execute_resource

        return await execute_resource(uri)
