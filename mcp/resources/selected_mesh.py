"""
Selected Mesh Resource

Provides information about selected mesh.
"""

import traceback

import bmesh
import bpy

from ._internal.registry import resource

# Safety limits to prevent Blender hangs
MAX_VERTICES = 100_000  # Maximum vertices before returning truncated info


@resource
def selected_mesh() -> str:
    """
    Returns comprehensive information about selected mesh.
    """
    try:
        active = bpy.context.active_object
        mode = bpy.context.mode

        if not active or active.type != "MESH":
            return f"# Selected Mesh\n\nNo active mesh object.\n\n**Active Object**: {active.name if active else 'None'} ({active.type if active else 'N/A'})\n**Mode**: {mode}"

        mesh = active.data
        obj = active

        output = f"# Selected Mesh: {obj.name}\n\n"
        output += f"**Mesh Data**: {mesh.name}\n"
        output += f"**Current Mode**: {mode}\n\n"

        # Basic mesh statistics
        output += "## Mesh Statistics\n\n"
        output += f"- **Vertices**: {len(mesh.vertices)}\n"
        output += f"- **Edges**: {len(mesh.edges)}\n"
        output += f"- **Faces**: {len(mesh.polygons)}\n"
        output += (
            f"- **Triangles**: {sum(len(p.vertices) - 2 for p in mesh.polygons)}\n"
        )

        # Edit mode analysis (create BMesh once and reuse)
        # NOTE: bmesh.from_edit_mesh() returns a REFERENCE to the live edit mesh,
        # NOT a copy. Therefore:
        # - Do NOT call bm.free() - that would corrupt the edit mesh!
        # - Do NOT call bmesh.update_edit_mesh() since we only read, never modify
        # This is different from bmesh.new() or bmesh.from_mesh() which create
        # copies that MUST be freed.
        bm = None  # Initialize BMesh variable for later reuse
        if mode == "EDIT_MESH":
            # Safety check: prevent hanging on huge meshes
            if len(mesh.vertices) > MAX_VERTICES:
                output += "- **Loose Vertices**: N/A (mesh too large)\n"
                output += "- **Loose Edges**: N/A (mesh too large)\n"
                output += "\n## Edit Mode Selection\n\n"
                output += f"**WARNING: Mesh Too Large** - {len(mesh.vertices):,} vertices (limit: {MAX_VERTICES:,})\n\n"
                output += "Detailed edit mode info disabled for performance.\n"
                output += (
                    "Use `blender_run_code` tool for custom queries on large meshes.\n"
                )
            else:
                # Create BMesh once and reuse for all edit mode operations
                bm = bmesh.from_edit_mesh(mesh)

                # Calculate loose vertices/edges efficiently using BMesh properties
                loose_verts = sum(1 for v in bm.verts if not v.link_edges)
                loose_edges = sum(1 for e in bm.edges if not e.link_faces)
                output += f"- **Loose Vertices**: {loose_verts}\n"
                output += f"- **Loose Edges**: {loose_edges}\n"

                # Edit mode selection details (reusing same BMesh instance)
                output += "\n## Edit Mode Selection\n\n"

                selected_verts = [v for v in bm.verts if v.select]
                selected_edges = [e for e in bm.edges if e.select]
                selected_faces = [f for f in bm.faces if f.select]
                output += f"- **Selected Vertices**: {len(selected_verts)} / {len(bm.verts)}\n"
                output += (
                    f"- **Selected Edges**: {len(selected_edges)} / {len(bm.edges)}\n"
                )
                output += (
                    f"- **Selected Faces**: {len(selected_faces)} / {len(bm.faces)}\n"
                )

                # Extract active element once to avoid AttributeError
                active_elem = bm.select_history.active
                if active_elem and isinstance(active_elem, bmesh.types.BMVert):
                    output += f"- **Active Vertex**: {active_elem.index}\n"
                else:
                    output += "- **Active Vertex**: None\n"

                if active_elem and isinstance(active_elem, bmesh.types.BMEdge):
                    output += (
                        f"- **Active Edge**: {[v.index for v in active_elem.verts]}\n"
                    )
                else:
                    output += "- **Active Edge**: None\n"

                if active_elem and isinstance(active_elem, bmesh.types.BMFace):
                    output += f"- **Active Face**: {active_elem.index}\n"
                else:
                    output += "- **Active Face**: None\n"

                # Selection mode
                select_mode = bpy.context.tool_settings.mesh_select_mode
                mode_names = []
                if select_mode[0]:
                    mode_names.append("Vertex")
                if select_mode[1]:
                    mode_names.append("Edge")
                if select_mode[2]:
                    mode_names.append("Face")
                output += f"- **Selection Mode**: {', '.join(mode_names)}\n"

                # Mesh elements info for selected items
                if selected_verts and len(selected_verts) <= 20:
                    output += f"\n**Selected Vertex Indices**: {[v.index for v in selected_verts]}\n"

                if selected_faces and len(selected_faces) <= 10:
                    output += "\n**Selected Face Info**:\n"
                    for face in selected_faces[:10]:
                        output += f"  - Face {face.index}: {len(face.verts)} verts, "
                        output += f"Normal: ({face.normal.x:.2f}, {face.normal.y:.2f}, {face.normal.z:.2f}), "
                        output += f"Area: {face.calc_area():.4f}\n"
        else:
            # Object mode - no BMesh available
            output += "- **Loose Vertices**: N/A (enter edit mode for analysis)\n"
            output += "- **Loose Edges**: N/A (enter edit mode for analysis)\n"

        # UV Maps
        if mesh.uv_layers:
            output += f"\n## UV Maps ({len(mesh.uv_layers)})\n\n"
            for i, uv_layer in enumerate(mesh.uv_layers):
                marker = "**ACTIVE**" if uv_layer == mesh.uv_layers.active else ""
                output += f"{i + 1}. {uv_layer.name} {marker}\n"

        # Color Attributes (Blender 3.2+, replaces deprecated vertex_colors)
        if hasattr(mesh, "color_attributes") and mesh.color_attributes:
            output += f"\n## Color Attributes ({len(mesh.color_attributes)})\n\n"
            for i, attr in enumerate(mesh.color_attributes):
                marker = (
                    "**ACTIVE**" if attr == mesh.color_attributes.active_color else ""
                )
                output += f"{i + 1}. {attr.name} (Domain: {attr.domain}, Type: {attr.data_type}) {marker}\n"

        # Vertex Groups
        if obj.vertex_groups:
            output += f"\n## Vertex Groups ({len(obj.vertex_groups)})\n\n"
            for i, vg in enumerate(obj.vertex_groups):
                marker = (
                    "**ACTIVE**" if vg.index == obj.vertex_groups.active_index else ""
                )
                output += f"{i + 1}. {vg.name} (Index: {vg.index}) {marker}\n"

        # Shape Keys
        if mesh.shape_keys:
            output += f"\n## Shape Keys ({len(mesh.shape_keys.key_blocks)})\n\n"
            output += f"- **Use Relative**: {mesh.shape_keys.use_relative}\n"
            # Get active shape key safely (may not exist)
            active_shape_key = getattr(obj, "active_shape_key", None)
            for i, key in enumerate(mesh.shape_keys.key_blocks):
                marker = (
                    "**ACTIVE**" if active_shape_key and key == active_shape_key else ""
                )
                output += f"{i + 1}. {key.name} - Value: {key.value:.3f}"
                if key.mute:
                    output += " [Muted]"
                output += f" {marker}\n"

        # Materials
        if mesh.materials:
            output += f"\n## Material Slots ({len(mesh.materials)})\n\n"
            for i, mat in enumerate(mesh.materials):
                if mat:
                    output += f"{i + 1}. **{mat.name}**\n"
                    output += f"   - Uses Nodes: {mat.use_nodes}\n"

                    if mat.use_nodes and mat.node_tree:
                        nodes = mat.node_tree.nodes
                        output += f"   - Nodes: {len(nodes)}\n"

                        # Output node
                        output_nodes = [
                            n
                            for n in nodes
                            if n.type == "OUTPUT_MATERIAL" and n.is_active_output
                        ]
                        if output_nodes:
                            output += f"   - Active Output: {output_nodes[0].name}\n"

                        # BSDF nodes
                        bsdf_nodes = [n for n in nodes if "BSDF" in n.type]
                        if bsdf_nodes:
                            output += f"   - BSDF Shaders: {', '.join([n.type for n in bsdf_nodes])}\n"
                else:
                    output += f"{i + 1}. (Empty material slot)\n"

        # Face Maps (if any)
        if hasattr(mesh, "face_maps") and mesh.face_maps:
            output += f"\n## Face Maps ({len(mesh.face_maps)})\n\n"
            for i, fm in enumerate(mesh.face_maps):
                output += f"{i + 1}. {fm.name}\n"

        # Custom Attributes
        if hasattr(mesh, "attributes"):
            custom_attrs = [
                attr for attr in mesh.attributes if not attr.name.startswith(".")
            ]
            if custom_attrs:
                output += f"\n## Custom Attributes ({len(custom_attrs)})\n\n"
                for attr in custom_attrs:
                    output += f"- **{attr.name}**: Domain={attr.domain}, Type={attr.data_type}\n"

        # Normals settings
        output += "\n## Normals\n\n"
        if hasattr(mesh, "use_auto_smooth"):
            # Blender 4.0 and earlier
            output += f"- **Auto Smooth**: {mesh.use_auto_smooth}\n"
            if mesh.use_auto_smooth:
                output += f"- **Auto Smooth Angle**: {mesh.auto_smooth_angle:.3f} rad ({mesh.auto_smooth_angle * 57.2958:.1f}°)\n"
        else:
            # Blender 4.1+ - auto smooth moved to modifiers
            output += "- **Auto Smooth**: N/A (Blender 4.1+ uses modifier system)\n"

        # Remesh settings (if any)
        if hasattr(mesh, "remesh_mode"):
            output += "\n## Remesh Settings\n\n"
            output += f"- **Mode**: {mesh.remesh_mode}\n"
            output += f"- **Voxel Size**: {mesh.remesh_voxel_size}\n"

        # Mesh validation info (reuse BMesh if available)
        output += "\n## Validation Info\n\n"

        if bm is not None:
            # Reuse existing BMesh from edit mode section
            non_manifold_edges = [e for e in bm.edges if not e.is_manifold]
            output += f"- **Non-Manifold Edges**: {len(non_manifold_edges)}\n"

            # Check for ngons
            ngons = [f for f in bm.faces if len(f.verts) > 4]
            output += f"- **N-gons** (>4 sides): {len(ngons)}\n"

            # Check for tris
            tris = [f for f in bm.faces if len(f.verts) == 3]
            output += f"- **Triangles**: {len(tris)}\n"
        elif mode == "EDIT_MESH":
            # Edit mode but mesh was too large - skipped BMesh creation
            output += "- **Validation skipped** - mesh too large\n"
        else:
            # Object mode - no validation available
            output += "- **Validation not available** - enter edit mode\n"

        return output

    except Exception as e:
        # Resource failed - return error as markdown string (never raise exceptions)
        error_trace = traceback.format_exc()

        return f"""# Selected Mesh - Error

**ERROR**: Failed to retrieve mesh information

**Exception Type**: {type(e).__name__}
**Error Message**: {str(e)}

## Traceback
```
{error_trace}
```

## Troubleshooting
- Ensure you have a mesh object selected
- Make sure you're in Object or Edit mode
- Check that the mesh data is valid
- Try selecting a different mesh
- Restart Blender if issues persist

## Common Issues
- **AttributeError**: Mesh data might be corrupted or invalid
- **TypeError**: Unexpected data type in mesh properties
- **ImportError**: bmesh module not available (check Blender version)
- **RuntimeError**: BMesh operation failed (try exiting/re-entering edit mode)
"""
