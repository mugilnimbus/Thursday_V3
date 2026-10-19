"""What Settings can ask about an agent's model: the same for every agent.

No HTTP here. Each agent's own API calls these and turns `ProviderError`, `UnknownAction` and `ModelBusy` (a
change asked for while the model is in use) into its answers.
"""

import dataclasses
from typing import Any

from thursday_llm.overrides import LoadOverrides
from thursday_llm.providers import ProviderError
from thursday_llm.runtime import LlmRuntime


class UnknownAction(Exception):
    """Not one of load, reload, unload."""


async def settings(llm: LlmRuntime) -> dict[str, Any]:
    return {**llm.describe(), "reachable": await llm.provider.reachable()}


async def available_models(llm: LlmRuntime) -> dict[str, Any]:
    """The models this provider offers, for the model list in Settings. A problem is reported, not raised."""
    try:
        found = await llm.provider.list_models()
    except ProviderError as exc:
        return {"models": [], "error": str(exc)}
    except Exception as exc:
        return {"models": [], "error": f"Could not list models ({type(exc).__name__})."}
    return {"models": [dataclasses.asdict(m) for m in found], "error": None}


async def model_action(llm: LlmRuntime, action: str, load: LoadOverrides | None = None) -> dict[str, Any]:
    """Load, reload (with new load settings, when given) or unload the model, and say how things stand after."""
    if action == "load":
        async with llm.use():  # loading by hand counts as a use: the idle time starts over
            await llm.provider.ensure_loaded()
    elif action == "reload":
        await llm.reload_model(load)
    elif action == "unload":
        await llm.unload_model()
    else:
        raise UnknownAction(action)
    return llm.describe()
