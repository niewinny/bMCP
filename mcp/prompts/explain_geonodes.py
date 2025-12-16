"""
Explain Geometry Nodes Prompt

Provides a structured prompt for explaining selected geometry nodes.
"""

from typing import List

from ._internal.registry import prompt


@prompt
def explain_geonodes(focus: str = "all") -> List[dict]:
    """Explain selected geometry nodes in detail.

    Args:
        focus: Area to focus on - "all", "inputs", "outputs", "flow", or "optimization"
    """
    base_instruction = """You are a Blender geometry nodes expert. Your task is to analyze and explain the geometry nodes setup provided by the `blender://selected_geometry_nodes` resource.

## Instructions

1. First, read the `blender://selected_geometry_nodes` resource to get the node graph data
2. Analyze the nodes, their connections, and their purposes
3. Provide a clear, educational explanation

## Analysis Structure

### 1. Overview
- What is the overall purpose of this node setup?
- What kind of geometry/effect does it create?

### 2. Node-by-Node Breakdown
For each significant node, explain:
- **What it does**: The node's function in simple terms
- **Inputs**: What data it receives and from where
- **Outputs**: What data it produces
- **Why it's used**: Its role in achieving the final result

### 3. Data Flow
Trace how geometry/data transforms from Group Input to Group Output:
- Start with the input geometry or parameters
- Follow each major transformation step
- End with what the output produces

### 4. Key Connections
Highlight important socket connections:
- Which connections are critical for the effect?
- Are there any field connections (vs geometry connections)?
- Any attribute transfers or captures?

### 5. Tips & Insights
- Common modifications users might want to make
- Potential gotchas or things to watch out for
- How this setup relates to common geometry nodes patterns"""

    focus_sections = {
        "inputs": """

## Special Focus: Inputs & Parameters

Pay special attention to:
- The **Group Input** node and all exposed parameters
- How each input parameter affects the final result
- Default values and their significance
- Which parameters are most important for customization
- Suggested value ranges for each parameter""",
        "outputs": """

## Special Focus: Outputs & Results

Emphasize:
- What the **Group Output** produces
- The type and quality of output geometry
- Any attributes that are output alongside geometry
- How to use/connect this node group's output in other contexts
- What downstream nodes would typically consume this output""",
        "flow": """

## Special Focus: Data Flow Analysis

Provide a detailed step-by-step trace:
1. Start at Group Input - what enters the system
2. For each transformation, describe:
   - Input state of geometry/data
   - What the node does to it
   - Output state after processing
3. Track how fields and attributes propagate
4. Note any branching paths (geometry used multiple ways)
5. Converge at Group Output - final state""",
        "optimization": """

## Special Focus: Optimization & Improvements

Analyze and suggest:
- **Performance**: Are there nodes that could be expensive? Alternatives?
- **Simplification**: Can any nodes be combined or removed?
- **Flexibility**: What parameters could be exposed for more control?
- **Robustness**: Are there edge cases that might break the setup?
- **Best Practices**: Does this follow geometry nodes conventions?
- **Alternatives**: Different approaches that might achieve similar results""",
        "all": "",
    }

    focus_section = focus_sections.get(focus, "")
    prompt_text = base_instruction + focus_section

    return [{"role": "user", "content": {"type": "text", "text": prompt_text}}]
