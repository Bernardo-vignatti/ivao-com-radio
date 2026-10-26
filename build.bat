@echo off
rem Gera dist\COM Radio.exe. Rode de novo depois de mudar qualquer arquivo.
cd /d "%~dp0"

py -m PyInstaller --noconfirm --onefile --windowed --name "COM Radio" ^
  --icon assets\icon.ico ^
  --add-data "app\static;static" ^
  --add-data "assets\icon.ico;assets" ^
  --collect-all SimConnect ^
  app\gui.py
if errorlevel 1 (
  echo.
  echo A geracao falhou. Veja as mensagens acima.
  pause
  exit /b 1
)

rem o config fica ao lado do .exe, editavel. Nao sobrescreve o que ja existe
if not exist "dist\config.json" copy config.json "dist\config.json" >nul

echo.
echo Pronto: dist\COM Radio.exe
pause
