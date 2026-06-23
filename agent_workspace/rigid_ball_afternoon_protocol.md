# Rigid Ball Afternoon Protocol

Use this for hard solid balls / rigid spheres. This route does not use droplet oscillation or volume-equivalent liquid assumptions.

The four expected materials are auto-detected from TIFF filenames:

- `PP`
- `PMMA`
- `PS`
- `POM`

Put the material token in the filename, for example `0527_PMMA_trial01.tif`.

## 1. Start before the experiment

Terminal 1:

```powershell
python run_dashboard.py
```

Terminal 2:

```powershell
python agent_loop.py --poll-interval 15 --intake-mode prompt
```

Open:

```text
http://127.0.0.1:8765/dashboard/
```

## 2. When a new TIFF appears

The watcher asks for:

- subjective experience: e.g. `rigid ball, may bounce near frame 420, ignore reflection below floor`
- review criteria: e.g. `radius should be stable; y-t should be parabolic before bounce`
- experiment type: use `rigid_ball`
- valid frame range: optional, e.g. `120,520`; leave blank to let the rigid-ball pipeline auto-select Vfr
- ROI: optional, e.g. `0,80,1920,500`; leave blank to let the rigid-ball pipeline auto-select ROI
- ball radius range in px: optional, e.g. `8,80`
- FPS / scale: enter current values if they differ from `config.yaml`

Type `PROCESS` to start.

## 3. Outputs

For each rigid ball case, output goes to:

```text
processed_data/<case_id>/<case_id>_rigid_ball_auto/
```

Important files:

- `case_summary.json`
- `rigid_ball_summary.json`
- `rigid_ball_summary_panel.png`
- `rigid_ball_trajectory.png`
- `rigid_ball_position_xy.png`
- `rigid_ball_velocity_xy.png`
- `rigid_ball_radius.png`
- `valid_window_tracking_preview.png`
- `*_monitor.mp4`

## 4. Direct one-shot command

Use this if watcher is not running:

```powershell
python rigid_ball_processing.py --tiff "raw_data/<file>.tif" --output-dir "processed_data/<case>/<case>_rigid_ball_auto" --roi 0,80,1920,500 --valid-frame-range 120,520 --fps 2000 --pixel-per-mm 25.5333 --min-radius-px 8 --max-radius-px 80
```

Then refresh dashboard:

```powershell
python dashboard_builder.py
```

## 5. What Franklin scores

For rigid balls, Franklin focuses on:

- valid-frame tracking ratio
- detected radius stability
- y-t parabolic fit quality
- auto ROI / Vfr candidate score
- material grouping from filename
- assumptions such as default ROI/default valid window

Frequency/oscillation is ignored for rigid ball cases.
