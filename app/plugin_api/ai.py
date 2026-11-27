"""The assistant's providers: a plugin family, as the charts, the functions and the operations are.

A provider answers the Assistant panel's conversation through some AI service.
It knows that service's API and nothing of ChartLibre: the tools it is given
are described here (ToolSpec), the calls it asks for come back as ToolCalls,
and the application runs them - on its own thread, with its confirmations and
its Undo - then hands the results back. Claude is the one shipped
(app/ai_providers); another provider is a file beside it, or in the user's
own ai_providers folder, deriving from AIProvider.

A provider is optional: one whose package is not installed says so through
``unavailable`` and the panel explains how to enable it - nothing imports the
service's package before the panel is used.

http_chat: A provider's HTTP, with the standard library only: a JSON request, and a streamed answer read line by line.

Ollama answers a chat as newline-delimited JSON; the OpenAI-style APIs (GitHub Models, a local server that
speaks it) as server-sent events, ``data: {...}`` lines ending with ``data: [DONE]``. Both are read here a
line at a time, so the Stop button is looked at between lines and the text reaches the panel as it comes.
No package to install: urllib, as the data sources already use.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
import http.client
import json
import threading
import urllib.error
import urllib.request


# --- provider -------------------------------------------------------------------------------------
#: The two kinds of work, and so the two models a provider offers: the conversation and the analysis work
#: ("accurate"), and the simple jobs - routing a request, a title, a summary ("fast").
ACCURATE, FAST = "accurate", "fast"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool the assistant may call: its name, what it does, and its input as a JSON schema."""

    name: str
    description: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A call the model asked for: the provider's id for it, the tool and its input."""

    id: str
    name: str
    input: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool gave back, as text, for the call *id*; *is_error* when it failed."""

    id: str
    content: str
    is_error: bool = False


@dataclass(slots=True)
class Turn:
    """One answer of the model: its text, the tool calls it asks for, why it stopped, the tokens it used."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    #: "done", "tools" (run tool_calls and continue), "stopped", "refused", "too_long".
    stop: str = "done"
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class ChatSession:
    """One conversation with a provider: it keeps the history in the service's own form.

    ``send`` runs on a worker thread: it must not touch a Qt object or the project. It streams the text as it
    comes to *on_text* (from that thread) and checks *cancel* between chunks.
    """

    def send(
        self,
        *,
        model: str,
        user_text: str | None = None,
        tool_results: Sequence[ToolResult] = (),
        on_text: Callable[[str], None],
        cancel: threading.Event,
    ) -> Turn:
        """Add the user's message, or the results of the last turn's tool calls, and get the next turn from
        *model* - which may change from one message to the next (the routing), the history staying one."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ProviderOption:
    """A setting of the provider's own, a line in Settings > Assistant: an address, a model's name."""

    key: str
    label: str
    default: str = ""
    tooltip: str = ""


class AIProvider:
    """An AI service the Assistant can talk to. Subclasses set Name and implement the methods below."""

    def option_choices(self, key: str) -> list[str]:
        """The values the setting *key* may take, for a drop-down list in Settings (Ollama's installed models);
        empty: a line to type in."""
        del key
        return []

    #: How the provider is listed in Settings.
    Name: str = ""
    Description: str = ""
    #: The account's key, kept by the system's keychain: the name it is filed under; "" when none is needed.
    KEY_NAME: str = ""
    #: Whether the questions and the data leave the computer: then nothing is sent before the user consents.
    SENDS_DATA: bool = True
    #: Whether unavailable() asks over the network (and so is asked off the GUI thread).
    CHECKS_NETWORK: bool = False
    #: Whether it may only read the project, whatever the permission chosen: too small a model for more.
    READ_ONLY: bool = False
    #: The longest tool result its model can take, in characters; 0: the application's own limit.
    MAX_RESULT: int = 0
    #: A small model: told the tables and columns from the start, or it guesses them.
    SMALL_MODEL: bool = False
    #: Its own settings, shown in Settings > Assistant when it is the provider (kept in user.json).
    OPTIONS: tuple[ProviderOption, ...] = ()

    def __init__(self) -> None:
        #: Settings typed but not saved yet (Settings' Try): read before the saved ones.
        self.overrides: dict[str, str] = {}

    @classmethod
    def option_key(cls, key: str) -> str:
        """Where *key* is kept in user.json: assistant_<provider>_<key>."""
        slug = "".join(c if c.isalnum() else "_" for c in cls.Name.lower()).strip("_")
        return f"assistant_{slug}_{key}"

    def option(self, key: str) -> str:
        """The value of one of OPTIONS: typed in Settings and not saved yet, else saved, else its default."""
        if key in self.overrides:
            return str(self.overrides[key])
        from app.utils.config import get_value

        default = next((spec.default for spec in self.OPTIONS if spec.key == key), "")
        return str(get_value(self.option_key(key), default) or default)

    def unavailable(self) -> str:
        """Why the provider cannot be used here (a package missing...), or "" when it can."""
        return ""

    def check(self, api_key: str) -> str:
        """Try *api_key* with the smallest request the service answers - on a worker thread: "" when it works,
        else why not, in words the user can act on. The default: nothing to try."""
        del api_key
        return ""

    def models(self) -> Mapping[str, str]:
        """The model for each kind of work: {ACCURATE: ..., FAST: ...}."""
        raise NotImplementedError

    def classify(self, text: str, *, api_key: str) -> str:
        """FAST when *text* is a simple request (a direct question, one lookup), else ACCURATE - with the fast
        model, on a worker thread. The default: ACCURATE, always."""
        del text, api_key
        return ACCURATE

    def start(self, *, api_key: str, system: str, tools: Sequence[ToolSpec]) -> ChatSession:
        """A new conversation, with *system* as its instructions and *tools* to call."""
        raise NotImplementedError


# --- http_chat ------------------------------------------------------------------------------------
#: Long enough for a local model's first token on a slow machine; streamed after that, so not a limit on the
#: answer's length.
TIMEOUT = 300


class ProviderHTTPError(RuntimeError):
    """The service answered with an error, or could not be reached - said in words the user can act on."""


def _request(url: str, payload: Mapping[str, Any] | None, headers: Mapping[str, str] | None) -> urllib.request.Request:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET")
    request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    return request


def _error(url: str, error: BaseException) -> ProviderHTTPError:
    if isinstance(error, urllib.error.HTTPError):
        try:
            detail = error.read().decode("utf-8", "replace").strip()
        except OSError:
            detail = ""
        try:
            parsed = json.loads(detail)
            detail = str(parsed.get("error", {}).get("message") if isinstance(parsed.get("error"), dict)
                         else parsed.get("error") or parsed.get("message") or detail)
        except (ValueError, AttributeError):
            pass
        return ProviderHTTPError(f"{url} answered {error.code}: {detail or error.reason}")
    reason = getattr(error, "reason", error)
    return ProviderHTTPError(f"No answer from {url}: {reason}")


def get_json(url: str, *, headers: Mapping[str, str] | None = None, timeout: float = 10) -> Any:
    """GET *url* and read its JSON."""
    try:
        with urllib.request.urlopen(_request(url, None, headers), timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise _error(url, error) from error


def post_json(url: str, payload: Mapping[str, Any], *, headers: Mapping[str, str] | None = None,
              timeout: float = TIMEOUT) -> Any:
    """POST *payload* to *url* and read its JSON answer (not streamed)."""
    try:
        with urllib.request.urlopen(_request(url, payload, headers), timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise _error(url, error) from error


def stream_lines(url: str, payload: Mapping[str, Any], *, cancel: threading.Event,
                 headers: Mapping[str, str] | None = None, timeout: float = TIMEOUT) -> Iterator[str]:
    """POST *payload* and yield the answer's lines as they arrive; stops early once *cancel* is set."""
    try:
        response = urllib.request.urlopen(_request(url, payload, headers), timeout=timeout)
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise _error(url, error) from error
    with response:
        try:
            for raw in response:
                if cancel.is_set():
                    return
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    yield line
        except (OSError, http.client.HTTPException) as error:  # the service went away in mid-answer
            raise _error(url, error) from error


def json_lines(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """Ollama's newline-delimited JSON, an object a line."""
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            if item.get("error"):
                raise ProviderHTTPError(str(item["error"]))
            yield item


def server_events(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """Server-sent events' ``data:`` objects, until ``data: [DONE]``."""
    for line in lines:
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            item = json.loads(data)
        except ValueError:
            continue
        if isinstance(item, dict):
            if item.get("error"):
                error = item["error"]
                raise ProviderHTTPError(str(error.get("message") if isinstance(error, dict) else error))
            yield item
