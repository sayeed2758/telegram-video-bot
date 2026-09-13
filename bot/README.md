# Phase 4C — Multiple Files

Base: verified Phase 4B quality-selector build.

Replace ONLY:
- bot/resolver.py
- bot/keyboards.py
- bot/handlers.py

Preserved:
- Render webhook / main.py
- TeraBox API environment variable
- platform detection including terasharefile.com
- thumbnail result UI
- quality selector
- Play / Download / Copy Link actions
- DiskWala/Flezen placeholders
- existing database/config files

New:
- Parses every file returned by TeraBox API.
- If one file: behavior remains essentially unchanged.
- If multiple files: shows a compact numbered file picker.
- Selecting a file opens that file's existing thumbnail/metadata/quality UI.
- Callback data uses only a small numeric index; no long URLs are placed in Telegram callback data.
- Backward-compatible first-file fields are retained in ResolveResult.
