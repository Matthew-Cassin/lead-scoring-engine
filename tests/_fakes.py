"""Shared test doubles for a Claude API ``Message`` response.

Not a test module itself (no ``test_`` prefix, so pytest won't collect
it) -- just a small factory used by test_claude_extractor.py and
test_claude_scorer.py to build fake responses shaped like the real
``anthropic.types.Message`` object returned by
``client.messages.create()``, confirmed against the installed SDK
(``anthropic==0.121.0``) while building this package: ``response.content``
is a list of blocks with ``.type``/``.text``, and ``response.usage`` has
``.input_tokens``/``.output_tokens``.
"""

from __future__ import annotations


class FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class FakeUsage:
    def __init__(self, input_tokens: int = 100, output_tokens: int = 50) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeMessage:
    """A minimal stand-in for ``anthropic.types.Message``."""

    def __init__(self, text: str, input_tokens: int = 100, output_tokens: int = 50) -> None:
        self.content = [FakeTextBlock(text)]
        self.usage = FakeUsage(input_tokens, output_tokens)
