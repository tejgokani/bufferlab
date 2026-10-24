@echo off
rem BufferLab launcher (Windows). Finds Python >= 3.11, keeps <repo>\.venv current, starts BufferLab.
setlocal enabledelayedexpansion
set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "VENV=%ROOT%\.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "NEED=1"
if exist "%VPY%" if exist "%VENV%\pyproject.stamp" (
  fc /b "%ROOT%\pyproject.toml" "%VENV%\pyproject.stamp" >nul 2>&1 && (
    "%VPY%" -c "import bufferlab, textual, typer" >nul 2>&1 && set "NEED=0"
  )
)
if "%NEED%"=="1" (
  set "PY="
  if defined BUFFERLAB_PYTHON set "PY=%BUFFERLAB_PYTHON%"
  if not defined PY (
    for %%C in (py python3 python) do (
      if not defined PY (
        %%C -c "import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)" >nul 2>&1 && set "PY=%%C"
      )
    )
  )
  if not defined PY (
    >&2 echo bufferlab: Python 3.11 or newer was not found.
    >&2 echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) or run: winget install Python.Python.3.12
    exit /b 127
  )
  >&2 echo bufferlab: setting up environment in "%VENV%" - first run only...
  if exist "%VENV%" rmdir /s /q "%VENV%"
  !PY! -m venv "%VENV%" || ( >&2 echo bufferlab: could not create virtual environment & exit /b 1 )
  "%VPY%" -m pip install --quiet --disable-pip-version-check -e "%ROOT%" || ( >&2 echo bufferlab: dependency installation failed & exit /b 1 )
  copy /y "%ROOT%\pyproject.toml" "%VENV%\pyproject.stamp" >nul
  >&2 echo bufferlab: ready.
)
"%VPY%" -P -m bufferlab %*
exit /b %ERRORLEVEL%
