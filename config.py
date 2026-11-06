import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

DB_PATH = Path(__file__).parent / 'users.db'

# Нужен для шифровании session объекта в куках
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY")
MASTER_KEY_ACCESS = os.getenv("FLASK_MASTER_KEY_ACCESS")

assert FLASK_SECRET_KEY, "В .env не установлен FLASK_SECRET_KEY"
assert MASTER_KEY_ACCESS, "В .env не установлен FLASK_MASTER_KEY_ACCESS"
