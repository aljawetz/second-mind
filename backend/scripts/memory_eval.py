"""Agent memory evaluation on LongMemEval — design in
docs/specs/2026-09-25-agent-memory-evaluation-design.md (§3, §4).

Four systems answer the same questions about a user's past conversations,
with the same neutral prompt and the same model:

  S0  shipped chat memory: the last 6 question/answer pairs, answers cut
      to 1,500 characters (chat.HISTORY_TURNS, chat.HISTORY_ANSWER_CHARS).
  S1  everything in context: every past session, in order, with its date.
  S2  search over raw turns: each user/assistant pair embedded with the
      app's BGE model, top 10 by cosine similarity.
  S3  the memory layer: sessions replayed through MemoryService.observe at
      their real dates, a sweep at question time, then the profile, one
      automatic recall, and up to 2 recall_memory calls.
  S4  S3 plus search over past chats (docs/specs/2026-11-10-past-chat-
      search-design.md): the sessions' turns are indexed as the app's
      worker indexes saved chats, and search_past_chats is offered too.
  S5  S4 plus one automatic past-chat search for the question, shown up
      front when anything matched. An experiment: not in the app.

Answers are graded by gpt-4o with LongMemEval's own judge prompts.

Stage 1 (this file so far) runs the development sample on the oracle split,
where each question's history holds only the sessions that contain the
answer. That tests extraction, consolidation and recall, not finding the
answer among 50 unrelated sessions: the S split does that, and is not wired
in yet. Evidence recall, ablations and significance tests are also still to
come.

Not a pytest test: it makes real, billed OpenAI calls. Run from backend/:

    uv run python3 scripts/memory_eval.py --per-type 5 --out /tmp/memory-eval
    uv run python3 scripts/memory_eval.py --per-type 1 --systems S0,S3 --no-judge --out /tmp/smoke

The run resumes: an answer already in <out>/answers.jsonl is not asked again.
Questions run 8 at a time (--workers). A question's memories are written
once per write model and prompts and kept under .cache/memory_eval/writes,
so runs that only change how memories are read reuse them (--no-write-cache
to write afresh). Answer times are measured under that load, so compare
them within a run, not with the app.
"""

import argparse
import hashlib
import json
import math
import random
import shutil
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

CACHE_DIR = Path(__file__).parent.parent / ".cache" / "longmemeval"
ORACLE_FILE = CACHE_DIR / "longmemeval_oracle.json"
# One question's memories, written once and reused by every run that only
# changes how they are read (recall limit, tools, answering). Writing them
# is most of a run's time and cost.
WRITE_CACHE = CACHE_DIR.parent / "memory_eval" / "writes"

ANSWER_MODEL = "gpt-4o-mini"
# A stronger model than the one under test, and the one the LongMemEval paper reports.
JUDGE_MODEL = "gpt-4o"
ANSWER_TEMPERATURE = 0.1  # chat's own setting (llm.OpenAIProvider)
S0_PAIRS = 6  # chat.HISTORY_TURNS
S0_ANSWER_CHARS = 1500  # chat.HISTORY_ANSWER_CHARS
S2_TOP_K = 10
S3_RECALL_ROUNDS = 2
RECALL_K = 5  # memories per recall, the app's (MemoryService.recall); --recall-k tries others
# $ per 1M tokens (input, output), the same figures as ask_modes_eval.py.
# gpt-5.4-mini from OpenAI's model page (developers.openai.com/docs/models/gpt-5.4-mini), read 2026-11-10.
# gpt-5-mini: OpenAI's list price as of its August 2025 release; check before budgeting.
PRICES = {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00), "gpt-5.4-mini": (0.75, 4.50), "gpt-5-mini": (0.25, 2.00)}
# Reasoning models that only accept the default temperature. They reason
# before answering by default (hidden tokens, billed as output).
NO_TEMPERATURE = {"gpt-5", "gpt-5-mini", "gpt-5-nano"}

PAST_CHATS_NOTE = (
    "\n\nsearch_past_chats looks through what you and the user said in those conversations, word for word. "
    "Use it when what you remember doesn't hold the answer, or the question is about something you said."
)

ANSWER_PROMPT = """You are a helpful assistant with memory of past conversations with this user. Today is {today}.
Answer the user's question from what they told you in those conversations. Work out dates and counts from \
what is given. If they never told you, say you don't know. Be concise."""


# --- data ---------------------------------------------------------------------


@dataclass
class Session:
    session_id: str
    at: datetime
    turns: list[dict]  # [{"role", "content"}], as the app stores them


def parse_date(text: str) -> datetime:
    """LongMemEval's "2023/04/10 (Mon) 23:07". No zone is given; UTC keeps
    the memory store's dates comparable."""
    day, _, clock = text.split(" ")
    return datetime.strptime(f"{day} {clock}", "%Y/%m/%d %H:%M").replace(tzinfo=timezone.utc)


def is_abstention(question: dict) -> bool:
    return "_abs" in question["question_id"]


def sessions_in_order(question: dict) -> list[Session]:
    sessions = [
        Session(sid, parse_date(date), [{"role": t["role"], "content": t["content"]} for t in turns])
        for sid, date, turns in zip(
            question["haystack_session_ids"], question["haystack_dates"], question["haystack_sessions"]
        )
    ]
    return sorted(sessions, key=lambda s: s.at)


def sample_questions(questions: list[dict], per_type: int, seed: int, exclude: set[str] = frozenset()) -> list[dict]:
    """The same `per_type` questions of each type on every run with this seed."""
    by_type: dict[str, list[dict]] = {}
    for q in questions:
        if q["question_id"] not in exclude:
            by_type.setdefault(q["question_type"], []).append(q)
    rng = random.Random(seed)
    sample = []
    for qtype in sorted(by_type):
        pool = sorted(by_type[qtype], key=lambda q: q["question_id"])
        sample += rng.sample(pool, min(per_type, len(pool)))
    return sample


# --- what each system sees ----------------------------------------------------


def _pairs(sessions: list[Session]) -> list[tuple[Session, str, str]]:
    """(session, what the user said, what the assistant answered), oldest first."""
    pairs = []
    for session in sessions:
        user = None
        for turn in session.turns:
            if turn["role"] == "user":
                if user is not None:
                    pairs.append((session, user, ""))
                user = turn["content"]
            elif user is not None:
                pairs.append((session, user, turn["content"]))
                user = None
        if user is not None:
            pairs.append((session, user, ""))
    return pairs


def _pair_text(user: str, assistant: str) -> str:
    return f"User: {user}\nAssistant: {assistant}"


def turns_to_index(session: Session) -> list[dict]:
    """One session as the app would put it in the past-chat index
    (memory_jobs.index_conversation): a row per question and answer, titled
    by the chat's first question the way conversations.append_turn titles it."""
    pairs = _pairs([session])
    title = " ".join(pairs[0][1].split())[:60] if pairs else ""
    return [
        {"conversation_id": session.session_id, "turn_index": i, "title": title, "at": session.at, "question": user, "answer": assistant}
        for i, (_, user, assistant) in enumerate(pairs)
    ]


def context_s0(sessions: list[Session]) -> str:
    recent = _pairs(sessions)[-S0_PAIRS:]
    return "\n\n".join(_pair_text(user, assistant[:S0_ANSWER_CHARS]) for _, user, assistant in recent)


def context_s1(sessions: list[Session]) -> str:
    parts = []
    for session in sessions:
        body = "\n".join(f"{t['role'].capitalize()}: {t['content']}" for t in session.turns)
        parts.append(f"## Conversation on {session.at:%Y-%m-%d %H:%M}\n{body}")
    return "\n\n".join(parts)


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0


def context_s2(sessions: list[Session], question: str, embed, k: int = S2_TOP_K) -> tuple[str, list[str]]:
    """The k pairs closest to the question, and the sessions they came from, best first."""
    query = embed(question)
    scored = [
        (_cosine(query, embed(_pair_text(user, assistant))), session, user, assistant)
        for session, user, assistant in _pairs(sessions)
    ]
    top = sorted(scored, key=lambda item: -item[0])[:k]
    context = "\n\n".join(f"[{s.at:%Y-%m-%d %H:%M}]\n{_pair_text(user, assistant)}" for _, s, user, assistant in top)
    return context, [s.session_id for _, s, _, _ in top]


# --- judging (LongMemEval's own prompts) --------------------------------------

# Copied from src/evaluation/evaluate_qa.py in https://github.com/xiaowu0162/LongMemEval
# (MIT License, Copyright (c) 2024 Di Wu). Wording unchanged, so the grades
# mean what the benchmark's grades mean.
_JUDGE_BASE = (
    "I will give you a question, a correct answer, and a response from a model. Please answer yes if the "
    "response contains the correct answer. Otherwise, answer no. "
)
_JUDGE_TAIL = "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
_JUDGE_EQUIVALENT = (
    "If the response is equivalent to the correct answer or contains all the intermediate steps to get the "
    "correct answer, you should also answer yes. If the response only contains a subset of the information "
    "required by the answer, answer no. "
)
JUDGE_TEMPLATES = {
    "single-session-user": _JUDGE_BASE + _JUDGE_EQUIVALENT + _JUDGE_TAIL,
    "single-session-assistant": _JUDGE_BASE + _JUDGE_EQUIVALENT + _JUDGE_TAIL,
    "multi-session": _JUDGE_BASE + _JUDGE_EQUIVALENT + _JUDGE_TAIL,
    "temporal-reasoning": _JUDGE_BASE
    + _JUDGE_EQUIVALENT
    + "In addition, do not penalize off-by-one errors for the number of days. If the question asks for the "
    "number of days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days when "
    "the answer is 18), the model's response is still correct. "
    + _JUDGE_TAIL,
    "knowledge-update": _JUDGE_BASE
    + "If the response contains some previous information along with an updated answer, the response should "
    "be considered as correct as long as the updated answer is the required answer."
    + _JUDGE_TAIL,
    "single-session-preference": (
        "I will give you a question, a rubric for desired personalized response, and a response from a model. "
        "Please answer yes if the response satisfies the desired response. Otherwise, answer no. The model does "
        "not need to reflect all the points in the rubric. The response is correct as long as it recalls and "
        "utilizes the user's personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}"
        "\n\nIs the model response correct? Answer yes or no only."
    ),
}
JUDGE_ABSTENTION = (
    "I will give you an unanswerable question, an explanation, and a response from a model. Please answer yes "
    "if the model correctly identifies the question as unanswerable. The model could say that the information "
    "is incomplete, or some other information is given but the asked information is not.\n\nQuestion: {}\n\n"
    "Explanation: {}\n\nModel Response: {}\n\nDoes the model correctly identify the question as unanswerable? "
    "Answer yes or no only."
)


def judge_prompt(task: str, question: str, answer: str, response: str, abstention: bool = False) -> str:
    if abstention:
        return JUDGE_ABSTENTION.format(question, answer, response)
    if task not in JUDGE_TEMPLATES:
        raise ValueError(f"no judge prompt for question type {task!r}")
    return JUDGE_TEMPLATES[task].format(question, answer, response)


def judged_correct(reply: str) -> bool:
    return "yes" in reply.lower()


# --- metrics ------------------------------------------------------------------


def wilson(correct: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a rate."""
    if n == 0:
        return (0.0, 0.0)
    p = correct / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def _tally(rows: list[dict]) -> dict:
    return {"correct": sum(bool(r["correct"]) for r in rows), "n": len(rows)}


def summarize(rows: list[dict]) -> dict:
    """Per system. Abstention is kept apart from the answerable questions: a
    system that knows almost nothing gets abstention right for free."""
    summary = {}
    for system in sorted({r["system"] for r in rows}):
        mine = [r for r in rows if r["system"] == system]
        answerable = [r for r in mine if not r["abstention"]]
        summary[system] = {
            "answerable": _tally(answerable),
            "abstention": _tally([r for r in mine if r["abstention"]]),
            "by_type": {
                qtype: _tally([r for r in answerable if r["question_type"] == qtype])
                for qtype in sorted({r["question_type"] for r in answerable})
            },
            "mean_prompt_tokens": statistics.mean(r["prompt_tokens"] for r in mine),
            "median_seconds": statistics.median(r["seconds"] for r in mine),
        }
    return summary


# --- model calls ---------------------------------------------------------------


@dataclass
class CountingLLM:
    """Every model call of a run goes through here, so tokens are counted
    per stage: "write" (memory extraction and consolidation), "answer",
    "judge". complete_json is the interface MemoryService expects."""

    client: object
    stage: str = "answer"
    write_model: str = ANSWER_MODEL  # memory extraction and consolidation
    answer_model: str = ANSWER_MODEL  # the app's default; --answer-model tries others
    usage: dict = field(default_factory=dict)
    reasoning_tokens: int = 0  # hidden reasoning, already inside the completion tokens

    def _count(self, model: str, response) -> None:
        slot = self.usage.setdefault((self.stage, model), {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
        slot["calls"] += 1
        slot["prompt_tokens"] += response.usage.prompt_tokens
        slot["completion_tokens"] += response.usage.completion_tokens

    def complete_json(self, messages: list[dict]) -> object:
        response = self.client.chat.completions.create(
            model=self.write_model, messages=messages, temperature=0, response_format={"type": "json_object"}
        )
        self._count(self.write_model, response)
        try:
            return json.loads(response.choices[0].message.content or "")
        except json.JSONDecodeError:
            return None

    def chat(self, messages: list[dict], tools: list[dict] | None = None, model: str | None = None, temperature: float = ANSWER_TEMPERATURE):
        model = model or self.answer_model
        kwargs = {"tools": tools} if tools else {}
        if model not in NO_TEMPERATURE:
            kwargs["temperature"] = temperature
        response = self.client.chat.completions.create(model=model, messages=messages, **kwargs)
        self._count(model, response)
        details = getattr(response.usage, "completion_tokens_details", None)
        self.reasoning_tokens += getattr(details, "reasoning_tokens", 0) or 0
        return response.choices[0].message, response.usage.prompt_tokens

    def add(self, other: "CountingLLM") -> None:
        """Fold in the calls of a question that ran on its own counter."""
        for key, slot in other.usage.items():
            mine = self.usage.setdefault(key, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
            for field_name in mine:
                mine[field_name] += slot[field_name]
        self.reasoning_tokens += other.reasoning_tokens

    def dollars(self) -> float:
        total = 0.0
        for (_, model), slot in self.usage.items():
            if model not in PRICES:  # no price on file: its tokens are listed, not costed
                continue
            price_in, price_out = PRICES[model]
            total += (slot["prompt_tokens"] * price_in + slot["completion_tokens"] * price_out) / 1_000_000
        return total


def _system_prompt(question: dict, heading: str, context: str) -> str:
    today = parse_date(question["question_date"])
    prompt = ANSWER_PROMPT.format(today=f"{today:%A, %B} {today.day}, {today.year}")
    return f"{prompt}\n\n{heading}\n{context or '(nothing)'}"


def answer_from_context(llm: CountingLLM, question: dict, context: str) -> dict:
    messages = [
        {"role": "system", "content": _system_prompt(question, "Past conversations:", context)},
        {"role": "user", "content": question["question"]},
    ]
    message, prompt_tokens = llm.chat(messages)
    return {"answer": message.content or "", "prompt_tokens": prompt_tokens}


def write_cache_key(question: dict, write_model: str, prompts: str | None = None) -> str:
    """Names one question's written memories. The model and both write
    prompts are part of it, so changing any of them writes afresh."""
    if prompts is None:
        from memory import consolidate, extract

        prompts = extract.SYSTEM_PROMPT + "|" + consolidate.SYSTEM_PROMPT
    payload = json.dumps([question["question_id"], write_model, prompts])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def written_memories(llm: CountingLLM, question: dict, sessions: list[Session], embed, use_cache: bool) -> tuple[Path, dict]:
    """The memory.db left after replaying this question's history, and what
    writing it took. Replayed through MemoryService.observe at the sessions'
    real dates, then swept at the question's date. Written once per
    (question, write model, prompts) and kept under WRITE_CACHE."""
    from memory import MemoryService

    folder = WRITE_CACHE / write_cache_key(question, llm.write_model)
    db, stats_file = folder / "memory.db", folder / "stats.json"
    if use_cache and db.exists() and stats_file.exists():
        return db, {**json.loads(stats_file.read_text()), "write_reused": True}

    today = parse_date(question["question_date"])
    llm.stage = "write"
    start = time.perf_counter()
    before = dict(llm.usage.get(("write", llm.write_model), {"calls": 0, "prompt_tokens": 0}))
    ops: dict[str, int] = {}
    dropped = 0
    with tempfile.TemporaryDirectory() as home:
        with MemoryService(Path(home), 1, llm=llm, embed=embed, now=lambda: today) as memory:
            for session in sessions:
                seen = memory.observe(session.turns, conversation_id=session.session_id, turn_index=0, at=session.at)
                for decision in seen.decisions:
                    ops[decision.action] = ops.get(decision.action, 0) + 1
                dropped += len(seen.dropped)
            memory.sweep()
        # Closed, so the file is whole (no WAL left behind) and safe to copy.
        after = llm.usage.get(("write", llm.write_model), {"calls": 0, "prompt_tokens": 0})
        stats = {
            "write_seconds": round(time.perf_counter() - start, 2),
            "write_calls": after["calls"] - before["calls"],
            "write_prompt_tokens": after["prompt_tokens"] - before["prompt_tokens"],
            "ops": ops,
            "dropped": dropped,
        }
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(home) / "courses" / "1" / "memory.db", db)
        stats_file.write_text(json.dumps(stats))
    llm.stage = "answer"
    return db, {**stats, "write_reused": False}


def answer_s3(
    llm: CountingLLM, question: dict, sessions: list[Session], embed, past_chats: bool = False, auto_past: bool = False,
    use_cache: bool = True,
) -> dict:
    """Replay the history into a fresh memory store, then answer the way
    chat.answer uses memory: profile, one automatic recall, recall_memory.
    past_chats (S4): the sessions' turns are also indexed, as the worker
    does in the app, and search_past_chats is offered beside recall_memory.
    auto_past (S5): the question is also searched in past chats up front,
    as it already is in memory, and shown when anything matched."""
    import chat
    from memory import MemoryService
    from memory.recall import format_hits

    today = parse_date(question["question_date"])
    written_db, written = written_memories(llm, question, sessions, embed, use_cache)
    with tempfile.TemporaryDirectory() as home:
        # A private copy: answering marks memories as used and indexes turns.
        target = Path(home) / "courses" / "1" / "memory.db"
        target.parent.mkdir(parents=True)
        shutil.copyfile(written_db, target)
        with MemoryService(Path(home), 1, llm=llm, embed=embed, now=lambda: today) as memory:
            turns_indexed = turns_skipped = 0
            if past_chats:
                from memory.past_chats import format_turns

                for session in sessions:
                    for turn in turns_to_index(session):
                        if memory.index_turn(**turn):
                            turns_indexed += 1
                        else:
                            turns_skipped += 1  # the grades-and-deadlines filter
            past_calls = 0
            past_sessions: list[str] = []
            llm.stage = "answer"

            recalled: list = []
            shown = 0

            def show(hits) -> str:
                nonlocal shown
                text = format_hits(hits, first_label=shown + 1)
                shown += len(hits)
                recalled.extend(hits)
                return text

            profile = memory.profile_block()
            context = profile + "\n\nRecalled for this question:\n" + show(memory.recall(question["question"], k=RECALL_K))
            auto_turns = memory.search_past_chats(question["question"]) if auto_past else []
            if auto_turns:
                past_sessions += [t.conversation_id for t in auto_turns]
                context += "\n\nFound in earlier conversations for this question:\n" + format_turns(
                    auto_turns, query=question["question"]
                )
            messages = [
                {
                    "role": "system",
                    "content": _system_prompt(question, "What you remember about this user:", context.strip())
                    + (PAST_CHATS_NOTE if past_chats else ""),
                },
                {"role": "user", "content": question["question"]},
            ]
            prompt_tokens = 0
            for round_num in range(S3_RECALL_ROUNDS + 1):
                offered = [chat.RECALL_TOOL, chat.PAST_CHATS_TOOL] if past_chats else [chat.RECALL_TOOL]
                tools = offered if round_num < S3_RECALL_ROUNDS else None
                message, used = llm.chat(messages, tools)
                prompt_tokens += used
                if not message.tool_calls:
                    break
                messages.append(message)
                for call in message.tool_calls:
                    try:
                        args = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    query = args.get("query")
                    if not (isinstance(query, str) and query.strip()):
                        result = "Empty query."
                    elif call.function.name == "search_past_chats" and past_chats:
                        found = memory.search_past_chats(query)
                        result = format_turns(found, first_label=len(past_sessions) + 1, query=query)
                        past_calls += 1
                        past_sessions += [t.conversation_id for t in found]
                    else:
                        result = show(memory.recall(query, k=RECALL_K, include_history=args.get("include_history") is True))
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            return {
                "answer": message.content or "",
                "prompt_tokens": prompt_tokens,
                "memories": len(memory.list()),
                # For the failure analysis (spec §7): what was stored, what
                # consolidation did, and what the answer was shown.
                "stored": [
                    {
                        "kind": m.kind,
                        "text": m.text,
                        "status": m.status,
                        "current": m.valid_to is None,
                        "event_time": m.event_time.isoformat() if m.event_time else None,
                        "sessions": [sid for sid, _ in m.provenance],
                    }
                    for m in memory.list(include_inactive=True)
                ],
                "ops": written["ops"],
                "dropped": written["dropped"],
                "profile": profile,
                "recalled": [hit.memory.text for hit in recalled],
                "recalled_sessions": [sid for hit in recalled for sid, _ in hit.memory.provenance],
                "past_chat_calls": past_calls,
                "auto_past_turns": len(auto_turns),
                "past_chat_sessions": past_sessions,
                "turns_indexed": turns_indexed,
                "turns_skipped": turns_skipped,
                # What writing took when it was done, also when reused from the cache.
                "write_seconds": written["write_seconds"],
                "write_calls": written["write_calls"],
                "write_prompt_tokens": written["write_prompt_tokens"],
                "write_reused": written["write_reused"],
            }


def run_system(system: str, llm: CountingLLM, question: dict, embed, use_cache: bool = True) -> dict:
    sessions = sessions_in_order(question)
    start = time.perf_counter()
    if system == "S0":
        out = answer_from_context(llm, question, context_s0(sessions))
    elif system == "S1":
        out = answer_from_context(llm, question, context_s1(sessions))
    elif system == "S2":
        context, session_ids = context_s2(sessions, question["question"], embed)
        out = answer_from_context(llm, question, context)
        out["recalled_sessions"] = session_ids
    elif system == "S3":
        out = answer_s3(llm, question, sessions, embed, use_cache=use_cache)
    elif system == "S4":
        out = answer_s3(llm, question, sessions, embed, past_chats=True, use_cache=use_cache)
    elif system == "S5":
        out = answer_s3(llm, question, sessions, embed, past_chats=True, auto_past=True, use_cache=use_cache)
    else:
        raise ValueError(f"unknown system {system!r}")
    # Answer time only. S3's replay is the background write in the app,
    # so it is reported apart (write_seconds).
    out["seconds"] = round(time.perf_counter() - start - (0 if out.get("write_reused", True) else out["write_seconds"]), 2)
    return out


def judge(llm: CountingLLM, question: dict, response: str) -> tuple[bool, str]:
    llm.stage = "judge"
    prompt = judge_prompt(question["question_type"], question["question"], question["answer"], response, is_abstention(question))
    message, _ = llm.chat([{"role": "user", "content": prompt}], model=JUDGE_MODEL, temperature=0)
    llm.stage = "answer"
    reply = message.content or ""
    return judged_correct(reply), reply


# --- report ---------------------------------------------------------------------


def print_report(rows: list[dict], llm: CountingLLM | None = None) -> None:
    summary = summarize(rows)
    types = sorted({r["question_type"] for r in rows})
    print("\n| system | answerable | 95% interval | abstention | " + " | ".join(types) + " | prompt tokens | median s |")
    print("|---|---|---|---|" + "---|" * len(types) + "---|---|")
    for system, s in summary.items():
        a = s["answerable"]
        low, high = wilson(a["correct"], a["n"])
        per_type = [s["by_type"].get(t) for t in types]
        cells = [f"{t['correct']}/{t['n']}" if t else "-" for t in per_type]
        absent = s["abstention"]
        print(
            f"| {system} | {a['correct']}/{a['n']} | {low * 100:.0f}-{high * 100:.0f}% | {absent['correct']}/{absent['n']} | "
            + " | ".join(cells)
            + f" | {s['mean_prompt_tokens']:.0f} | {s['median_seconds']:.1f} |"
        )
    for system in ("S3", "S4", "S5"):
        s3 = [r for r in rows if r["system"] == system]
        if not s3:
            continue
        print(
            f"\n{system} per question: {statistics.mean(r['memories'] for r in s3):.1f} memories stored, "
            f"{statistics.mean(r['write_calls'] for r in s3):.1f} write calls, "
            f"{statistics.mean(r['write_prompt_tokens'] for r in s3):.0f} write prompt tokens, "
            f"{statistics.median(r['write_seconds'] for r in s3):.1f} s median to write (background in the app)."
        )
    if llm is not None and llm.usage:
        unpriced = sorted({model for _, model in llm.usage if model not in PRICES})
        note = f", not counting {', '.join(unpriced)} (no price on file)" if unpriced else ""
        print(f"\nThis run's model calls (not counting answers reused from a previous run): ${llm.dollars():.2f}{note}")
        if llm.reasoning_tokens:
            print(f"  of the output tokens, {llm.reasoning_tokens} were hidden reasoning")
        for (stage, model), slot in sorted(llm.usage.items()):
            print(f"  {stage:7s} {model:12s} {slot['calls']:5d} calls  {slot['prompt_tokens']:9d} in  {slot['completion_tokens']:7d} out")


def main() -> None:
    global RECALL_K
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-type", type=int, default=5, help="questions sampled per question type")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--recall-k", type=int, default=RECALL_K, help="memories returned per recall (S3 to S5)")
    parser.add_argument("--types", default="", help="comma-separated question types to keep; default all")
    parser.add_argument("--systems", default="S0,S1,S2,S3")
    parser.add_argument("--out", required=True, help="directory for answers.jsonl and sample_ids.json")
    parser.add_argument(
        "--write-model", default=ANSWER_MODEL,
        help="model for S3's memory writes (extraction and consolidation); answers always use " + ANSWER_MODEL,
    )
    parser.add_argument("--answer-model", default=ANSWER_MODEL, help="model that answers (every system); the app's is " + ANSWER_MODEL)
    parser.add_argument("--workers", type=int, default=8, help="questions run at the same time")
    parser.add_argument(
        "--no-write-cache", action="store_true",
        help="write every question's memories afresh (for repeated runs that measure run-to-run variation)",
    )
    parser.add_argument("--no-judge", action="store_true", help="answer only; correct is left unset")
    args = parser.parse_args()

    import memory_jobs
    import providers
    from eval_key import use_eval_key

    print("OpenAI key: " + ("the evaluation key" if use_eval_key() else "the app's (no evaluation key stored)"), flush=True)

    if not ORACLE_FILE.exists():
        sys.exit(f"{ORACLE_FILE} is missing. Download longmemeval_oracle.json from the xiaowu0162/longmemeval-cleaned dataset.")
    RECALL_K = args.recall_k
    wanted_types = set(filter(None, args.types.split(",")))
    pool = [q for q in json.loads(ORACLE_FILE.read_text()) if not wanted_types or q["question_type"] in wanted_types]
    questions = sample_questions(pool, args.per_type, args.seed)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sample_ids.json").write_text(json.dumps([q["question_id"] for q in questions], indent=2))
    answers_path = out_dir / "answers.jsonl"
    rows = [json.loads(line) for line in answers_path.read_text().splitlines()] if answers_path.exists() else []
    done = {(r["question_id"], r["system"]) for r in rows}

    client = providers.openai_client(providers.OPENAI)
    llm = CountingLLM(client, write_model=args.write_model, answer_model=args.answer_model)  # the run's total
    systems = args.systems.split(",")

    def run_question(question: dict) -> tuple[list[dict], CountingLLM]:
        """Every wanted system for one question, on a counter of its own:
        questions run side by side, and a shared counter's stage would mix."""
        mine = CountingLLM(client, write_model=args.write_model, answer_model=args.answer_model)
        out_rows = []
        for system in systems:
            if (question["question_id"], system) in done:
                continue
            try:
                out = run_system(system, mine, question, memory_jobs.embed, use_cache=not args.no_write_cache)
            except Exception as e:  # one failed question must not lose the run
                print(f"[{question['question_id']} {system}] failed: {type(e).__name__}: {e}", flush=True)
                continue
            row = {
                "question_id": question["question_id"],
                "question_type": question["question_type"],
                "abstention": is_abstention(question),
                "system": system,
                "question": question["question"],
                "gold": question["answer"],
                "evidence_sessions": question["answer_session_ids"],
                "correct": None,
                **out,
            }
            if not args.no_judge:
                row["correct"], row["judge_reply"] = judge(mine, question, row["answer"])
            out_rows.append(row)
        return out_rows, mine

    # Systems of one question stay in order on one worker, so its memories
    # are written once and then reused, not written twice at the same time.
    with answers_path.open("a") as answers, ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(run_question, q) for q in questions]):
            new_rows, used = future.result()
            llm.add(used)
            for row in new_rows:
                answers.write(json.dumps(row) + "\n")
                rows.append(row)
                print(f"[{row['question_id']} {row['system']}] {row['seconds']}s correct={row['correct']}", flush=True)
            answers.flush()

    wanted = {q["question_id"] for q in questions}
    judged = [r for r in rows if r["question_id"] in wanted and r["correct"] is not None]
    if judged:
        print_report(judged, llm)


if __name__ == "__main__":
    main()
