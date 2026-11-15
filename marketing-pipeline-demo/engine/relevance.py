"""Step 2: the AI relevance filter removes off-topic ideas before an editor sees them (MK-03, MK-04).

How one sweep works:
  1. take every idea with status "new" (collected, not judged yet);
  2. send them in batches of up to 25: one line per idea, "I-07 | title | first 300 characters";
  3. the AI answers {"verdicts": [{"id", "relevant", "reason"}, ...]};
  4. a reply that is unusable (not JSON, or a verdict missing) is asked once more; if it is still
     unusable, the batch is split in half and each half is asked on its own; a single idea that
     still gets no verdict is KEPT (status pending) so a human judges it;
  5. relevant -> "pending" (waits for Gate 1); off-topic -> "filtered", with the AI's reason.

WHY two different failure behaviours:
  - AI outage (MK-04): mark NOTHING. If we marked everything "relevant" without asking, junk
    would reach the editors; if we marked everything "off-topic", good ideas would vanish. So
    we wait and try again next cycle.
  - one idea the AI will not judge: keep it. It costs an editor two seconds to skip it; losing
    a good idea silently costs more.

In production the filter runs inside the polling loop with a fixed yes/no schema at
temperature 0; ideas it rejects are deleted from the idea table with a log line.
"""
from engine.llm import AIDeclined, AIUnavailable, parse_json_object

BATCH = 25


def _ask(llm, prompts, batch, log, trace):
    """One call for a batch. Returns {id: (relevant, reason)} covering every idea, or None."""
    lines = [f"{i.id} | {i.title} | {' '.join(i.text.split())[:300]}" for i in batch]
    user = "Task: relevance\nJudge each idea below. One line per idea: id | title | start of the text.\n\n" + "\n".join(lines)
    try:
        reply = llm.complete(prompts.relevance_system(), user)
    except AIDeclined:
        reply = ""
    data = parse_json_object(reply) or {}
    verdicts = {v.get("id"): (bool(v.get("relevant")), str(v.get("reason", "")).strip())
                for v in data.get("verdicts", []) if isinstance(v, dict)}
    missing = [i.id for i in batch if i.id not in verdicts]
    if missing:
        log.append(f"    reply had {len(batch) - len(missing)} verdicts for {len(batch)} ideas "
                   f"(missing {', '.join(missing)})")
        trace.hit("MK-03", f"unusable reply: {len(missing)} of {len(batch)} verdicts missing")
        return None
    return verdicts


def _resolve(llm, prompts, batch, log, trace):
    """Ask, ask once more, then split. Never returns without a decision for every idea."""
    result = _ask(llm, prompts, batch, log, trace)
    if result is None:
        log.append("    -> asking once more")
        result = _ask(llm, prompts, batch, log, trace)
    if result is not None:
        return result
    if len(batch) > 1:
        mid = len(batch) // 2
        log.append(f"    -> splitting the batch: {batch[0].id}..{batch[mid - 1].id} and {batch[mid].id}..{batch[-1].id}")
        trace.hit("MK-03", f"batch of {len(batch)} split in two")
        return {**_resolve(llm, prompts, batch[:mid], log, trace), **_resolve(llm, prompts, batch[mid:], log, trace)}
    trace.hit("MK-03", f"{batch[0].id}: no verdict after retries -> kept for a human")
    return {batch[0].id: (True, "the AI gave no verdict; kept so an editor can decide")}


def relevance_sweep(state, llm, prompts, now, log, trace):
    """Judge every idea with status 'new'. Returns the number of ideas judged."""
    todo = [i for i in state.ideas.values() if i.status == "new"]
    if not todo:
        return 0
    log.append(f"  relevance filter: {len(todo)} new idea(s), batches of up to {BATCH}")
    decided = {}
    try:
        for start in range(0, len(todo), BATCH):
            decided.update(_resolve(llm, prompts, todo[start:start + BATCH], log, trace))
    except AIUnavailable as e:
        log.append(f"    AI unavailable ({e}) -> nothing marked, the filter runs again next cycle [MK-04]")
        trace.hit("MK-04", f"{now:%H:%M}: AI unavailable, {len(todo)} idea(s) left as 'new'")
        return 0
    for idea in todo:
        relevant, reason = decided[idea.id]
        if relevant:
            idea.status, idea.reason = "pending", f"relevant: {reason}"
            idea.note(now, f"AI: relevant ({reason})")
        else:
            idea.status, idea.reason = "filtered", f"off-topic: {reason}"
            idea.note(now, f"AI: off-topic ({reason})")
            log.append(f"    {idea.id} OFF-TOPIC  \"{idea.title[:55]}\" - {reason} [MK-03]")
        trace.hit("MK-03", f"{idea.id}: {'relevant' if relevant else 'off-topic'} - {reason}")
    kept = sum(1 for i in todo if i.status == "pending")
    log.append(f"    {kept} relevant (wait for Gate 1), {len(todo) - kept} off-topic (removed from the board)")
    return len(todo)
