# Windows Portable Release

This project can be distributed as a portable Windows folder.

Expected release contents:

- `learnpress-dl.exe`
- `yt-dlp.exe`
- `ffmpeg.exe`
- `ffprobe.exe`
- `.env.example`
- `run.bat`
- `retry-failed.bat`

## Build On Windows

1. Install Python 3.10+ on Windows.
2. Place `yt-dlp.exe`, `ffmpeg.exe`, and `ffprobe.exe` in the repository root.
3. Run:

```powershell
cd packaging\windows
.\build-portable.ps1
```

The portable release folder will be created at:

```text
dist\learnpress-dl-windows\
```

## Run On Windows

Single normal run:

```bat
run.bat C:\path\to\cookies.txt C:\path\to\output
```

Retry failed lessons only:

```bat
retry-failed.bat C:\path\to\cookies.txt C:\path\to\output
```

The executable automatically looks for `yt-dlp.exe`, `ffmpeg.exe`, and `ffprobe.exe` next to itself.
