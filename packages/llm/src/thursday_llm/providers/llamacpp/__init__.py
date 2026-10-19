"""The built-in llama.cpp: Thursday starts one `llama-server` process per agent and stops it on unload.

- `provider`: the process and the model it serves (the only part other code uses);
- `files`: where llama.cpp and the model files are on disk;
- `arguments`: the server's command line;
- `placement`: which graphics card gets how much of the model;
- `hearing`: a recording written down by the model itself.
"""

from thursday_llm.providers.llamacpp.provider import LlamaCppProvider

__all__ = ["LlamaCppProvider"]
