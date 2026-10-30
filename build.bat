@echo off
rem Gera o instalador dist\COM-Radio-Setup-<versao>.exe.
rem Rode de novo depois de mudar qualquer arquivo.
cd /d "%~dp0"

rem uma pasta em vez de arquivo unico: abre mais rapido, o antivirus
rem desconfia menos e o instalador empacota tudo de uma vez
py -m PyInstaller --noconfirm --onedir --windowed --name "COM Radio" ^
  --icon assets\icon.ico ^
  --add-data "app\static;static" ^
  --add-data "app\desktop;desktop" ^
  --add-data "assets\icon.ico;assets" ^
  --add-data "config.json;." ^
  --hidden-import pystray._win32 ^
  --collect-all SimConnect ^
  app\gui.py
if errorlevel 1 goto falhou

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo.
  echo O Inno Setup nao esta instalado. Instale com:
  echo   winget install JRSoftware.InnoSetup
  pause
  exit /b 1
)
"%ISCC%" /Q installer.iss
if errorlevel 1 goto falhou

echo.
echo Pronto: o instalador esta em dist\
pause
exit /b 0

:falhou
echo.
echo A geracao falhou. Veja as mensagens acima.
pause
exit /b 1
