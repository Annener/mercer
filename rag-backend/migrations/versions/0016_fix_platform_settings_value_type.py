"""fix platform_settings.value: JSONB -> TEXT, strip JSON quoting from existing rows

Revision ID: 0016_fix_platform_settings_value_type
Revises: 0015_fix_messages_pipeline_id_type
Create Date: 2026-06-08

Почему: колонка value была создана как JSONB, из-за чего строковые значения
(например URL) хранились с JSON-кавычками: "\"http://...\"". При чтении через
asyncpg JSONB-строка возвращалась как Python str с кавычками вместо чистого str,
что ломало httpx при передаче URL.

Что делаем:
1. Конвертируем существующие данные: каждое значение достаём через json.loads(),
   после чего приводим к строке согласно value_type.
2. Меняем тип колонки с JSONB на TEXT — значения теперь хранятся как plain text.

Данные не теряются: bool->"true"/"false", int->"123", str->чистая строка.

Downgrade: возвращаем TEXT->JSONB и обратно оборачиваем значения в json.dumps().
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0016_fix_platform_settings_value_type"
down_revision = "0015_fix_messages_pipeline_id_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Читаем все строки пока колонка ещё JSONB
    rows = conn.execute(
        sa.text("SELECT key, value, value_type FROM platform_settings")
    ).fetchall()

    # 2. Конвертируем каждое значение в plain-text строку
    updates: list[tuple[str, str]] = []
    for key, raw_value, value_type in rows:
        # asyncpg/psycopg2 уже десериализует JSONB в Python-объект:
        # str -> str (но с лишними кавычками если было JSON-строкой),
        # int -> int, bool -> bool.
        # Однако на момент миграции через alembic движок может вернуть
        # raw JSON-текст, поэтому обрабатываем оба случая.
        if isinstance(raw_value, str):
            try:
                native = json.loads(raw_value)
            except (json.JSONDecodeError, TypeError):
                native = raw_value  # уже чистая строка
        else:
            native = raw_value  # int, bool, None — уже Python-объект

        if value_type == "bool":
            text_value = "true" if native else "false"
        elif value_type == "int":
            text_value = str(int(native))
        elif value_type == "float":
            text_value = str(float(native))
        else:  # str и любой нераспознанный тип
            text_value = str(native) if native is not None else ""

        updates.append((key, text_value))

    # 3. Меняем тип колонки JSONB -> TEXT
    # USING приводит JSONB->TEXT через встроенный каст PostgreSQL (убирает JSON-обёртку)
    op.alter_column(
        "platform_settings",
        "value",
        type_=sa.Text(),
        existing_type=JSONB(),
        postgresql_using="value::text",
        nullable=False,
    )

    # 4. Обновляем строки уже в TEXT-колонке: убираем остаточные JSON-кавычки
    # (USING value::text для строк даст '"http://..."' — с кавычками, исправляем)
    for key, text_value in updates:
        conn.execute(
            sa.text(
                "UPDATE platform_settings SET value = :val WHERE key = :key"
            ),
            {"val": text_value, "key": key},
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Читаем plain-text значения
    rows = conn.execute(
        sa.text("SELECT key, value, value_type FROM platform_settings")
    ).fetchall()

    # Меняем тип обратно TEXT -> JSONB
    op.alter_column(
        "platform_settings",
        "value",
        type_=JSONB(),
        existing_type=sa.Text(),
        postgresql_using="value::jsonb",
        nullable=False,
    )

    # Оборачиваем значения обратно в JSON
    for key, raw_value, value_type in rows:
        if value_type == "bool":
            json_value = json.dumps(raw_value.lower() == "true")
        elif value_type == "int":
            try:
                json_value = json.dumps(int(raw_value))
            except ValueError:
                json_value = json.dumps(raw_value)
        elif value_type == "float":
            try:
                json_value = json.dumps(float(raw_value))
            except ValueError:
                json_value = json.dumps(raw_value)
        else:
            json_value = json.dumps(raw_value)

        conn.execute(
            sa.text(
                "UPDATE platform_settings SET value = :val::jsonb WHERE key = :key"
            ),
            {"val": json_value, "key": key},
        )
