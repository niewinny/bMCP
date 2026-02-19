#!/usr/bin/env python3
"""
Build script for creating the bmcp mega-wheel.

This script:
1. Builds the bmcp wheel normally using hatchling
2. Downloads all dependency wheels
3. Extracts all wheels into a staging directory (skipping native extensions)
4. Combines all top-level packages into a single wheel
5. Generates new RECORD/METADATA
6. Repacks as a single wheel
7. Copies to ../wheels/

The resulting wheel contains bmcp + ALL dependencies bundled together.
Websockets is included as pure-Python only (C speedups stripped, falls back
to Python implementation automatically).

Usage:
    python scripts/build_wheel.py
"""

import hashlib
import io
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# Configuration
BMCP_VERSION = "1.0.0"
WHEEL_NAME = f"bmcp-{BMCP_VERSION}-py3-none-any.whl"
DIST_INFO_DIR = f"bmcp-{BMCP_VERSION}.dist-info"

# All dependencies to bundle (with version constraints)
DEPS = [
    "starlette>=0.50.0",
    "uvicorn>=0.38.0",
    "anyio>=4.0.0",
    "h11>=0.16.0",
    "sniffio>=1.3.0",
    "click>=8.0.0",
    "websockets>=15.0.0",
]

# File extensions to strip from wheels (native C extensions)
# Websockets falls back to pure Python when these are missing
STRIP_EXTENSIONS = {".so", ".pyd", ".dylib", ".dll", ".c", ".h"}

# Directories/files to skip when merging
SKIP_PATTERNS = {".dist-info", "__pycache__", ".pyc"}


def run_cmd(cmd, cwd=None, check=True):
    """Run a command and return output."""
    print(f"  > {' '.join(cmd)}")
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=cwd, check=check
    )
    if result.returncode != 0 and check:
        print(f"  STDERR: {result.stderr}")
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result


def build_bmcp_wheel(project_dir, dist_dir):
    """Build the bmcp wheel using pip wheel."""
    print("\n[1/6] Building bmcp wheel...")
    run_cmd(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(dist_dir), str(project_dir)]
    )

    # Find the built wheel
    wheels = list(dist_dir.glob("bmcp-*.whl"))
    if not wheels:
        raise RuntimeError("bmcp wheel not found after build")
    print(f"  Built: {wheels[0].name}")
    return wheels[0]


def download_deps(dist_dir, deps_dir):
    """Download dependency wheels."""
    print("\n[2/6] Downloading dependencies...")

    for dep in DEPS:
        print(f"  Downloading: {dep}")
        result = run_cmd([
            sys.executable, "-m", "pip", "download",
            "--no-deps",
            "--only-binary=:all:",
            "--dest", str(deps_dir),
            dep,
        ], check=False)
        if result.returncode != 0:
            print(f"  WARN: Failed to download {dep}: {result.stderr.strip()}")

    dep_wheels = list(deps_dir.glob("*.whl"))
    print(f"  Downloaded {len(dep_wheels)} dependency wheels")
    for w in dep_wheels:
        print(f"    - {w.name}")
    return dep_wheels


def extract_wheel(wheel_path, target_dir, strip_native=False):
    """Extract a wheel to a target directory, skipping dist-info and optionally native extensions."""
    stripped = 0
    with zipfile.ZipFile(wheel_path, "r") as zf:
        for info in zf.infolist():
            # Skip dist-info directories and __pycache__
            if any(skip in info.filename for skip in SKIP_PATTERNS):
                continue
            # Optionally strip native C extensions
            if strip_native:
                ext = os.path.splitext(info.filename)[1].lower()
                if ext in STRIP_EXTENSIONS:
                    stripped += 1
                    continue
            zf.extract(info, target_dir)
    return stripped


def sha256_digest(data):
    """Calculate base64url-encoded SHA256 digest for RECORD."""
    import base64
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_mega_wheel(bmcp_wheel, dep_wheels, output_dir, staging_dir):
    """Combine all wheels into a single mega-wheel."""
    print("\n[3/6] Extracting wheels into staging area...")

    # Extract bmcp wheel first
    print(f"  Extracting: {bmcp_wheel.name}")
    extract_wheel(bmcp_wheel, staging_dir)

    # Extract dependency wheels (strip native extensions)
    for dep_wheel in dep_wheels:
        print(f"  Extracting: {dep_wheel.name}")
        stripped = extract_wheel(dep_wheel, staging_dir, strip_native=True)
        if stripped:
            print(f"    (stripped {stripped} native extension files)")

    # List what we have in staging
    top_level = [d.name for d in staging_dir.iterdir() if d.is_dir()]
    print(f"\n[4/6] Top-level packages in mega-wheel: {', '.join(sorted(top_level))}")

    # Create dist-info directory
    print("\n[5/6] Generating dist-info...")
    dist_info = staging_dir / DIST_INFO_DIR
    dist_info.mkdir(exist_ok=True)

    # Write METADATA
    metadata = f"""Metadata-Version: 2.1
Name: bmcp
Version: {BMCP_VERSION}
Summary: Python SDK for building MCP (Model Context Protocol) servers - bundled with dependencies
Requires-Python: >=3.11
License: GPL-3.0-or-later
"""
    (dist_info / "METADATA").write_text(metadata)

    # Write WHEEL
    wheel_info = """Wheel-Version: 1.0
Generator: bmcp-build-script
Root-Is-Purelib: true
Tag: py3-none-any
"""
    (dist_info / "WHEEL").write_text(wheel_info)

    # Write top_level.txt
    (dist_info / "top_level.txt").write_text("\n".join(sorted(top_level)) + "\n")

    # Generate RECORD
    print("\n[6/6] Packing mega-wheel...")
    record_lines = []
    output_path = output_dir / WHEEL_NAME

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(staging_dir):
            # Skip __pycache__ directories
            dirs[:] = [d for d in dirs if d != "__pycache__"]

            for file in files:
                file_path = Path(root) / file
                arc_name = str(file_path.relative_to(staging_dir)).replace("\\", "/")

                # Skip the RECORD file itself (added at the end)
                if arc_name == f"{DIST_INFO_DIR}/RECORD":
                    continue

                data = file_path.read_bytes()
                zf.writestr(arc_name, data)

                # Add to RECORD
                digest = sha256_digest(data)
                record_lines.append(f"{arc_name},{digest},{len(data)}")

        # Add RECORD itself (no hash)
        record_lines.append(f"{DIST_INFO_DIR}/RECORD,,")
        record_content = "\n".join(record_lines) + "\n"
        zf.writestr(f"{DIST_INFO_DIR}/RECORD", record_content)

    print(f"\n  Mega-wheel created: {output_path}")
    print(f"  Size: {output_path.stat().st_size / 1024:.1f} KB")
    return output_path


def copy_to_addon_wheels(mega_wheel, addon_wheels_dir):
    """Copy the mega-wheel to the addon's wheels directory, removing all old wheels."""
    print(f"\n  Copying to addon wheels directory: {addon_wheels_dir}")

    # Remove ALL old wheels (everything is now in the mega-wheel)
    for old_wheel in addon_wheels_dir.glob("*.whl"):
        old_wheel.unlink()
        print(f"  Removed: {old_wheel.name}")

    # Copy new mega-wheel
    dest = addon_wheels_dir / mega_wheel.name
    shutil.copy2(mega_wheel, dest)
    print(f"  Copied: {dest.name}")


def main():
    """Main build process."""
    # Determine paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent  # .bmcp/
    addon_dir = project_dir.parent  # bmcp addon root
    addon_wheels_dir = addon_dir / "wheels"

    # Build directories
    build_dir = project_dir / "build"
    dist_dir = project_dir / "dist"
    deps_dir = build_dir / "deps"
    staging_dir = build_dir / "staging"

    print("=" * 60)
    print(f"Building bmcp mega-wheel v{BMCP_VERSION}")
    print("=" * 60)
    print(f"  Project dir: {project_dir}")
    print(f"  Addon dir:   {addon_dir}")
    print(f"  Output:      {addon_wheels_dir}")

    # Clean build directories
    for d in [build_dir, dist_dir]:
        if d.exists():
            shutil.rmtree(d)
    for d in [build_dir, dist_dir, deps_dir, staging_dir]:
        d.mkdir(parents=True, exist_ok=True)

    try:
        # Step 1: Build bmcp wheel
        bmcp_wheel = build_bmcp_wheel(project_dir, dist_dir)

        # Step 2: Download dependencies
        dep_wheels = download_deps(dist_dir, deps_dir)

        # Step 3-6: Build mega-wheel
        mega_wheel = build_mega_wheel(bmcp_wheel, dep_wheels, dist_dir, staging_dir)

        # Copy to addon wheels directory
        addon_wheels_dir.mkdir(parents=True, exist_ok=True)
        copy_to_addon_wheels(mega_wheel, addon_wheels_dir)

        print("\n" + "=" * 60)
        print("BUILD SUCCESSFUL")
        print("=" * 60)

        # List remaining wheels
        print("\nWheels in addon directory:")
        for w in sorted(addon_wheels_dir.glob("*.whl")):
            size = w.stat().st_size / 1024
            print(f"  {w.name} ({size:.1f} KB)")

    finally:
        # Clean up build directory
        if build_dir.exists():
            shutil.rmtree(build_dir)
            print("\n  Cleaned up build directory")


if __name__ == "__main__":
    main()
