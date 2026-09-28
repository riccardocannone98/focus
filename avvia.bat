@echo off
rem Focus Guard - avvio con doppio click su Windows.
rem Al primo avvio crea .venv, installa le dipendenze e scarica il modello.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" goto activate
echo Primo avvio: creo l'ambiente virtuale .venv...
where py >nul 2>nul
if %errorlevel%==0 (py -3 -m venv .venv) else (python -m venv .venv)
if errorlevel 1 goto error_python
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto error_install
goto model

:activate
call ".venv\Scripts\activate.bat"

:model
if not exist "models\face_landmarker.task" python scripts\download_model.py
if errorlevel 1 goto error_model

python -m focus_guard %*
if errorlevel 1 goto error_run
goto end

:error_python
echo ERRORE: Python non trovato. Installa Python 3.10-3.12 da python.org (spunta "Add to PATH").
goto wait
:error_install
echo ERRORE: installazione delle dipendenze non riuscita.
goto wait
:error_model
echo ERRORE: download del modello non riuscito.
goto wait
:error_run
echo ERRORE: Focus Guard si e' chiuso con un errore (vedi sopra).
:wait
pause
:end
endlocal
