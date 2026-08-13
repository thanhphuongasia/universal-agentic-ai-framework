"""Tests for the prompt lifecycle store (ryuu_prompts.store) + config round-trip."""

from __future__ import annotations

import pytest

from ryuu_prompts import (
    InMemoryPromptStore,
    IPromptStore,
    PromptConfig,
    PromptStatus,
    PromptStoreError,
    PromptTemplate,
    PromptVersion,
    PromptVersionNotFoundError,
)


def _config(version: str = "v1") -> PromptConfig:
    return PromptConfig(
        version=version,
        description="test",
        model="gpt-4o-mini",
        temperature=0.1,
        max_tokens=512,
        prompts={"analyze": PromptTemplate(system="You are {role}.", user="{query}")},
    )


def _version(suite: str, ver: str, *, created_at: float = 0.0) -> PromptVersion:
    return PromptVersion(
        id=f"{suite}-{ver}",
        suite_id=suite,
        version=ver,
        config=_config(ver),
        created_at=created_at,
    )


# --- PromptConfig serialization round-trip --------------------------------


def test_config_to_dict_from_dict_roundtrip():
    cfg = _config("v2")
    again = PromptConfig.from_dict(cfg.to_dict())
    assert again == cfg


def test_config_from_dict_applies_defaults():
    cfg = PromptConfig.from_dict({"prompts": {}})
    assert cfg.model == "gpt-4o-mini"
    assert cfg.temperature == 0.1
    assert cfg.max_tokens == 1024


# --- InMemoryPromptStore conforms to the Protocol -------------------------


def test_inmemory_store_is_iprompt_store():
    assert isinstance(InMemoryPromptStore(), IPromptStore)


# --- save / get / list ----------------------------------------------------


@pytest.mark.asyncio
async def test_save_and_get():
    store = InMemoryPromptStore()
    v = _version("suite-a", "v1")
    await store.save(v)
    assert await store.get("suite-a", "v1") is v
    assert await store.get("suite-a", "missing") is None


@pytest.mark.asyncio
async def test_list_versions_sorted_and_scoped():
    store = InMemoryPromptStore()
    await store.save(_version("a", "v2", created_at=2.0))
    await store.save(_version("a", "v1", created_at=1.0))
    await store.save(_version("b", "v9", created_at=9.0))

    versions = await store.list_versions("a")
    assert [v.version for v in versions] == ["v1", "v2"]  # oldest first
    assert all(v.suite_id == "a" for v in versions)


# --- lifecycle: status ----------------------------------------------------


@pytest.mark.asyncio
async def test_set_status_transitions():
    store = InMemoryPromptStore()
    await store.save(_version("a", "v1"))
    updated = await store.set_status("a", "v1", PromptStatus.STAGING)
    assert updated.status is PromptStatus.STAGING
    assert (await store.get("a", "v1")).status is PromptStatus.STAGING


@pytest.mark.asyncio
async def test_set_status_missing_raises():
    store = InMemoryPromptStore()
    with pytest.raises(PromptVersionNotFoundError):
        await store.set_status("a", "nope", PromptStatus.STAGING)


# --- lifecycle: promote + active pointer ----------------------------------


@pytest.mark.asyncio
async def test_promote_sets_active_and_stamps():
    store = InMemoryPromptStore()
    await store.save(_version("a", "v1"))
    assert await store.get_active("a") is None

    promoted = await store.promote("a", "v1", by="alice")
    assert promoted.promoted_by == "alice"
    assert promoted.promoted_at is not None and promoted.promoted_at > 0
    assert (await store.get_active("a")).version == "v1"


@pytest.mark.asyncio
async def test_promote_moves_active_pointer():
    store = InMemoryPromptStore()
    await store.save(_version("a", "v1"))
    await store.save(_version("a", "v2"))
    await store.promote("a", "v1", by="alice")
    await store.promote("a", "v2", by="bob")
    assert (await store.get_active("a")).version == "v2"


@pytest.mark.asyncio
async def test_promote_archived_is_blocked():
    store = InMemoryPromptStore()
    await store.save(_version("a", "v1"))
    await store.set_status("a", "v1", PromptStatus.ARCHIVED)
    with pytest.raises(PromptStoreError):
        await store.promote("a", "v1", by="alice")


@pytest.mark.asyncio
async def test_promote_missing_raises():
    store = InMemoryPromptStore()
    with pytest.raises(PromptVersionNotFoundError):
        await store.promote("a", "nope", by="alice")


# --- 'production' is derived, not a status --------------------------------


def test_no_production_status():
    assert "production" not in {s.value for s in PromptStatus}
