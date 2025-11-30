@echo off
setlocal enabledelayedexpansion

set "output=combined_python.txt"

:: Очищаем или создаём выходной файл
type nul > "%output%"

:: Проходим по всем .py файлам рекурсивно
for /r %%f in (*.py) do (
    echo. >> "%output%"
    echo # File: %%f >> "%output%"
    type "%%f" >> "%output%"
    echo. >> "%output%"
)

echo Сборка завершена. Результат в %output%
pause