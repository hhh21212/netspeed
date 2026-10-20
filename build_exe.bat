@echo off
cd /d "%~dp0"
python -m pip install pyinstaller
python -m PyInstaller --onefile --noconsole --name NetSpeed --hidden-import pystray._win32 netspeed.py
echo.
echo 打包完成：dist\NetSpeed.exe
pause
