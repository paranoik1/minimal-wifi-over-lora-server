import os
import hmac
import secrets
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    session,
    redirect,
    jsonify,
)

import sys
from pathlib import Path


BASE_DIR = Path(__file__).parent.parent
sys.path.append(str(BASE_DIR))

from database import UserRepository, get_db
from config import FLASK_SECRET_KEY, MASTER_KEY_ACCESS


app = Flask(
    __name__,
    template_folder=BASE_DIR / "web" / "templates",
    static_folder=BASE_DIR / "web" / "static"
)

app.secret_key = FLASK_SECRET_KEY


app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=(
        os.getenv("FLASK_HTTPS", "false").lower() == "true"
    ),
)

CSRF_TOKEN_HEADER_NAME = "X-CSRF-Token"



def generate_key() -> str:
    """
    Генерирует 256-битный секретный ключ.
    Возвращает 64 hex-символа.
    """
    return secrets.token_hex(32)


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            if request.path.startswith("/api/"):
                return jsonify(
                    error="Требуется авторизация"
                ), 401

            return redirect("/")
        return func(*args, **kwargs)

    return wrapper


def csrf_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):

        token = request.headers.get(CSRF_TOKEN_HEADER_NAME, "")
        expected = session.get("csrf_token", "")

        if not expected or not hmac.compare_digest(
            token,
            expected
        ):
            return jsonify(
                error="Недействительный CSRF-токен"
            ), 403

        return func(*args, **kwargs)

    return wrapper


@app.route("/", methods=["GET", "POST"])
def home():
    """
    Авторизация администратора.
    """

    if request.method == "GET":
        if session.get("is_admin"):
            return redirect("/users")

        return render_template("index.html")

    input_master_key = request.form.get("master_key")

    if not input_master_key:
        return render_template(
            "index.html",
            error="Введите master key"
        )

    if hmac.compare_digest(
        input_master_key,
        MASTER_KEY_ACCESS
    ):
        session.clear()

        session["is_admin"] = True
        session["csrf_token"] = secrets.token_urlsafe(32)

        return redirect("/users")

    return render_template(
        "index.html",
        error="Неверный master key"
    )


@app.route("/logout", methods=["POST"])
@admin_required
@csrf_required
def logout():
    session.clear()
    return redirect("/")


@app.route("/users")
@admin_required
def users():
    """
    Страница управления пользователями.
    """
    with get_db() as db:
        users = UserRepository(db).get_users()

    return render_template(
        "users.html",
        users=users,
        csrf_token=session["csrf_token"]
    )




@app.route("/api/users", methods=["POST"])
@admin_required
@csrf_required
def create_user():
    """
    Создание пользователя.

    Секретный ключ сохраняется в SQLite
    и возвращается администратору один раз.
    """
    data = request.get_json(silent=True)

    if data is None:
        return jsonify(
            error="Некорректный JSON"
        ), 400

    name = data.get("name")

    if not isinstance(name, str) or not name.strip():
        return jsonify(
            error="Укажите имя пользователя"
        ), 400

    name = name.strip()

    if len(name) > 100:
        return jsonify(
            error="Имя слишком длинное"
        ), 400

    key = generate_key()
    try:
        with get_db() as db:
            user_id = UserRepository(db).create_user(name, key)
    except ValueError as error:
        return jsonify(
            error=str(error)
        ), 409

    return jsonify(
        user={
            "user_id": user_id,
            "name": name
        },
        key=key
    ), 201



@app.route(
    "/api/users/<int:user_id>/regenerate-key",
    methods=["POST"]
)
@admin_required
@csrf_required
def regenerate_key(user_id: int):
    """
    Перегенерация секретного ключа.

    Новый ключ сохраняется в SQLite
    и возвращается администратору один раз.
    """
    key = generate_key()

    with get_db() as db:
        success = UserRepository(db).set_secret_key(user_id, key)

    if not success:
        return jsonify(
            error="Пользователь не найден"
        ), 404

    return jsonify(key=key)


@app.route(
    "/api/users/<int:user_id>",
    methods=["DELETE"]
)
@admin_required
@csrf_required
def delete_user(user_id: int):
    """
    Удаление пользователя.
    """
    with get_db() as db:
        success = UserRepository(db).delete_user(user_id)

    if not success:
        return jsonify(
            error="Пользователь не найден"
        ), 404

    return jsonify(success=True)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5678,
        debug=False,
        use_reloader=False
    )
