"""One small door to the AI model: complete(system, user) -> text.

The rest of the engine never knows which AI answered. It sends a prompt and
gets text back. Three providers sit behind that door:

  mock       (default) replies from recorded files in fixtures/. No key, no cost,
             same answer every time. This is what the tests and the demo use.
  anthropic  Claude, through the official Anthropic Python SDK.
             Needs ANTHROPIC_API_KEY. Model: env CLAUDE_MODEL (default claude-opus-5-5).
  gemini     Google Gemini, through the google-genai package.
             Needs GEMINI_API_KEY. Model: env GEMINI_MODEL.

WHY a mock: you can run and test the whole pipeline offline, and the
fixtures include two deliberately bad answers (a wrong cell and an invented
price) so you can watch the verification step reject them.

In production, the AI reader for the booking team's price files calls the Claude
command-line tool from code; here we call the SDK, which is simpler to read. The
provider switch mirrors a provider setting in production.
"""
import os
import re
from pathlib import Path

DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
DEFAULT_GEMINI_MODEL = "gemini-2.5-pro"


class MockLLM:
    """Replies with recorded text, one recording per department and per item.

    The prompt starts with 'Department: <name>' and has a key line ('File: x.xlsx' or
    'Product: wood charcoal'). The recording lives in fixtures/<department>/<key>.reply.txt.
    """

    name = "mock"

    def __init__(self, fixtures_dir):
        self.dir = Path(fixtures_dir)

    def complete(self, system, user):
        dept = re.search(r"^Department: (\w+)", user, re.M)
        item = re.search(r"^(?:File|Product): (.+?)\s*$", user, re.M)
        if not dept or not item:
            raise ValueError("Mock LLM: prompt needs 'Department:' and 'File:' or 'Product:' lines")
        name = item.group(1)
        name = re.sub(r"\.xlsx$", "", name) if name.endswith(".xlsx") else re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        # The "second try" prompt asks for clean JSON, so it gets the "retry" recording.
        suffix = "retry" if "was not valid JSON" in user else "reply"
        path = self.dir / dept.group(1) / f"{name}.{suffix}.txt"
        if not path.exists():
            raise FileNotFoundError(f"No recorded AI answer: {path}")
        return path.read_text(encoding="utf-8")


class AnthropicLLM:
    name = "anthropic"

    def __init__(self):
        if "ANTHROPIC_API_KEY" not in os.environ:
            raise SystemExit("Live mode with Claude needs ANTHROPIC_API_KEY in the environment.")
        import anthropic                       # imported here so mock mode needs no SDK
        self.client = anthropic.Anthropic()    # the SDK reads ANTHROPIC_API_KEY itself
        self.model = os.environ.get("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL)

    def complete(self, system, user):
        response = self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if response.stop_reason == "refusal":  # rare; never read content blindly
            raise RuntimeError("The model declined to answer this request")
        return "".join(block.text for block in response.content if block.type == "text")


class GeminiLLM:
    name = "gemini"

    def __init__(self):
        if "GEMINI_API_KEY" not in os.environ:
            raise SystemExit("Live mode with Gemini needs GEMINI_API_KEY in the environment.")
        from google import genai               # imported here so mock mode needs no SDK
        from google.genai import types
        self.types = types
        self.client = genai.Client()           # the SDK reads GEMINI_API_KEY itself
        self.model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)

    def complete(self, system, user):
        config = self.types.GenerateContentConfig(system_instruction=system)
        response = self.client.models.generate_content(model=self.model, contents=user, config=config)
        return response.text or ""


def make_llm(live, fixtures_dir):
    """--live picks the provider named in LLM_PROVIDER (default: anthropic). Otherwise: mock."""
    if not live:
        return MockLLM(fixtures_dir)
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    if provider == "anthropic":
        return AnthropicLLM()
    if provider == "gemini":
        return GeminiLLM()
    raise SystemExit(f"Unknown LLM_PROVIDER '{provider}'. Use anthropic or gemini.")
