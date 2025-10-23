This repository is a desktop control and analysis app for an annealing + imaging system ("System X"). The guidance below gives an AI coding agent the minimum context and conventions needed to be productive editing or extending the codebase.

Project snapshot (big picture)
- Entry point: `main.py` — parses a YAML config file, initializes `services.AppConfig`, `services.Logger`, connects `services.DatabaseService`, then wires `presenters.MainPresenter` to `views.MainView` and starts the GUI main loop.
- Architecture: lightweight MVC/MVP-style with clear layers:
  - views/ — GUI widgets built with `customtkinter` (CTk). Keep UI code in views.
  - presenters/ — glue between views and services/models; presenters bind view commands to presenter methods.
  - services/ — singletons and utility services (logging, config, database, image processing, hardware comms).
  - hardware/ — hardware adapters (annealer, camera, stage, etc.) and communication helpers.
  - operators/ — higher-level domain operations (experiment orchestration, imaging runs, plate operations).
  - models/ — SQLAlchemy ORM models and other domain classes.

Key files and where to look for common tasks
- Start app: `main.py` (requires a YAML config path argument). Example: the expected usage is `python main.py config.yaml`.
- Configuration: `config.yaml` — contains all runtime toggles (camera names, serial ports, annealer PID params, file paths). Use `services.AppConfig.get(key, default)` to read config.
- Logging: `services/logger.py` — singleton Logger is used across the codebase. Instantiate via `Logger()`.
- Database models: `models/*.py` — SQLAlchemy mapping classes (Experiment, Plate, Sample, Protocol, etc.). DB is configured in `services/database_service.py` (search for DatabaseService).
- Camera / hardware: `hardware/camera_controller.py`, `hardware/temika_comms.py`, `hardware/*_controller.py` — adapters talk to hardware using a small XML-like command protocol for Temika devices; prefer high-level adapter methods (e.g., `FlirCameraAdapter.capture_image()`).
- UI flow patterns: presenters wire buttons in the view (see `presenters/main_presenter.py`). Presenters generally import views lazily inside methods to avoid circular imports.

Important conventions and patterns
- Singletons: `services/singleton.py` provides a metaclass used by `AppConfig` and `Logger`. Construct these classes with no args (e.g., `Logger()` or `AppConfig()`) to get the existing instance.
- Lazy imports in presenters: presenters often import views or presenters inside methods (e.g., `from views import ExperimentListView`) to avoid circular imports. Follow that pattern when adding new navigation.
- Hardware adapters: prefer a Factory pattern (see `CameraControllerFactory.create_camera_controller`) and keep vendor-specific code in adapter classes. When adding a new camera type, add a new adapter class that implements the BaseCamera ABC.
- Threading / blocking: GUI uses tkinter main loop. Long-running operations must not block the main thread. Look for operator classes in `operators/`; they should run heavy tasks on background threads or use non-blocking patterns.
- Database access: use `services.DatabaseService` (singleton) to read/write models; don't create direct SQLAlchemy sessions ad-hoc.

Run / debug / test notes (what worked when inspecting files)
- Start GUI (dev):
  - Ensure the environment has dependencies from `requirements.txt` installed.
  - Run: `python main.py config.yaml` (the app expects a path to a YAML file). The `config.yaml` at the repo root is a valid example.
- Logger output: logs are written to the `logs/` folder (log file names come from `config.yaml`). Set the `-v` flag or `debug` flag on `main.py` to enable console logging.
- Hardware simulation: many hardware controllers call `hardware/temika_comms.py` and open serial ports. If hardware is unavailable, either mock `TemikaComms` or run features in sandbox views (`views/*sandbox*`). Look for `stage_force_to_origin` and `annealer_port` config keys.

Representative examples (copy/paste friendly)
- Read a config value:
  app_config = AppConfig()
  camera_name = app_config.get("camera_name")

- Use the logger singleton:
  logger = Logger()
  logger.info("Starting imaging run")

- Create a presenter that opens a view (follow lazy import pattern):
  def open_my_window(self):
      from views import MyView
      from presenters import MyPresenter
      view = MyView()
      presenter = MyPresenter(view, self.db)

- Send a camera command via Temika adapter:
  cam = FlirCameraAdapter()
  cam.set_shutter_speed(50000)
  cam.capture_image()

Integration points and external dependencies
- Serial devices: annealer, Temika-based hardware, and stage controllers — configured in `config.yaml` (e.g., `annealer_port`, `temika_host`). Code uses `pyserial` and small XML-like command strings.
- Camera SDKs: FLIR / IDS adapters — `pyueye` is referenced for IDS (may be optional). FLIR uses `TemikaComms` to talk to a camera host.
- Database: SQLAlchemy (DB URI configured by `sqlite_db` in `config.yaml`). Use `services.database_service.DatabaseService`.
- Optional/3rd-party services: Roboflow (image processing) keys appear in `config.yaml`; treat these as optional and guard network calls.

What to avoid / gotchas (discovered from source)
- Do not import views at module import time inside presenters — follow the existing lazy-imports pattern to avoid circular imports.
- Many modules rely on the singleton behavior of `AppConfig` and `Logger` — re-instantiating them with different arguments won't reconfigure existing instances. Use the patterns already present.
- UI-blocking: avoid long CPU or IO work on the main thread; use `operators/` or background threads.

Editing and commit guidance for AI agents
- Keep edits focused and small. Preserve existing import and singleton patterns.
- When adding features touching hardware, add a sandbox mode (or extend existing sandbox views) so the UI remains usable without hardware.
- If adding public functions or modules, include a one-line docstring and a short unit test in a new `tests/` folder if feasible.

Files to reference for further context
- `main.py`, `config.yaml`, `requirements.txt`
- `services/appconfig.py`, `services/logger.py`, `services/database_service.py`
- `hardware/temika_comms.py`, `hardware/camera_controller.py`, `hardware/*_controller.py`
- `presenters/*`, `views/*`, `operators/*`, `models/*`

If anything here is unclear or you want more detail for a specific area (e.g., database migrations, a particular hardware adapter, or how imaging runs are orchestrated), tell me which area to expand and I'll update this file.
