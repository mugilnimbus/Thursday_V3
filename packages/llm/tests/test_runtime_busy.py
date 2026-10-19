"""A change to the model and a model call never overlap."""

import asyncio

import pytest
from thursday_llm import management
from thursday_llm.config import ProviderKind
from thursday_llm.overrides import InferenceOverrides, LlmOverrides, LoadOverrides
from thursday_llm.providers import LoadedModel
from thursday_llm.runtime import LlmRuntime, ModelBusy, config_from_env


class FakeProvider:
    """Stands in for a provider that owns a model server: closing or unloading it stops the server."""

    supports_lifecycle = True

    def __init__(self, slow_close: asyncio.Event | None = None) -> None:
        self.closed = self.unloaded = self.reloaded = False
        self._slow_close = slow_close

    async def ensure_loaded(self) -> LoadedModel:
        return LoadedModel("m", None, 8192, adopted=True)

    async def reload(self, load: object = None) -> LoadedModel:
        self.reloaded = True
        return LoadedModel("m", None, 8192, adopted=False)

    async def unload(self) -> None:
        self.unloaded = True

    async def reachable(self) -> bool:
        return True

    async def aclose(self) -> None:
        if self._slow_close is not None:
            await self._slow_close.wait()
        self.closed = True


class Keys:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str:
        return self.values.get(name, "")

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch) -> list[FakeProvider]:
    """Every provider the runtime builds, in order. The first is the one a running call would be using."""
    made: list[FakeProvider] = []

    def make(_config: object) -> FakeProvider:
        made.append(FakeProvider())
        return made[-1]

    monkeypatch.setattr("thursday_llm.runtime.make_provider", make)
    monkeypatch.setattr("thursday_llm.runtime.make_chat_model", lambda *a, **k: object())
    return made


def runtime(saved: dict, keys: Keys | None = None) -> LlmRuntime:
    return LlmRuntime(
        lambda: config_from_env(ProviderKind.OPENAI_COMPATIBLE, "http://127.0.0.1:9", "m", None, 60.0),
        lambda: saved or None,
        saved.update,
        keys=keys,
        agent="main",
    )


async def test_saving_a_setting_while_the_model_answers_is_refused_and_changes_nothing(built) -> None:
    saved: dict = {}
    rt = runtime(saved)
    in_use = built[0]
    async with rt.use():
        with pytest.raises(ModelBusy, match="in use right now"):
            await rt.update(LlmOverrides(inference=InferenceOverrides(temperature=0.5)))
        assert not in_use.closed, "the provider the call is using is left alone"
        assert rt.provider is in_use and saved == {}, "and nothing was saved"
    await rt.update(LlmOverrides(inference=InferenceOverrides(temperature=0.5)))
    assert in_use.closed and rt.provider is built[1], "once the call has ended the same change goes through"
    assert saved["inference"]["temperature"] == 0.5


async def test_a_key_an_unload_and_a_reload_are_refused_while_the_model_answers(built) -> None:
    keys = Keys()
    rt = runtime({}, keys)
    async with rt.use():
        with pytest.raises(ModelBusy):
            await rt.set_key("secret")
        with pytest.raises(ModelBusy):
            await rt.unload_model()
        with pytest.raises(ModelBusy):
            await rt.reload_model(LoadOverrides(context_length=16384))
        with pytest.raises(ModelBusy):
            await management.model_action(rt, "unload")
        with pytest.raises(ModelBusy):
            await management.model_action(rt, "reload")
    assert keys.values == {} and rt.config.load.context_length is None
    assert not (built[0].unloaded or built[0].reloaded or built[0].closed)


async def test_unload_and_reload_work_when_nothing_is_running(built) -> None:
    rt = runtime({})
    await management.model_action(rt, "unload")
    assert built[0].unloaded
    await management.model_action(rt, "reload", LoadOverrides(context_length=16384))
    assert rt.config.load.context_length == 16384 and built[-1].reloaded, "the new setting is saved, then it loads"
    assert rt.idle_seconds < 5, "reloading counts as a use"
    async with rt.use():  # the runtime is free again afterwards
        pass


async def test_a_call_that_starts_during_a_change_waits_for_the_change(monkeypatch: pytest.MonkeyPatch) -> None:
    closing = asyncio.Event()
    made: list[FakeProvider] = []

    def make(_config: object) -> FakeProvider:
        made.append(FakeProvider(slow_close=closing if not made else None))
        return made[-1]

    monkeypatch.setattr("thursday_llm.runtime.make_provider", make)
    monkeypatch.setattr("thursday_llm.runtime.make_chat_model", lambda *a, **k: object())
    rt = runtime({})
    order: list[str] = []

    async def change() -> None:
        await rt.update(LlmOverrides(inference=InferenceOverrides(temperature=0.2)))
        order.append("changed")

    async def call() -> None:
        async with rt.use():
            order.append(f"call on provider {made.index(rt.provider)}")  # type: ignore[arg-type]

    changing = asyncio.create_task(change())
    await asyncio.sleep(0)  # the change is now stopping the old provider
    calling = asyncio.create_task(call())
    await asyncio.sleep(0.05)
    assert order == [], "the call has not started: the old provider is still being stopped"
    closing.set()
    await asyncio.gather(changing, calling)
    assert order == ["changed", "call on provider 1"], "it runs on the new provider, after the change"
