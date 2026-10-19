# Focus Timer Widget

Windows desktop card built with PySide6. High-DPI vector rendering, draggable and lockable position, saved settings, and console-free logon startup.

Configurable focus, short and long breaks; persistent daily totals and history. Default: 90/15/30 minutes, long break every 3 sessions. Restart restores the timer paused.

## Install

Windows 10/11, Python 3.11+ (tested with Python 3.14). Download or clone this repository, then run in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

For an explicit interpreter: `-Python "C:\path\to\python.exe"`.
The installer installs requirements into that interpreter and registers `GurOS Focus Timer` for your Windows account. It waits 20 seconds at logon, allows battery operation and retries failed exits. Run only one copy.

## Use

Right-click for settings, size, position lock and Quit. Local settings/history/cache live in `state/` and are never included in Git. Startup failures are recorded in bounded `state/crash.log` files. Quitting normally stops the widget until the next launch/logon.

To remove autostart:
```powershell
Unregister-ScheduledTask -TaskName 'GurOS Focus Timer' -Confirm:$false
```

## Tests

```powershell
python -m unittest test_focus -q
```

Automated tests do not prove a real Windows reboot, a full focus session or all third-party playback/network behavior. No credentials, personal runtime state, screenshots or private history are distributed.
