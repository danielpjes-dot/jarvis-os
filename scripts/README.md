# JARVIS Python Watcher

Files:
- `watcher.py` — Python replacement for the Bash watcher.
- `watcher.sh` — tiny launcher that starts `watcher.py`.
- `install.sh` — copies both files into `/mnt/e/coding/jarvis-os/scripts`.

## Notes
- Keeps the same bridge files under `/tmp/jarvis`.
- Keeps route/model selection, TTS, history, runtime persona, and current spoken sentence support.
- `TTS_SENTENCE_LIMIT = 0` means speak all sentences.
- Designed for your WSL + Windows toolchain with `mpv.exe`, `powershell.exe`, and optional `ffmpeg.exe`.

## Start
```bash
cd /mnt/data/jarvis_watcher_py
chmod +x watcher.py watcher.sh install.sh
./watcher.sh
```

## Install into your project
```bash
cd /mnt/data/jarvis_watcher_py
./install.sh
```
