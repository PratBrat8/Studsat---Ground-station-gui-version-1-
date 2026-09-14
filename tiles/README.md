# Offline map tiles

Place pre-downloaded **XYZ** tiles here for competition use (no internet at runtime).

## Layout

```text
tiles/
  {z}/
    {x}/
      {y}.png
```

Example: `tiles/14/11600/7340.png`

## Backend URL

The Python backend serves:

```text
GET /tiles/{z}/{x}/{y}.png
GET /tiles/info
```

- If a file exists under this folder → that PNG/JPEG is returned.
- If missing → a **local placeholder** tile is generated (still offline).

The React map (`react-leaflet`) points **only** at this local endpoint — never at OSM/MapTiler CDN.

## Demo placeholders

From `backend/`:

```powershell
python scripts/generate_demo_tiles.py
```

Writes a small grid of tiles around the sim pad (≈ Bengaluru).

## Real basemap (before competition)

1. Export the launch-site region as XYZ PNG tiles (e.g. Mobile Atlas Creator, QGIS, MapTiler desktop, or a one-time online download on a networked machine).
2. Copy the `{z}/{x}/{y}.png` tree into this `tiles/` folder.
3. Run the ground station **offline** — the map uses only these files.

Recommended zooms for pad ops: **12–16**, covering pad + expected recovery area with margin.
