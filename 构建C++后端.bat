@echo off
cd /d "%~dp0"
python native\setup_native.py build_ext --inplace --force
if errorlevel 1 (
    pause
    exit /b 1
)
python tools\native_backend_doctor.py --verify --benchmark
pause
