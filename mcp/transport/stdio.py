#!/usr/bin/env python3
"""
stdio MCP Server for Blender

A lightweight stdio-to-HTTP bridge that forwards MCP protocol messages
between stdio-only clients (like Claude Desktop) and Blender's HTTP server.

This script uses ONLY Python standard library - no external dependencies.
It implements just enough MCP protocol to act as a transparent bridge.

Architecture:
- Reads JSON-RPC messages from stdin (newline-delimited)
- Forwards to Blender's JSON-RPC endpoint at http://localhost:12097/http
- Writes responses back to stdout (newline-delimited)

Note: The /http endpoint is for plain JSON-RPC POST requests (stdio bridge).
      The /sse endpoint is for SSE connections (direct HTTP clients like LM Studio).

Usage:
    python stdio_server.py [--port PORT] [--host HOST]

For Claude Desktop, add to config:
    {
        "mcpServers": {
            "blender": {
                "command": "python",
                "args": ["C:\\path\\to\\stdio_server.py"]
            }
        }
    }
"""

import argparse
import http.client
import io
import json
import logging
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

if sys.platform == "win32":
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", line_buffering=True
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", line_buffering=True
    )

DEFAULT_BLENDER_HOST = "127.0.0.1"
DEFAULT_BLENDER_PORT = 12097
DEFAULT_BLENDER_PATH = "/http"
DEFAULT_TIMEOUT = 300  # 5 minutes for long operations
MAX_RETRIES = 2  # Retry transient failures

logger = logging.getLogger("bmcp-stdio-bridge")
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.WARNING)


class HTTPConnectionPool:
    """Simple HTTP connection pool for reusing connections.

    Maintains a single persistent connection to the Blender server,
    reconnecting automatically if the connection is lost.
    """

    def __init__(self, host: str, port: int, timeout: float = DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._conn: Optional[http.client.HTTPConnection] = None

    def _get_connection(self) -> http.client.HTTPConnection:
        """Get or create a connection to the server."""
        if self._conn is None:
            self._conn = http.client.HTTPConnection(
                self.host, self.port, timeout=self.timeout
            )
        return self._conn

    def _close_connection(self) -> None:
        """Close the current connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def request(
        self, method: str, path: str, body: bytes, headers: dict
    ) -> tuple[int, str, bytes]:
        """Make an HTTP request, reconnecting if necessary.

        Args:
            method: HTTP method (POST, GET, etc.)
            path: URL path
            body: Request body as bytes
            headers: Request headers

        Returns:
            Tuple of (status_code, reason, response_body)

        Raises:
            Exception if request fails after reconnection attempt
        """
        conn = self._get_connection()
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.reason, response.read()
        except (http.client.HTTPException, ConnectionError, OSError) as e:
            # Connection lost - try to reconnect once
            logger.debug("Connection error, reconnecting: %s", e)
            self._close_connection()
            conn = self._get_connection()
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.reason, response.read()

    def close(self) -> None:
        """Close the connection pool."""
        self._close_connection()


# Global connection pool (initialized in run_stdio_bridge)
_connection_pool: Optional[HTTPConnectionPool] = None


def forward_to_blender(
    message: dict, endpoint: str, retries: int = MAX_RETRIES
) -> dict:
    """
    Forward a JSON-RPC message to Blender's HTTP server.

    Uses connection pooling for efficiency and retries transient failures.

    Args:
        message: JSON-RPC message dictionary
        endpoint: HTTP endpoint URL
        retries: Number of retries for transient failures

    Returns:
        JSON-RPC response dictionary (or None for notifications)
    """
    global _connection_pool

    logger.debug("Forwarding to Blender: %s", message.get("method"))

    # Prepare request data
    data = json.dumps(message).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "bmcp-stdio-bridge/1.0",
    }

    # Parse endpoint to get path
    parsed = urllib.parse.urlparse(endpoint)
    path = parsed.path or DEFAULT_BLENDER_PATH

    last_error = None

    for attempt in range(retries + 1):
        try:
            # Use connection pool if available
            if _connection_pool:
                status, reason, response_data = _connection_pool.request(
                    "POST", path, data, headers
                )

                # Handle HTTP 204 No Content (for notifications)
                if status == 204:
                    logger.debug(
                        "Received 204 No Content for: %s", message.get("method")
                    )
                    return None

                # Handle HTTP errors
                if status >= 400:
                    logger.error("HTTP error from Blender: %s %s", status, reason)
                    if status == 406:
                        logger.error(
                            "This usually means the Blender MCP server is not properly initialized"
                        )
                    return {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "error": {
                            "code": -32603,
                            "message": f"Blender HTTP error: {status} {reason}",
                        },
                    }

                # Parse response
                result = json.loads(response_data.decode("utf-8"))
                logger.debug("Received response for: %s", message.get("method"))
                return result

            else:
                # Fallback to urllib if no connection pool (shouldn't happen)
                req = urllib.request.Request(
                    endpoint, data=data, headers=headers, method="POST"
                )
                with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as response:
                    if response.status == 204:
                        return None
                    response_data = response.read().decode("utf-8")
                    return json.loads(response_data)

        except (http.client.HTTPException, ConnectionError, OSError) as e:
            # Transient connection error - retry with backoff
            last_error = e
            if attempt < retries:
                wait_time = 0.1 * (attempt + 1)  # 0.1s, 0.2s backoff
                logger.debug(
                    "Connection error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    retries + 1,
                    wait_time,
                    e,
                )
                time.sleep(wait_time)
                continue

            # All retries exhausted
            error_msg = str(e)
            if "Connection refused" in error_msg or "Couldn't connect" in str(e):
                logger.error("Cannot connect to Blender - connection refused")
                logger.error(
                    "SOLUTION: Start Blender and click 'Mcp' menu -> 'Start Server'"
                )
            else:
                logger.error("Cannot connect to Blender at %s: %s", endpoint, error_msg)
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Cannot connect to Blender: {error_msg}",
                },
            }

        except urllib.error.HTTPError as e:
            # HTTP error (like 404, 406, 500, etc.) - don't retry
            logger.error("HTTP error from Blender: %s %s", e.code, e.reason)
            if e.code == 406:
                logger.error(
                    "This usually means the Blender MCP server is not properly initialized"
                )
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Blender HTTP error: {e.code} {e.reason}",
                },
            }

        except urllib.error.URLError as e:
            # Connection error via urllib fallback
            last_error = e
            if attempt < retries:
                time.sleep(0.1 * (attempt + 1))
                continue

            error_msg = str(e.reason)
            logger.error("Cannot connect to Blender at %s: %s", endpoint, error_msg)
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Cannot connect to Blender: {error_msg}",
                },
            }

        except json.JSONDecodeError as e:
            # Don't retry JSON errors
            logger.error("Invalid JSON response from Blender: %s", e)
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {"code": -32700, "message": f"Invalid JSON response: {e}"},
            }

        except Exception as e:
            # Don't retry unexpected errors
            logger.error("Unexpected error: %s", e)
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {"code": -32603, "message": f"Internal error: {e}"},
            }

    # Should not reach here, but just in case
    return {
        "jsonrpc": "2.0",
        "id": message.get("id"),
        "error": {
            "code": -32603,
            "message": f"Request failed after {retries + 1} attempts: {last_error}",
        },
    }


def run_stdio_bridge(endpoint: str):
    """
    Run the stdio bridge that forwards messages between stdin/stdout and HTTP.

    Uses connection pooling for efficient reuse of HTTP connections.

    Args:
        endpoint: Blender HTTP endpoint URL
    """
    global _connection_pool

    logger.debug("Starting stdio bridge to %s", endpoint)

    # Initialize connection pool
    parsed = urllib.parse.urlparse(endpoint)
    host = parsed.hostname or DEFAULT_BLENDER_HOST
    port = parsed.port or DEFAULT_BLENDER_PORT
    _connection_pool = HTTPConnectionPool(host, port, timeout=DEFAULT_TIMEOUT)
    logger.debug("Initialized connection pool to %s:%d", host, port)

    logger.debug("Waiting for messages on stdin...")

    try:
        # Read messages from stdin line by line
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                # Parse incoming JSON-RPC message
                message = json.loads(line)
                logger.debug("Received message: %s", message.get("method", "unknown"))

                # Forward to Blender HTTP server
                response = forward_to_blender(message, endpoint)

                # Write response to stdout (with error handling for closed pipe)
                # Skip if response is None (notification with no response needed)
                if response is not None:
                    try:
                        response_json = json.dumps(response)
                        print(response_json, flush=True)
                        logger.debug("Sent response: %d bytes", len(response_json))
                    except (OSError, IOError) as e:
                        # Pipe closed (client disconnected) - this is expected during shutdown
                        logger.debug("Output pipe closed: %s", e)
                        break
                else:
                    logger.debug("No response needed (notification)")

            except json.JSONDecodeError as e:
                logger.error("Invalid JSON from client: %s", e)
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"},
                }
                print(json.dumps(error_response), flush=True)

    except KeyboardInterrupt:
        logger.debug("Received interrupt signal, shutting down")
    except Exception as e:
        logger.error("Fatal error in stdio bridge: %s", e)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    finally:
        # Clean up connection pool
        if _connection_pool:
            _connection_pool.close()
            logger.debug("Closed connection pool")


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="bMCP Blender stdio Bridge",
        epilog="This script forwards MCP messages between stdio and Blender's HTTP server.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_BLENDER_HOST,
        help=f"Blender HTTP server host (default: {DEFAULT_BLENDER_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_BLENDER_PORT,
        help=f"Blender HTTP server port (default: {DEFAULT_BLENDER_PORT})",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging to stderr"
    )
    return parser.parse_args()


def main():
    """Main entry point for the stdio bridge."""
    args = parse_args()

    # Configure logging level based on --debug flag
    if args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("=" * 60)
        logger.debug("bMCP Blender stdio Bridge")
        logger.debug("=" * 60)
    else:
        logger.setLevel(logging.WARNING)

    # Build Blender HTTP endpoint (use /http for plain JSON-RPC, not SSE)
    endpoint = f"http://{args.host}:{args.port}{DEFAULT_BLENDER_PATH}"

    logger.debug("Blender endpoint: %s", endpoint)
    logger.debug("Ready to forward messages")
    logger.debug("=" * 60)

    # Run the stdio bridge (blocking)
    run_stdio_bridge(endpoint)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
        sys.exit(0)
    except Exception as e:
        logger.error("FATAL: %s", e)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
