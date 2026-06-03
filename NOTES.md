# Repository notes

This repository stores the source version of the realtime translator.

The local desktop build files were intentionally not uploaded:

- `RealtimeTranslator.exe`
- `realtime_translator_app.zip`
- `__pycache__/`

To rebuild an executable, install PyInstaller locally and run a command similar to:

```powershell
python -m PyInstaller --onefile --windowed --name RealtimeTranslator realtime_translator.py
```
