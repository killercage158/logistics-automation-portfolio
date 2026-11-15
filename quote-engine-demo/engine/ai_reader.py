"""Step 4a: the AI reads the team's messy price spreadsheets.

Staff keep carrier price lists in spreadsheets with no common layout: merged
headers, notes rows, prices in different columns, prices stored as text. Writing
a parser per layout breaks every time a carrier changes its template. So we let
the AI read each file and answer in a fixed JSON shape.

THE KEY RULE: for every price the AI must say exactly WHERE it read it
(sheet + cell). verify.py then opens that cell and checks. The AI never gets the
last word.

Replies from AI models are not always clean JSON: they may be wrapped in a code
fence, have a friendly sentence in front, or be cut off. So we parse
tolerantly, and if that fails we ask ONCE more. If the second reply is also
unreadable, the file is reported as unreadable (never silently skipped).

This file also holds the shared machinery every department's AI reader uses:

  ask_for_json()   put the department's SKILL FILE into the prompt, ask, parse the
                   reply tolerantly, re-ask once if needed
  parse_json_reply()

The skill file (skills/<department>.md) is the department's own guide. The AI is
told to follow it, and the code that checks the AI's answer enforces the same rule
IDs. Trucking (trucking.py) and customs (customs.py) call ask_for_json() too.

In production, each department's AI reader follows that department's own guide
document, and the AI reads the whole folder of price files. Simplified here: one
file per call, fixed small schema.
"""
import json
import re
from datetime import date

from engine.models import PriceRow
from engine.price_files import grid_text
from engine.request import normalise_cargo, normalise_container, normalise_port
from engine.rulebook import load_skill

OUTPUT_SPEC = """Return ONLY a JSON array. Each item has these keys:
  carrier    (string, the carrier the file belongs to)
  pol, pod   (port names as written)
  container  ("20GP", "40GP" or "40HC"; read 20' as 20GP and 40' as 40GP)
  cargo      ("general", "charcoal", or null if the file does not say)
  price_usd  (number)
  valid_until (YYYY-MM-DD, or null)
  source     ({"sheet": sheet name, "cell": the exact cell where the price number sits})
No text before or after the JSON."""


class ReplyError(Exception):
    """The AI's reply could not be turned into JSON."""


def system_prompt(skill_name, output_spec):
    """The AI's instructions = the department's skill file + the exact output format."""
    return (f"You work for the {skill_name} team of a freight forwarder. "
            "Follow the department's rules below exactly. Every answer must carry its citation.\n\n"
            f"# Department rules\n\n{load_skill(skill_name)}\n\n# Output format\n\n{output_spec}")


def build_prompt(department, key_line, body, retry=False):
    """User message. 'Department:' and the key line also let the mock provider pick its recording."""
    prompt = f"Department: {department}\n{key_line}\n\n{body}"
    if retry:
        prompt = ("Your previous reply was not valid JSON. Return ONLY the JSON array, "
                  "complete and closed, with no other text.\n\n" + prompt)
    return prompt


def parse_json_reply(text):
    """Pull a JSON list out of an AI reply. Tolerates fences, chatter and trailing commas."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)       # ```json ... ```
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ReplyError("no JSON list found in the reply")
    body = text[start:end + 1]
    for candidate in (body, re.sub(r",\s*([\]}])", r"\1", body)):   # 2nd try: drop trailing commas
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return data
    raise ReplyError("the reply is not valid JSON")


def ask_for_json(llm, department, skill_name, output_spec, key_line, body, log, label):
    """Ask the AI, parse the reply, re-ask ONCE if it is unusable. Raises ReplyError if still bad."""
    system = system_prompt(skill_name, output_spec)
    reply = llm.complete(system, build_prompt(department, key_line, body))
    try:
        return parse_json_reply(reply)
    except ReplyError as first_error:
        log.add(f"  {label}: reply not usable ({first_error}) -> asking once more")
        reply = llm.complete(system, build_prompt(department, key_line, body, retry=True))
        return parse_json_reply(reply)


def to_price_row(raw, file_name):
    """Turn one raw JSON item into a PriceRow, normalising ports and containers.

    Raises ValueError if something is missing or unreadable. The caller reports
    that item as rejected, with the reason.
    """
    try:
        source = raw["source"]
        valid = raw.get("valid_until")
        cargo = raw.get("cargo")
        return PriceRow(
            carrier=str(raw["carrier"]).strip(),
            pol=normalise_port(raw["pol"]),
            pod=normalise_port(raw["pod"]),
            container=normalise_container(raw["container"]),
            cargo=normalise_cargo(cargo) if cargo else None,
            price_usd=float(raw["price_usd"]),
            valid_until=date.fromisoformat(valid) if valid else None,
            file=file_name,                    # WE know the file name; do not trust the AI with it
            sheet=str(source["sheet"]),
            cell=str(source["cell"]).upper(),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"unreadable item ({type(e).__name__}: {e})")


def read_price_file(llm, path, log):
    """Ask the AI about one booking price file (BK-09 will verify the answer).

    Returns (rows, problems):
      rows:     list[PriceRow]
      problems: list[(text, reason)] for items or whole files we could not use
    """
    name = path.name
    try:
        raw_items = ask_for_json(llm, "booking", "booking-price-files", OUTPUT_SPEC,
                                 f"File: {name}", grid_text(path), log, name)
    except ReplyError as e:
        return [], [(name, f"whole file unreadable after one re-ask: {e}")]
    rows, problems = [], []
    for raw in raw_items:
        try:
            rows.append(to_price_row(raw, name))
        except ValueError as e:
            problems.append((json.dumps(raw)[:80], str(e)))
    log.add(f"  {name}: AI returned {len(raw_items)} items, {len(rows)} readable")
    return rows, problems
