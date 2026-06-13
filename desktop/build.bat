@echo off
REM ----------------------------------------------------------------------
REM build.bat — one-click local Windows build of UnidirectionalOneShot.
REM
REM PREREQS:
REM   • Python 3.11 installed and on PATH (NOT 3.12 or newer — see why
REM     in README_BUILD.txt section "PYTHON VERSION").
REM   • Internet access for pip.
REM
REM RUN FROM:  desktop\
REM OUTPUT:    desktop\dist\UnidirectionalOneShot\UnidirectionalOneShot.exe
REM ----------------------------------------------------------------------

setlocal enableextensions enabledelayedexpansion

REM --- Sanity check Python version ---------------------------------------
for /f "tokens=2 delims= " %%v in ('py -3.11 -V 2^>nul') do set PYVER=%%v
if "%PYVER%"=="" (
    echo.
    echo  Python 3.11 not found.  Install it from python.org and re-run.
    echo  Do NOT use 3.12 or newer ^(pkgutil.ImpImporter removed, our
    echo  setuptools pin needs it^).
    exit /b 1
)
echo  Using Python %PYVER%

REM --- Fresh venv -------------------------------------------------------
if exist .venv (
    echo  Removing previous .venv...
    rmdir /s /q .venv
)
py -3.11 -m venv .venv
call .venv\Scripts\activate.bat

python -m pip install --upgrade pip wheel
pip install -r requirements-desktop.txt

REM --- Re-pin setuptools LAST so nothing pulled a newer one ------------
pip install --upgrade --force-reinstall setuptools==65.5.1

REM --- Clean previous artifacts ----------------------------------------
if exist build dist (
    rmdir /s /q build  2>nul
    rmdir /s /q dist   2>nul
)

REM --- Build ------------------------------------------------------------
pyinstaller UnidirectionalOneShot.spec --noconfirm --clean
if errorlevel 1 (
    echo  PyInstaller build FAILED.
    exit /b 1
)

echo.
echo  ----------------------------------------------------------
echo   Build succeeded.
echo   Run:  dist\UnidirectionalOneShot\UnidirectionalOneShot.exe
echo  ----------------------------------------------------------
echo   Reminder: a green build proves nothing.  The CI boot self-
echo   test (push to GitHub, watch the windows-latest job) is the
echo   only proof the .exe actually launches.
echo  ----------------------------------------------------------

endlocal
