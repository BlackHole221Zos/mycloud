import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# пути под себя
DB_PATH = BASE_DIR / "cloud.db"          # или другое имя
VENV_PATH = BASE_DIR / ".venv"
UPLOADS_PATH = BASE_DIR / "uploads"      # если у тебя Config.UPLOAD_FOLDER == 'uploads'
IDEA_PATH = BASE_DIR / ".idea"


def remove_path(path: Path):
    if path.is_file():
        print(f"Удаляю файл: {path}")
        path.unlink()
    elif path.is_dir():
        print(f"Удаляю папку со всем содержимым: {path}")
        shutil.rmtree(path)
    else:
        print(f"Не найдено (пропускаю): {path}")


def remove_pycache(root: Path):
    """Удаление всех __pycache__/_pycache_ в проекте."""
    removed_any = False
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames:
            if name in ("__pycache__", "_pycache_"):
                cache_path = Path(dirpath) / name
                print(f"Удаляю кеш-папку: {cache_path}")
                shutil.rmtree(cache_path, ignore_errors=True)
                removed_any = True
    if not removed_any:
        print("Кеш-папки __pycache__ / _pycache_ не найдены (или уже удалены).")


def main():
    print("Этот скрипт удалит локальные артефакты перед деплоем:")
    print(f"  БД:        {DB_PATH}")
    print(f"  .venv:     {VENV_PATH}")
    print(f"  uploads:   {UPLOADS_PATH}")
    print(f"  .idea:     {IDEA_PATH}")
    print(f"  __pycache__ / _pycache_ во всём проекте, начиная с: {BASE_DIR}")
    confirm = input("НАПИШИТЕ 'YES', чтобы подтвердить удаление: ")

    if confirm != "YES":
        print("Отмена.")
        return

    remove_path(DB_PATH)
    remove_path(VENV_PATH)
    remove_path(UPLOADS_PATH)
    remove_path(IDEA_PATH)
    remove_pycache(BASE_DIR)

    print("Готово.")

if __name__ == "__main__":
    main()
