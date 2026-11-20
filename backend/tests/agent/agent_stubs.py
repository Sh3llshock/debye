"""Stub Claude client for tests."""
from types import SimpleNamespace


# ---------------------------------------------------------------- stub Claude
class Block(SimpleNamespace):
    def model_dump(self, exclude_none=True):
        return {k: v for k, v in vars(self).items() if v is not None}


def tool_use(name, **inp):
    return Block(type="tool_use", id=f"toolu_{name}_{abs(hash(str(inp))) % 10**6}", name=name, input=inp)


def text(t):
    return Block(type="text", text=t)


class StubClaude:
    """Returns scripted responses in order. Each script item: list of blocks, or an Exception to raise."""

    def __init__(self, script):
        self.script = list(script)
        self.requests: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        self.requests.append(dict(kw, messages=list(kw["messages"])))
        item = self.script.pop(0) if self.script else [text("ok")]
        if isinstance(item, Exception):
            raise item
        if item == "refusal":
            return SimpleNamespace(stop_reason="refusal", content=[], stop_details=None)
        stop = "tool_use" if any(b.type == "tool_use" for b in item) else "end_turn"
        return SimpleNamespace(stop_reason=stop, content=item)




# ---------------------------------------------------------------- stub OpenAI (Chat Completions)
import json as _json  # noqa: E402

_call_n = 0


def oa_call(name, **args):
    """A tool call the stub model makes."""
    global _call_n
    _call_n += 1
    return SimpleNamespace(id=f"call_{_call_n}", type="function",
                           function=SimpleNamespace(name=name, arguments=_json.dumps(args, ensure_ascii=False)))


class StubOpenAI:
    """Script items: list of oa_call(...) (tool calls), a str (plain text reply), "refusal", or an Exception."""

    def __init__(self, script):
        self.script = list(script)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        self.requests.append(dict(kw, messages=list(kw["messages"])))
        item = self.script.pop(0) if self.script else "ok"
        if isinstance(item, Exception):
            raise item
        if item == "refusal":
            msg = SimpleNamespace(content=None, tool_calls=None, refusal="I can't help with that.")
        elif isinstance(item, str):
            msg = SimpleNamespace(content=item, tool_calls=None, refusal=None)
        else:
            msg = SimpleNamespace(content=None, tool_calls=item, refusal=None)
        finish = "tool_calls" if msg.tool_calls else "stop"
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)])
