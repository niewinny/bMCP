#!/usr/bin/env python3
"""
stdio MCP Server Bridge

A lightweight stdio-to-HTTP bridge that forwards MCP protocol messages
between stdio-only clients (like Claude Desktop) and an HTTP server.

This script uses ONLY Python standard library - no external dependencies.
It implements just enough MCP protocol to act as a transparent bridge.

Architecture:
- Reads JSON-RPC messages from stdin (newline-delimited)
- Forwards to JSON-RPC endpoint at http://localhost:12097/http
- Writes responses back to stdout (newline-delimited)

Usage:
    python -m bmcp.transport.stdio [--port PORT] [--host HOST]
    bmcp-stdio [--port PORT] [--host HOST]
"""

import argparse
import http.client
import io
import json
import logging
import sys
import threading
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

    Maintains a single persistent connection to the server,
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
_connection_pool_lock = threading.Lock()


def forward_to_blender(
    message: dict, endpoint: str, retries: int = MAX_RETRIES
) -> Optional[dict]:
    """
    Forward a JSON-RPC message to the HTTP server.

    Uses connection pooling for efficiency and retries transient failures.

    Args:
        message: JSON-RPC message dictionary
        endpoint: HTTP endpoint URL
        retries: Number of retries for transient failures

    Returns:
        JSON-RPC response dictionary (or None for notifications)
    """
    global _connection_pool

    logger.debug("Forwarding to server: %s", message.get("method"))

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
            # Use connection pool if available (thread-safe access)
            with _connection_pool_lock:
                pool = _connection_pool
            if pool:
                status, reason, response_data = pool.request(
                    "POST", path, data, headers
                )

                if status == 204:
                    logger.debug(
                        "Received 204 No Content for: %s", message.get("method")
                    )
                    return None

                if status >= 400:
                    logger.error("HTTP error from server: %s %s", status, reason)
                    if status == 406:
                        logger.error(
                            "This usually means the MCP server is not properly initialized"
                        )
                    return {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "error": {
                            "code": -32603,
                            "message": f"HTTP error: {status} {reason}",
                        },
                    }

                result = json.loads(response_data.decode("utf-8"))
                logger.debug("Received response for: %s", message.get("method"))
                return result

            else:
                req = urllib.request.Request(
                    endpoint, data=data, headers=headers, method="POST"
                )
                with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as response:
                    if response.status == 204:
                        return None
                    response_data = response.read().decode("utf-8")
                    return json.loads(response_data)

        except (http.client.HTTPException, ConnectionError, OSError) as e:
            last_error = e
            if attempt < retries:
                wait_time = 0.1 * (attempt + 1)
                logger.debug(
                    "Connection error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    retries + 1,
                    wait_time,
                    e,
                )
                time.sleep(wait_time)
                continue

            error_msg = str(e)
            if "Connection refused" in error_msg or "Couldn't connect" in str(e):
                logger.error("Cannot connect to server - connection refused")
                logger.error(
                    "SOLUTION: Start the MCP server first"
                )
            else:
                logger.error("Cannot connect to server at %s: %s", endpoint, error_msg)
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Cannot connect to server: {error_msg}",
                },
            }

        except urllib.error.HTTPError as e:
            logger.error("HTTP error from server: %s %s", e.code, e.reason)
            if e.code == 406:
                logger.error(
                    "This usually means the MCP server is not properly initialized"
                )
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"HTTP error: {e.code} {e.reason}",
                },
            }

        except urllib.error.URLError as e:
            last_error = e
            if attempt < retries:
                time.sleep(0.1 * (attempt + 1))
                continue

            error_msg = str(e.reason)
            logger.error("Cannot connect to server at %s: %s", endpoint, error_msg)
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Cannot connect to server: {error_msg}",
                },
            }

        except json.JSONDecodeError as e:
            logger.error("Invalid JSON response from server: %s", e)
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {"code": -32700, "message": f"Invalid JSON response: {e}"},
            }

        except Exception as e:
            logger.error("Unexpected error: %s", e)
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {"code": -32603, "message": f"Internal error: {e}"},
            }

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

    Args:
        endpoint: HTTP endpoint URL
    """
    global _connection_pool

    logger.debug("Starting stdio bridge to %s", endpoint)

    parsed = urllib.parse.urlparse(endpoint)
    host = parsed.hostname or DEFAULT_BLENDER_HOST
    port = parsed.port or DEFAULT_BLENDER_PORT
    with _connection_pool_lock:
        _connection_pool = HTTPConnectionPool(host, port, timeout=DEFAULT_TIMEOUT)
    logger.debug("Initialized connection pool to %s:%d", host, port)

    logger.debug("Waiting for messages on stdin...")

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                message = json.loads(line)
                logger.debug("Received message: %s", message.get("method", "unknown"))

                response = forward_to_blender(message, endpoint)

                if response is not None:
                    try:
                        response_json = json.dumps(response)
                        print(response_json, flush=True)
                        logger.debug("Sent response: %d bytes", len(response_json))
                    except (OSError, IOError) as e:
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
        with _connection_pool_lock:
            if _connection_pool:
                _connection_pool.close()
                logger.debug("Closed connection pool")


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="bMCP stdio Bridge",
        epilog="This script forwards MCP messages between stdio and an HTTP server.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_BLENDER_HOST,
        help=f"HTTP server host (default: {DEFAULT_BLENDER_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_BLENDER_PORT,
        help=f"HTTP server port (default: {DEFAULT_BLENDER_PORT})",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging to stderr"
    )
    return parser.parse_args()


def main():
    """Main entry point for the stdio bridge."""
    args = parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug("=" * 60)
        logger.debug("bMCP stdio Bridge")
        logger.debug("=" * 60)
    else:
        logger.setLevel(logging.WARNING)

    endpoint = f"http://{args.host}:{args.port}{DEFAULT_BLENDER_PATH}"

    logger.debug("Server endpoint: %s", endpoint)
    logger.debug("Ready to forward messages")
    logger.debug("=" * 60)

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
