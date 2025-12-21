"""Run Code MCP Operator - MCP-compliant version of execute_code"""

import ast
import io
import json
import sys

import bpy
from bpy.types import Operator

# Safety limit for output size
MAX_OUTPUT_SIZE = 2_000_000  # 2MB maximum output size


class BMCP_OT_run_code(Operator):
    """Execute Python code in Blender - MCP compatible (Internal operator)"""

    bl_idname = "bmcp.run_code"
    bl_label = "Run Code"
    bl_options = {"INTERNAL"}

    code: bpy.props.StringProperty(
        name="Code",
        description="Python code to execute",
        default="",
        options={"SKIP_SAVE"},
    )

    job_id: bpy.props.StringProperty(
        name="Job ID",
        description="Unique identifier for this execution",
        default="",
        options={"SKIP_SAVE"},
    )

    def execute(self, context) -> set[str]:
        """Execute the provided Python code"""
        # Validate context is available
        if context is None or context.window_manager is None:
            self.report({"ERROR"}, "Invalid context: window_manager not available")
            return {"CANCELLED"}

        result_key = f"mcp_result_{self.job_id}" if self.job_id else "mcp_result"

        # Clean up any stale data from previous execution
        context.window_manager.pop(result_key, None)

        old_stdout = sys.stdout
        stdout_redirected = False

        try:
            # Parse code first (before redirecting stdout)
            try:
                tree = ast.parse(self.code, filename="<ai-code>", mode="exec")
            except SyntaxError as e:
                error_msg = f"Syntax error at line {e.lineno}: {e.msg}"
                if e.text:
                    error_msg += f"\n  {e.text.strip()}"
                error_dict = {"status": "error", "error": error_msg}
                context.window_manager[result_key] = json.dumps(error_dict)
                return {"CANCELLED"}

            # NOTE: No sandboxing - this tool intentionally allows full Python access.
            # If someone can reach this endpoint, they have the same access as Blender itself.
            # Security is handled at the transport layer (auth token + localhost-only by default).
            compiled_code = compile(tree, "<ai-code>", "exec")

            # Redirect stdout to capture output
            buffer = io.StringIO()
            sys.stdout = buffer
            stdout_redirected = True

            local_namespace = {"bpy": bpy, "context": context}
            exec(compiled_code, local_namespace, local_namespace)

            output = buffer.getvalue()

            # Truncate output if too large - provide clear warning with details
            if len(output) > MAX_OUTPUT_SIZE:
                original_size = len(output)
                output = (
                    output[:MAX_OUTPUT_SIZE] + f"\n\n[OUTPUT TRUNCATED]\n"
                    f"Original size: {original_size:,} bytes\n"
                    f"Limit: {MAX_OUTPUT_SIZE:,} bytes (2MB)\n"
                    f"Truncated: {original_size - MAX_OUTPUT_SIZE:,} bytes\n"
                    f"Consider using bpy.data.texts to store large outputs."
                )

            result_dict = {
                "status": "success",
                "output": output if output else "Code executed successfully",
            }
            context.window_manager[result_key] = json.dumps(result_dict)

            # Manually push undo step - ensures each MCP command is undoable separately
            # Wrapped in try/except as undo_push can fail in certain contexts (e.g., modal operators)
            try:
                bpy.ops.ed.undo_push(message="MCP: Execute Code")
            except RuntimeError:
                pass  # Undo not available in current context, silently skip

            return {"FINISHED"}

        except Exception as e:
            error_dict = {"status": "error", "error": f"{type(e).__name__}: {str(e)}"}
            context.window_manager[result_key] = json.dumps(error_dict)
            return {"CANCELLED"}

        finally:
            # ALWAYS restore stdout, even if an exception occurred
            if stdout_redirected:
                try:
                    sys.stdout = old_stdout
                except Exception:
                    # If restoration fails, attempt direct assignment to avoid broken console
                    if sys.__stdout__:
                        setattr(sys, "stdout", sys.__stdout__)
