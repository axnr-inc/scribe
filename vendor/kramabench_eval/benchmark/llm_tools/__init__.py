from .gpt_interface import GPTInterface
from .llm_interface import LLMInterface
# SCRIBE patch: skip Ollama import — we only use GPT-5-mini for LLMParaphrase.
try:
    from .ollama_interface import OllamaInterface
except ImportError:
    OllamaInterface = None
