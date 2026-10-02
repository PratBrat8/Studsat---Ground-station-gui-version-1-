# CAD models (PRD v2 C.8)

Runtime assets. Do not load the STEP files in the Electron app.

| GLB | Source STEP |
| --- | --- |
| `rocket.glb` | `CAED STEP FILES/rocket 150 (1).step` |
| `cansat.glb` | `CAED STEP FILES/Bestcansatttt1 (~recovered).step` |

Regenerate after a CAD change:

```
python -m venv tools/cad-venv
tools/cad-venv/Scripts/python -m pip install cadquery
tools/cad-venv/Scripts/python scripts/convert_cad_to_glb.py
```

The converter tessellates with OpenCascade, centers the AABB, and rotates the longest axis to +Y (Three.js up / nose-up). Copies also land in `frontend/public/models/` so Vite and Electron `file://` resolve `./models/*.glb`.
