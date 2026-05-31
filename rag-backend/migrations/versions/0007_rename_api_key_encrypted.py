"""rename api_key_encrypted to encrypted_api_key in generation_models and embedding_models

Revision ID: 0007_rename_api_key_encrypted
Revises: 0006_add_uuid_pk_to_models_vaults
Create Date: 2026-06-01
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0007_rename_api_key_encrypted"
down_revision = "0006_add_uuid_pk_to_models_vaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("generation_models", "api_key_encrypted", new_column_name="encrypted_api_key")
    op.alter_column("embedding_models", "api_key_encrypted", new_column_name="encrypted_api_key")


def downgrade() -> None:
    op.alter_column("generation_models", "encrypted_api_key", new_column_name="api_key_encrypted")
    op.alter_column("embedding_models", "encrypted_api_key", new_column_name="api_key_encrypted")
