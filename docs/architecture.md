# NeisAutoInput Architecture

## V3 Current State

V3 is a single-file CustomTkinter application in `NeisAutoInputV3.py`. The `MacroApp` class owns almost every responsibility:

- window creation, tabs, styling, table widgets, dialogs, and status bar
- settings loading and saving through `config.json`
- student data persistence through `data.csv` and `student.csv`
- achievement standard loading through `achievement_standards.json`
- Gemini prompt construction and API calls
- NEIS macro execution through `keyboard`, `pyautogui`, and `pyperclip`

The runtime files are stored next to the script during development and next to the executable when frozen with PyInstaller. The bundled achievement standards file is resolved with a PyInstaller-aware `resource_path()` helper.

## V3 Data Flow

1. App startup loads `config.json`.
2. If `student.csv` exists, names are loaded and used as the initial table.
3. Otherwise the app uses `student_count` from config or asks for a first-run count.
4. The NEIS tab edits a two-column table: `이름`, `내용`.
5. `data.csv` stores the full table and `student.csv` stores only names.
6. The AI tab loads grade, subject, domain, and standard data from `achievement_standards.json`.
7. Selected standards are converted into a Korean prompt and sent to Gemini in batches.
8. The macro loop copies each row's content to the clipboard, pastes it into NEIS, then presses Tab a configured number of times.

## V3 Technical Debt

- UI, persistence, AI, and automation are tightly coupled in one class.
- The Gemini API key is stored as plaintext in `api_key.txt`.
- The legacy `google-generativeai` package is used instead of the newer `google-genai` SDK.
- Macro execution runs close to the UI layer and relies on blocking calls.
- AI output is treated as plain text with limited validation.
- Error handling is user-facing in some places but silent or `print`-based in others.
- The app is difficult to unit test because behavior is embedded in widget methods.

## V4 Architecture

V4 is a new PySide6 project under `NeisAutoInputV4`.

- `main.py` starts the application.
- `neis_v4/app.py` creates `QApplication` and the main window.
- `neis_v4/ui/` contains tab-specific UI classes.
- `neis_v4/models.py` contains dataclass models for settings, student rows, standards, and AI requests.
- `neis_v4/storage.py` owns JSON, CSV, resource, and user-data paths.
- `neis_v4/secrets.py` stores API keys through `keyring`.
- `neis_v4/ai/` contains a provider interface plus Gemini and OpenAI implementations.
- `neis_v4/automation/runner.py` runs NEIS input automation in a `QThread`.

## V4 Runtime Files

- `config.json`: settings such as macro delay, Tab count, provider, and model names.
- `data.csv`: full student table with `이름`, `내용` headers.
- `student.csv`: reusable student roster with `이름` header.
- API keys: stored in OS credential storage via `keyring`.
- `resources/achievement_standards.json`: bundled achievement standard data.
- `resources/icon.ico`: application icon.

In development, runtime files live in the `NeisAutoInputV4` folder. In a PyInstaller build, runtime files live under `%APPDATA%\NeisAutoInputV4`, while bundled resources are read from the executable bundle.

## V4 Interaction Flow

The main window creates three tabs:

- NEIS input tab: table editing, CSV persistence, macro controls, status, progress.
- AI comment tab: provider/model selection, API key setup, achievement standard selection, generation result preview, and table insertion.
- Settings tab: global settings and model defaults.

AI generation is executed in a background `QThread`. The selected provider returns a normalized `GenerationResult`. The UI validates the number of generated comments and can insert them into the NEIS table.

The macro runner receives immutable row data and settings at start time. It emits progress/status signals back to the UI and supports Esc-based cancellation.
