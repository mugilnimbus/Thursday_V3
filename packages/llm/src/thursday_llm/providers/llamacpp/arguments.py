"""The command line of `llama-server`, built from the chosen load settings."""

from pathlib import Path

from thursday_llm.config import LoadParameters
from thursday_llm.providers.llamacpp.files import projector_beside

DEFAULT_CONTEXT = 8192


def model_arguments(model: Path, load: LoadParameters) -> list[str]:
    """What decides how much memory the model needs. The server and the fitting tool get the same."""
    args = ["-m", str(model), "-c", str(load.context_length or DEFAULT_CONTEXT)]
    if load.flash_attention is not None:
        args += ["-fa", "on" if load.flash_attention else "off"]
    if load.offload_kv_cache_to_gpu is False:
        args.append("--no-kv-offload")
    if load.eval_batch_size:
        args += ["-b", str(load.eval_batch_size), "-ub", str(load.eval_batch_size)]
    if load.moe_cpu_layers:
        args += ["--n-cpu-moe", str(load.moe_cpu_layers)]
    return args


def server_arguments(
    exe: Path, model: Path, port: int, api_key: str, load: LoadParameters, *, fills_in_order: bool
) -> list[str]:
    """Everything but the placement on the cards, which is worked out separately when they are filled in order."""
    args = [
        str(exe),
        *model_arguments(model, load),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--api-key",
        api_key,
        "--jinja",
    ]
    projector = projector_beside(model)
    if projector is not None:
        args += ["--mmproj", str(projector)]
    # Left unset, llama.cpp fits as many layers on the cards as their free memory allows, split by layer.
    if load.gpu_layers:
        args += ["-ngl", load.gpu_layers]
    if load.gpu_split and not fills_in_order:
        args += ["--tensor-split", load.gpu_split]
    return args
