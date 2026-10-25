# Friday 1.0

<p align="center"><img src="assets/friday_icon.png" alt="Friday app icon" width="120"></p>

Friday is a local-first Windows desktop assistant. It uses Ollama for local language models and keeps conversations and settings on your own computer.

## Run from source (Windows)

1. Install Python 3.12 or newer.
2. Install the project dependencies from PowerShell:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

3. Install Ollama from [ollama.com/download](https://ollama.com/download).
4. In PowerShell, download a model (example):

   ```powershell
   ollama pull qwen2.5:7b
   ollama list
   ```

5. Start Friday:

   ```powershell
   python friday.py
   ```

Friday starts Ollama when needed, refreshes the installed model list, and preloads the selected local model at launch when one is installed. Ollama keeps it in memory for five minutes so the first reply does not have to wait for a cold model load. Model files remain in Ollama's own model store; they are not included in this repository or the app build.

## Build the Windows app

The PyInstaller spec creates a windowed one-folder app so Qt runtime DLLs stay alongside the EXE. This avoids the one-file extraction failure some Windows systems encounter. Install the dependencies above, then run:

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean friday.spec
```

Launch `dist\Friday\Friday.exe`. Keep the complete `dist\Friday` folder together when copying or distributing the app. It opens as a desktop window without a Python console. Friday stores its local database and settings in `.friday_data` beside the app. A Windows build ZIP is produced by the GitHub Actions workflow, and pushing a `v*` tag also publishes that ZIP as a GitHub Release.

## Features

- Chat with locally installed Ollama models, with an automatic model option.
- Optional web and image search.
- Voice mode, local file reading, conversation history, and local settings.
- In-app checks for Friday and Ollama updates.

Web and image search and update checks need an internet connection. Friday does not use an online AI API. YouTube video search and playback links are available, but Friday does not download YouTube videos.

## Privacy and included files

- Conversation history and settings stay in `.friday_data` on the computer running the app. This folder is excluded from Git.
- Ollama model weights are stored and managed by Ollama. They are not included here; install Ollama and run `ollama pull qwen2.5:7b` (or choose another Ollama model).
- No Gmail integration is included.
- Do not commit personal databases, profiles, credentials, local model files, or build caches.

## Project layout

- `friday/` — application source.
- `tests/` — focused reliability tests.
- `assets/` — Friday app icons.
- `requirements.txt` — Python dependencies.
- `friday.spec` — windowed PyInstaller build configuration.
