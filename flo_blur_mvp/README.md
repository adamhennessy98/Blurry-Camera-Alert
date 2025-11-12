# Flo Blur MVP

Flo Blur MVP is a lightweight simulator I put together to demo how we could watch for blurry cameras on a production line. It keeps a handful of virtual cameras humming along, raises Tkinter pop-ups when a lens stays foggy, and writes everything down to CSV for later analysis. When someone clicks **Clean Lens**, it also records the full blur episode so we know how long the issue lasted.

## What You Need

- Python 3.11 (anything 3.10+ should be fine — 3.11 is what I used)
- Tkinter, which comes with the standard Windows Python installer
- Git, so you can clone the repo

## Getting Started

1. Clone the project and jump into the folder:
   ```powershell
   git clone https://github.com/<your-user>/flo_blur_mvp.git
   cd flo_blur_mvp
   ```
2. Spin up a virtual environment (optional):
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```
3. Install the package locally. This also gives you a `flo-blur-mvp` command you can run from anywhere:
   ```powershell
   python -m pip install --upgrade pip
   python -m pip install .
   ```



## Using the Simulator

Command:
```powershell
python blurry_mvp.py --cameras 3 --interval 5   
```

While it’s running you’ll see pop-up windows. Hit **Clean Lens** when you want to resolve an alert — the simulator clears the blur, records the episode, and goes back to watching.

## What Gets Logged

- `events.csv` captures every simulator tick with the timestamp, camera id, and whether it looked blurry.
- `blur_episodes.csv` adds a row each time someone clears a blur, so you can see how long the camera stayed dirty.

Both files include headers the first time they’re created, so they play nice with spreadsheets.

## Running the Tests

Install the dev extras and run pytest:
```powershell
python -m pip install .[dev]
python -m pytest
```

If you’re more of a tox/nox person:
```powershell
python -m pip install tox nox
tox
nox -s tests
```

## Building Distributables

The project uses a `pyproject.toml` with setuptools and exposes the `flo-blur-mvp` entry point. If you want to ship a wheel or sdist:
```powershell
python -m pip install build
python -m build
```

