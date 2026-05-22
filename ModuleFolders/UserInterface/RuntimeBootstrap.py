from __future__ import annotations

import hashlib
import importlib
import os
import threading
import time
from collections.abc import Callable


_RUNTIME_BOOTSTRAPPED = False
_RUNTIME_BOOTSTRAP_LOCK = threading.RLock()
_PREWARM_LOCK = threading.RLock()
_PREWARM_THREAD: threading.Thread | None = None
_PREWARM_RUNNING = False
_PREWARM_COMPLETED = False

_TEXT_TASK_PREWARM_MODULES = (
    "ModuleFolders.Base.EventManager",
    "ModuleFolders.Base.PluginManager",
    "ModuleFolders.Infrastructure.Cache.CacheItem",
    "ModuleFolders.Infrastructure.Cache.CacheFile",
    "ModuleFolders.Infrastructure.Cache.CacheProject",
    "ModuleFolders.Infrastructure.Cache.CacheManager",
    "ModuleFolders.Infrastructure.TaskConfig.TaskConfig",
    "ModuleFolders.Infrastructure.RequestLimiter.RequestLimiter",
    "ModuleFolders.Infrastructure.LLMRequester.LLMRequester",
    "ModuleFolders.Infrastructure.LLMRequester.AsyncSignalHub",
    "ModuleFolders.Infrastructure.LLMRequester.ErrorClassifier",
    "ModuleFolders.Infrastructure.LLMRequester.AsyncOpenaiRequester",
    "ModuleFolders.Infrastructure.LLMRequester.AsyncLLMRequester",
    "ModuleFolders.Domain.ResponseExtractor.ResponseExtractor",
    "ModuleFolders.Domain.ResponseChecker.ResponseChecker",
    "ModuleFolders.Domain.TextProcessor.TextProcessor",
    "ModuleFolders.Domain.TextProcessor.PolishTextProcessor",
    "ModuleFolders.Domain.PromptBuilder.PromptBuilderEnum",
    "ModuleFolders.Domain.PromptBuilder.PromptBuilder",
    "ModuleFolders.Domain.PromptBuilder.PromptBuilderLocal",
    "ModuleFolders.Domain.PromptBuilder.PromptBuilderSakura",
    "ModuleFolders.Domain.PromptBuilder.PromptBuilderPolishing",
    "ModuleFolders.Service.TaskExecutor.TranslatorUtil",
    "ModuleFolders.Service.TaskExecutor.TranslatorTask",
    "ModuleFolders.Service.TaskExecutor.PolisherTask",
    "ModuleFolders.Service.TaskExecutor.TaskExecutor",
)


def ensure_runtime_bootstrap(*, suppress_output: bool = False):
    global _RUNTIME_BOOTSTRAPPED

    with _RUNTIME_BOOTSTRAP_LOCK:
        if _RUNTIME_BOOTSTRAPPED:
            return

        from ModuleFolders.Infrastructure.Tokener.TiktokenLoader import initialize_tiktoken
        import ModuleFolders.Infrastructure.Tokener.TiktokenLoader as TiktokenLoaderModule
        import ModuleFolders.Domain.FileReader.ReaderUtil as ReaderUtilModule

        TiktokenLoaderModule._SUPPRESS_OUTPUT = True
        ReaderUtilModule._SUPPRESS_OUTPUT = True

        try:
            if suppress_output:
                import contextlib
                import io

                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    initialize_tiktoken()
            else:
                initialize_tiktoken()
        except Exception:
            pass

        _RUNTIME_BOOTSTRAPPED = True


def _should_continue(callback: Callable[[], bool] | None) -> bool:
    if callback is None:
        return True
    try:
        return bool(callback())
    except Exception:
        return False


def _sleep_interval(seconds: float, callback: Callable[[], bool] | None) -> bool:
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        if not _should_continue(callback):
            return False
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    return _should_continue(callback)


def _prewarm_tiktoken_encoding() -> None:
    from ModuleFolders.Infrastructure.Tokener.TiktokenLoader import get_tiktoken_cache_dir

    cache_dir = get_tiktoken_cache_dir()
    if not cache_dir:
        return

    o200k_url = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
    cache_key = hashlib.sha1(o200k_url.encode()).hexdigest()
    if not os.path.isfile(os.path.join(cache_dir, cache_key)):
        return

    from ModuleFolders.Infrastructure.Tokener.Tokener import Tokener

    Tokener().num_tokens_from_str("warmup")


def _background_prewarm_worker(
    *,
    delay: float,
    interval: float,
    should_continue: Callable[[], bool] | None,
) -> None:
    completed = False
    try:
        if not _sleep_interval(delay, should_continue):
            return

        try:
            ensure_runtime_bootstrap(suppress_output=True)
        except Exception:
            return

        if not _sleep_interval(interval, should_continue):
            return

        for module_name in _TEXT_TASK_PREWARM_MODULES:
            if not _sleep_interval(interval, should_continue):
                return
            try:
                importlib.import_module(module_name)
            except Exception:
                continue

        if not _sleep_interval(interval, should_continue):
            return

        try:
            _prewarm_tiktoken_encoding()
        except Exception:
            pass
        completed = True
    finally:
        _finish_background_prewarm(completed)


def _finish_background_prewarm(completed: bool) -> None:
    global _PREWARM_RUNNING, _PREWARM_COMPLETED

    with _PREWARM_LOCK:
        _PREWARM_RUNNING = False
        if completed:
            _PREWARM_COMPLETED = True


def start_background_prewarm(
    *,
    enabled: bool = True,
    delay: float = 3.0,
    interval: float = 0.35,
    should_continue: Callable[[], bool] | None = None,
) -> bool:
    """Start a slow, best-effort prewarm for regular text translation components."""
    global _PREWARM_RUNNING, _PREWARM_THREAD

    if not enabled:
        return False

    with _PREWARM_LOCK:
        if _PREWARM_RUNNING or _PREWARM_COMPLETED:
            return True

        _PREWARM_RUNNING = True
        _PREWARM_THREAD = threading.Thread(
            target=_background_prewarm_worker,
            kwargs={
                "delay": delay,
                "interval": interval,
                "should_continue": should_continue,
            },
            name="ainiee-background-prewarm",
            daemon=True,
        )
        _PREWARM_THREAD.start()
        return True
