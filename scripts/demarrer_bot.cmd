@echo off
rem Lance le bot PokeVeille et le relance automatiquement s'il s'arrete (coupure reseau, erreur...).
rem Journal : data\bot.log. Pour arreter : Gestionnaire des taches > python.exe, ou fermer la session Windows.
cd /d "%~dp0.."
:boucle
echo [%date% %time%] Demarrage du bot >> "data\bot.log"
".venv\Scripts\python.exe" -m pokebot bot >> "data\bot.log" 2>&1
rem Code 3 : un bot tourne deja sur ce PC, on ne relance pas.
if %errorlevel%==3 goto fin
echo [%date% %time%] Bot arrete (code %errorlevel%), relance dans 60 s >> "data\bot.log"
timeout /t 60 /nobreak >nul
goto boucle
:fin
