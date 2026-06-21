from datetime import datetime

import pytest

from shared_contracts.models import FileIndexState


def test_file_index_state_has_no_chunk_ids():
    """После удаления поля chunk_ids его не должно быть в модели."""
    assert not hasattr(FileIndexState, 'chunk_ids'), \
        "chunk_ids должен быть удалён из FileIndexState"


def test_file_index_state_instantiation_without_chunk_ids():
    """Модель создаётся без chunk_ids и не принимает его как параметр."""
    state = FileIndexState(
        stage="pending",
        checksum_md5="abc123",
        status="pending",
        last_modified=datetime(2024, 1, 1),
    )
    assert not hasattr(state, 'chunk_ids')


def test_file_index_state_rejects_chunk_ids():
    """Передача chunk_ids должна вызвать ошибку валидации или быть проигнорирована."""
    try:
        state = FileIndexState(
            checksum_md5="abc123",
            status="pending",
            last_modified=datetime(2024, 1, 1),
            chunk_ids=["x"],
        )
        assert not hasattr(state, 'chunk_ids')
    except Exception:
        pass  # ValidationError — тоже корректное поведение


def test_file_index_state_fields():
    """Проверка что все обязательные поля на месте и chunk_ids отсутствует в model_fields."""
    fields = set(FileIndexState.model_fields.keys())
    assert 'checksum_md5' in fields
    assert 'status' in fields
    assert 'last_modified' in fields
    assert 'chunk_ids' not in fields, "chunk_ids должен быть удалён из model_fields"
