"""A stored key goes only to the address it was typed for."""

import dataclasses
from typing import Any

from pydantic import SecretStr
from thursday_llm.config import ProviderKind
from thursday_llm.overrides import LlmOverrides
from thursday_llm.runtime import LlmRuntime, config_from_env


class Keys:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, name: str) -> str:
        return self.values.get(name, "")

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def runtime(saved: dict[str, Any], keys: Keys, env_key: str = "") -> LlmRuntime:
    def base():
        config = config_from_env(ProviderKind.OPENAI_COMPATIBLE, "https://api.one.example/v1", "m", None, 60.0)
        return dataclasses.replace(config, api_key=SecretStr(env_key))

    return LlmRuntime(base, lambda: saved or None, saved.update, keys=keys, agent="main")


async def test_a_changed_address_does_not_get_the_key_until_it_is_typed_again() -> None:
    saved: dict[str, Any] = {}
    rt = runtime(saved, Keys())
    await rt.set_key("secret-one")
    assert rt.describe()["api_key_set"] and not rt.describe()["api_key_held_back"]

    await rt.update(LlmOverrides(base_url="https://api.other.example/v1"))
    described = rt.describe()
    assert not described["api_key_set"] and described["api_key_held_back"]
    assert rt.config.api_key.get_secret_value() == "", "nothing is sent to the new address"

    await rt.update(LlmOverrides(base_url="https://api.one.example/v1/"))
    assert rt.config.api_key.get_secret_value() == "secret-one", "back at its own address the key works again"

    await rt.update(LlmOverrides(base_url="https://api.other.example/v1"))
    await rt.set_key("secret-two")
    assert rt.config.api_key.get_secret_value() == "secret-two" and not rt.describe()["api_key_held_back"]
    await rt.provider.aclose()


async def test_the_rule_holds_across_a_restart_and_a_client_cannot_move_the_address() -> None:
    saved: dict[str, Any] = {}
    keys = Keys()
    rt = runtime(saved, keys)
    await rt.set_key("secret-one")
    await rt.update(LlmOverrides.model_validate({"key_address": {"openai_compatible": "https://evil.example"}}))
    await rt.update(LlmOverrides(base_url="https://evil.example"))
    assert rt.config.api_key.get_secret_value() == "", "the noted address is the agent's own record"
    await rt.provider.aclose()

    again = runtime(saved, keys)
    assert again.describe()["api_key_held_back"] and again.config.api_key.get_secret_value() == ""
    await again.provider.aclose()


async def test_a_key_stored_before_addresses_were_noted_belongs_to_the_address_in_use() -> None:
    saved: dict[str, Any] = {}
    rt = runtime(saved, Keys({"main-llm-openai_compatible": "old-secret"}))
    assert rt.config.api_key.get_secret_value() == "old-secret"
    await rt.update(LlmOverrides(base_url="https://api.other.example/v1"))
    assert rt.config.api_key.get_secret_value() == "" and rt.describe()["api_key_held_back"]
    await rt.provider.aclose()


async def test_the_env_key_goes_only_to_the_env_address() -> None:
    rt = runtime({}, Keys(), env_key="env-secret")
    assert rt.config.api_key.get_secret_value() == "env-secret"
    await rt.update(LlmOverrides(base_url="https://api.other.example/v1"))
    assert rt.config.api_key.get_secret_value() == ""
    await rt.provider.aclose()
