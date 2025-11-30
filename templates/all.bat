@echo off
setlocal enabledelayedexpansion

set "output=combined.txt"

:: Очищаем или создаём выходной файл
type nul > "%output%"

:: Проходим по всем .html файлам рекурсивно
for /r %%f in (*.html) do (
    echo. >> "%output%"
    echo ^<!-- File: %%f --^> >> "%output%"
    type "%%f" >> "%output%"
    echo. >> "%output%"
)

echo Сборка завершена. Результат в %output%
pause