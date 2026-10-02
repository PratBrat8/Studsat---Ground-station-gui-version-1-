"""
STEP → GLB conversion (PRD v2 C.8 / Phase 6).

One-time build step. Runtime never imports CadQuery — the app only loads the
resulting .glb files.

Requires a CadQuery/OCP environment (Python 3.9–3.12):

    python -m venv tools/cad-venv
    tools/cad-venv/Scripts/python -m pip install cadquery
    tools/cad-venv/Scripts/python scripts/convert_cad_to_glb.py

Outputs (identical copies):
    assets/models/rocket.glb
    assets/models/cansat.glb
    frontend/public/models/rocket.glb
    frontend/public/models/cansat.glb

Convention baked into the GLB:
    - origin at the AABB center
    - longest axis aligned to +Y (Three.js up / vehicle nose-up)
    - units millimetres as in the Fusion/Autodesk STEP export
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEP_DIR = ROOT / "CAED STEP FILES"
ROCKET_STEP = STEP_DIR / "rocket 150 (1).step"
CANSAT_STEP = STEP_DIR / "Bestcansatttt1 (~recovered).step"

OUT_DIRS = (
    ROOT / "assets" / "models",
    ROOT / "frontend" / "public" / "models",
)

# Tessellation in model units (mm). CanSat has dense B-splines — slightly
# coarser than the rocket to keep the GLB web-friendly.
ROCKET_TOL_MM = 0.15
CANSAT_TOL_MM = 0.35
ANGULAR_TOL_RAD = 0.2


def _align_longest_to_y(shape):
    """Center the solid and rotate so the longest AABB edge is +Y."""
    bb = shape.BoundingBox()
    shape = shape.translate((-bb.center.x, -bb.center.y, -bb.center.z))
    bb = shape.BoundingBox()
    longest = max(
        (("x", bb.xlen), ("y", bb.ylen), ("z", bb.zlen)),
        key=lambda item: item[1],
    )[0]
    origin = (0, 0, 0)
    if longest == "z":
        # Typical Fusion Z-up → Three.js Y-up.
        shape = shape.rotate(origin, (1, 0, 0), -90)
    elif longest == "x":
        shape = shape.rotate(origin, (0, 0, 1), 90)
    bb = shape.BoundingBox()
    shape = shape.translate((-bb.center.x, -bb.center.y, -bb.center.z))
    return shape, longest


def convert_step(
    src: Path,
    stem: str,
    *,
    color,
    tolerance: float,
) -> Path:
    import cadquery as cq

    if not src.is_file():
        raise FileNotFoundError(f"STEP missing: {src}")

    print(f"import {src.name} ({src.stat().st_size} bytes)")
    # These Autodesk STEP files are compounds of solids, not XCAF assemblies.
    wp = cq.importers.importStep(str(src))
    compound = wp.val()
    aligned, longest = _align_longest_to_y(compound)
    bb = aligned.BoundingBox()
    print(
        f"  longest-was {longest}  aabb "
        f"{bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm"
    )

    out_assy = cq.Assembly()
    out_assy.add(aligned, name=stem, color=color)

    primary = OUT_DIRS[0] / f"{stem}.glb"
    primary.parent.mkdir(parents=True, exist_ok=True)
    print(f"  tessellate tol={tolerance} mm → {primary}")
    out_assy.export(
        str(primary),
        exportType="GLTF",
        tolerance=tolerance,
        angularTolerance=ANGULAR_TOL_RAD,
    )
    size = primary.stat().st_size
    print(f"  wrote {primary} ({size} bytes)")
    if size < 200:
        raise RuntimeError(f"GLB looks empty: {primary}")

    for dest_dir in OUT_DIRS[1:]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{stem}.glb"
        shutil.copy2(primary, dest)
        print(f"  copy {dest}")
    return primary


def main() -> int:
    import cadquery as cq

    convert_step(
        ROCKET_STEP,
        "rocket",
        color=cq.Color(0.94, 0.45, 0.24, 1.0),
        tolerance=ROCKET_TOL_MM,
    )
    convert_step(
        CANSAT_STEP,
        "cansat",
        color=cq.Color(0.72, 0.80, 0.86, 1.0),
        tolerance=CANSAT_TOL_MM,
    )
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
