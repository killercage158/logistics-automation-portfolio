"""One door to the AI model: complete(system, user) -> text.

The rest of the pipeline never knows which AI answered. Three providers sit behind the door:

  mock       (default) answers from recorded files in fixtures/llm/. No key, no cost, same
             answers every run. Some recorded answers are deliberately bad (an outage, a
             reply with missing verdicts, a banned phrase, a dropped source line, a refusal)
             so you can watch the rules catch them.
  anthropic  Claude, through the official Anthropic Python SDK. Needs ANTHROPIC_API_KEY.
             Model: env CLAUDE_MODEL (default claude-opus-5-5). Server-side refusal fallback
             is switched on, so a declined request is re-run on a fallback model in the same call.
  gemini     Google Gemini, through the google-genai package. Needs GEMINI_API_KEY.

Every prompt starts its user message with a "Task: <name>" line (relevance, draft, comment,
rewrite, oa_article) and, when it is about one idea, an "Idea: I-xx" line. The mock uses those
lines to find the recorded answer.

AIUnavailable means "the AI could not be reached" (outage, rate limit, server error). Callers
decide what that means for their step: the relevance filter marks nothing and tries again next
cycle (rule MK-04); the writer leaves the idea approved so it is retried.

In production the writer and the filter call a hosted model through an API proxy with retries
and a cost log; here we call the SDK directly, which is simpler to read.
"""
import json
import os
import re
from pathlib import Path

DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
DEFAULT_GEMINI_MODEL = "gemini-2.5-pro"


class AIUnavailable(Exception):
    """The AI service did not answer (outage, overload, rate limit, network)."""


class AIDeclined(Exception):
    """The AI answered with a refusal instead of content."""


class MockLLM:
    """Replies with recorded answers, chosen by the Task and Idea lines of the prompt."""

    name = "mock"

    def __init__(self, fixtures_dir):
        folder = Path(fixtures_dir) / "llm"
        load = lambda name: json.loads((folder / name).read_text(encoding="utf-8"))
        relevance = load("relevance.json")
        self.planted = list(relevance["planted"])      # one entry per relevance call, used first
        self.verdicts = relevance["verdicts"]
        self.tables = {"draft": load("drafts.json"), "comment": load("comments.json"),
                       "rewrite": load("rewrites.json"), "oa_article": load("oa_articles.json")}
        self.calls = {}                                 # (task, idea) -> how many times asked
        self.log = []                                   # every (task, idea) asked, for tests

    def complete(self, system, user):
        task = re.search(r"^Task: (\w+)", user, re.M).group(1)
        if task == "relevance":
            ids = re.findall(r"^(I-\d+) \|", user, re.M)
            self.log.append((task, ",".join(ids)))
            planted = self.planted.pop(0) if self.planted else None
            if planted == "outage":
                raise AIUnavailable("planted outage: the AI service did not answer")
            if planted == "short":
                ids = ids[: max(1, len(ids) * 3 // 4)]   # a reply that forgets some ideas
            verdicts = []
            for i in ids:
                relevant, reason = self.verdicts.get(i, [True, "no recorded verdict"])
                verdicts.append({"id": i, "relevant": relevant, "reason": reason})
            return json.dumps({"verdicts": verdicts}, ensure_ascii=False)
        idea = re.search(r"^Idea: (I-\d+)", user, re.M).group(1)
        self.log.append((task, idea))
        replies = self.tables[task].get(idea)
        if replies is None:
            raise FileNotFoundError(f"No recorded {task} answer for {idea}")
        replies = replies if isinstance(replies, list) else [replies]
        n = self.calls.get((task, idea), 0)
        self.calls[(task, idea)] = n + 1
        reply = replies[min(n, len(replies) - 1)]      # later calls get the next recorded answer
        return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)


class AnthropicLLM:
    name = "anthropic"

    def __init__(self):
        if "ANTHROPIC_API_KEY" not in os.environ:
            raise SystemExit("Live mode with Claude needs ANTHROPIC_API_KEY in the environment.")
        import anthropic                                # imported here so mock mode needs no SDK
        self.sdk = anthropic
        self.client = anthropic.Anthropic()             # the SDK reads ANTHROPIC_API_KEY itself
        self.model = os.environ.get("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL)

    def complete(self, system, user):
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user}],
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",                    # a declined request is re-run on a fallback model
            )
        except (self.sdk.RateLimitError, self.sdk.InternalServerError, self.sdk.APIConnectionError) as e:
            raise AIUnavailable(f"{type(e).__name__}: {e}")
        if response.stop_reason == "refusal":           # the whole fallback chain declined
            raise AIDeclined("the model declined this request")
        return "".join(block.text for block in response.content if block.type == "text")


class GeminiLLM:
    name = "gemini"

    def __init__(self):
        if "GEMINI_API_KEY" not in os.environ:
            raise SystemExit("Live mode with Gemini needs GEMINI_API_KEY in the environment.")
        from google import genai                        # imported here so mock mode needs no SDK
        from google.genai import types
        self.types = types
        self.client = genai.Client()                    # the SDK reads GEMINI_API_KEY itself
        self.model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)

    def complete(self, system, user):
        config = self.types.GenerateContentConfig(system_instruction=system)
        try:
            response = self.client.models.generate_content(model=self.model, contents=user, config=config)
        except Exception as e:                          # network, quota, overload: try again later
            raise AIUnavailable(f"{type(e).__name__}: {e}")
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


def parse_json_object(text):
    """Return the first JSON object in a reply, or None. Tolerates code fences and chatter."""
    text = (text or "").strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except ValueError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else None
    except ValueError:
        return None
