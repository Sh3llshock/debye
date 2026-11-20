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


