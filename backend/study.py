"""Study artifacts — quizzes and flashcards (implementation-plan.md Step 11,
design spec §8). Plan: docs/plans/2026-10-03-study-artifacts.md.

Modelled on NotebookLM's Quiz and Flashcards: the student picks how many
(fewer / standard / more), a difficulty, and optionally a topic and which
sources to use; generation runs in the background.

What NotebookLM doesn't do and this does: every question and card is
written from one labelled passage of the course's own index, cites it the
way chat answers do, and is dropped if that passage doesn't support it. A
plausible but made-up quiz question is worse than none (§8): the student
studies the wrong thing and finds out in the exam.

Stored under courses/<id>/study/, so deleting a course deletes them too
(courses.delete_course).
"""

import csv
import io
import json
import math
import os
import random
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import lancedb

import generation
import indexing

KINDS = ("quiz", "flashcards")
COUNTS = {
    "quiz": {"fewer": 5, "standard": 10, "more": 15},
    "flashcards": {"fewer": 10, "standard": 20, "more": 30},
}
DIFFICULTIES = ("easy", "medium", "hard")

# About 30k tokens of course text per artifact: a few lectures' slides plus
# a recording fit whole; a full course gets narrowed by select_material.
# Leaves room in a 64k context (DeepSeek) for the instructions and the reply.
MATERIAL_BUDGET_CHARS = 120_000
# About the course rather than its subject: left out unless chosen by hand.
NOT_STUDIED_BY_DEFAULT = ("syllabus", "assignment")
MAX_TOPIC_CHARS = 500


# --- material ----------------------------------------------------------------


def _rows(db_path: Path, course_id: int) -> list[dict]:
    table = f"course_{course_id}"
    if not indexing.index_exists(db_path, table):
        return []
    arrow = lancedb.connect(str(db_path)).open_table(table).to_arrow()
    return arrow.select(["doc_id", "text", "metadata", "vector"]).to_pylist()


def _position(metadata: dict) -> float:
    """Where a chunk sits in its document, for putting a document back in order."""
    for key in ("page", "slide"):
        if metadata.get(key) is not None:
            return float(metadata[key])
    stamp = metadata.get("timestamp")
    if stamp:
        seconds = 0
        for part in str(stamp).split(":"):
            seconds = seconds * 60 + (int(part) if part.isdigit() else 0)
        return float(seconds)
    return 0.0


def material_chunks(db_path: Path, course_id: int, item_ids: list[str] | None = None) -> list[dict]:
    """The course's indexed text, one dict per chunk, each document's chunks
    together and in reading order. item_ids narrows it to those documents;
    without it, the syllabus and assignment pages are left out."""
    wanted = set(item_ids) if item_ids else None
    by_doc: dict[str, list[dict]] = {}
    for row in _rows(db_path, course_id):
        doc_id = row["doc_id"] or ""
        metadata = row["metadata"] or {}
        if wanted is not None and doc_id not in wanted:
            continue
        if wanted is None and metadata.get("item_type") in NOT_STUDIED_BY_DEFAULT:
            continue
        by_doc.setdefault(doc_id, []).append(
            {
                "text": row["text"] or "",
                "vector": row["vector"],
                "location": generation.location(metadata),
                "citation": generation.citation_for(metadata, doc_id),
                "_position": _position(metadata),
            }
        )
    chunks = []
    for doc_chunks in by_doc.values():
        # sorted() is stable: chunks split from one page keep their order.
        for chunk in sorted(doc_chunks, key=lambda c: c["_position"]):
            del chunk["_position"]
            chunks.append(chunk)
    return chunks


def _canvas_item_id(item: dict) -> str | None:
    """A module item's id as course_sync indexes it (ref_doc_id)."""
    kind = item.get("type")
    if kind == "File" and item.get("content_id") is not None:
        return f"file:{item['content_id']}"
    if kind == "Page" and item.get("page_url"):
        return f"page:{item['page_url']}"
    if kind == "Assignment" and item.get("content_id") is not None:
        return f"assignment:{item['content_id']}"
    return None


def _canvas_groups(structure: list[dict]) -> dict[str, tuple[int, str, dict]]:
    """item id → (position in Canvas, group, the module item). The group is
    the nearest SubHeader above the item ("Week 02 - Literature Review"),
    else its module."""
    groups: dict[str, tuple[int, str, dict]] = {}
    for module in structure:
        heading = module.get("name") or "Module"
        for item in module.get("items") or []:
            if item.get("type") == "SubHeader":
                heading = item.get("title") or heading
                continue
            item_id = _canvas_item_id(item)
            if item_id and item_id not in groups:
                groups[item_id] = (len(groups), heading, item)
    return groups


def _why_not_indexed(name: str) -> str:
    """Why a module file has nothing in the index."""
    from course_sync import SUPPORTED_FILE_SUFFIXES

    suffix = Path(name).suffix.lower()
    if not suffix:
        return "Second Mind can't read this kind of file"
    if suffix not in SUPPORTED_FILE_SUFFIXES:
        return f"Second Mind can't read {suffix} files"
    # A scanned PDF OCR found nothing in, or a file added since the last sync.
    return "No readable text found, or not synced yet"


def _fallback_group(source_type: str) -> str:
    if source_type in ("transcript", "notes"):
        return "Recorded sessions"
    if source_type in NOT_STUDIED_BY_DEFAULT:
        return "Syllabus and assignments"
    return "Course material"


def list_sources(db_path: Path, course_id: int, structure: list[dict] | None = None) -> list[dict]:
    """Each indexed document once, for choosing which to study from, plus the
    module files that couldn't be indexed (with "unavailable" saying why). With
    Canvas's module structure, grouped and ordered the way Canvas shows them
    (by week, where the course has week headings); what Canvas doesn't list
    (recordings, the syllabus) comes after, grouped by kind."""
    sources: dict[str, dict] = {}
    for row in _rows(db_path, course_id):
        doc_id = row["doc_id"] or ""
        metadata = row["metadata"] or {}
        if doc_id not in sources:
            sources[doc_id] = {
                "item_id": doc_id,
                "source": metadata.get("source") or doc_id,
                "source_type": metadata.get("item_type") or "file",
                "chunks": 0,
                "unavailable": None,
            }
        sources[doc_id]["chunks"] += 1
    canvas_groups = _canvas_groups(structure or [])
    # Module files with nothing indexed are listed too, greyed out with the
    # reason, so the list shows everything the course's modules hold.
    for item_id, (_, _, item) in canvas_groups.items():
        if item.get("type") == "File" and item_id not in sources:
            name = item.get("title") or item_id
            sources[item_id] = {
                "item_id": item_id,
                "source": name,
                "source_type": "file",
                "chunks": 0,
                "unavailable": _why_not_indexed(name),
            }
    fallback_order = ["Course material", "Syllabus and assignments", "Recorded sessions"]

    def place(source: dict) -> tuple[int, int]:
        if source["item_id"] in canvas_groups:
            return 0, canvas_groups[source["item_id"]][0]
        return 1, fallback_order.index(source["group"])

    for source in sources.values():
        known = canvas_groups.get(source["item_id"])
        source["group"] = known[1] if known else _fallback_group(source["source_type"])
    # sorted() is stable, so documents within a fallback group keep index order.
    return sorted(sources.values(), key=place)


def _similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def select_material(
    chunks: list[dict], budget_chars: int = MATERIAL_BUDGET_CHARS, query_vector: list[float] | None = None
) -> list[dict]:
    """All of it if it fits. Otherwise, with a topic, the chunks closest to
    it; without one, an even spread, so a quiz on a whole course doesn't
    only cover its first lectures. Either way back in reading order."""
    if sum(len(c["text"]) for c in chunks) <= budget_chars:
        return chunks
    picked: set[int] = set()
    used = 0
    if query_vector is not None:
        ranked = sorted(range(len(chunks)), key=lambda i: (-_similarity(chunks[i]["vector"], query_vector), i))
        for i in ranked:
            if used + len(chunks[i]["text"]) <= budget_chars:
                picked.add(i)
                used += len(chunks[i]["text"])
    else:
        total = sum(len(c["text"]) for c in chunks)
        stride = math.ceil(total / budget_chars)
        for offset in range(stride):
            for i in range(offset, len(chunks), stride):
                if used + len(chunks[i]["text"]) <= budget_chars:
                    picked.add(i)
                    used += len(chunks[i]["text"])
            if used >= budget_chars * 0.95:
                break
    return [chunks[i] for i in sorted(picked)]


# --- generation --------------------------------------------------------------

_COMMON_RULES = """\
- Use only the material below. No outside facts, even true ones.
- Each item comes from one passage of the material. Put that passage's label in "source", e.g. "c12". The passage alone must be enough to know the answer.
- Write about the course's subject matter, not about the course itself (who teaches it, due dates, grading, office hours, policies, assignment instructions), unless the focus asks for that.
- The item must stand on its own like an exam question: don't mention "the material", "the passage", "the course", "the lecture" or slide numbers.
- Cover different ideas across the material (or across the focus). No two items about the same fact.
- Write in the language of the material."""

_QUIZ_SYSTEM = f"""You write a multiple-choice practice quiz for a student from their own course material.

Rules:
{_COMMON_RULES}
- Exactly 4 options per question and exactly one correct. Wrong options should be plausible to someone who half-knows the material, ideally related ideas from the same material, but clearly wrong to someone who knows it. No "all of the above" or "none of the above".
- Every option gets a rationale of one or two sentences: for the correct option why it is right, for a wrong one why it is wrong.
- A hint that points toward the answer without giving it away.

Reply with JSON only:
{{"title": "the quiz's topic, at most 6 words", "questions": [{{"question": "...", "options": [{{"text": "...", "correct": true, "rationale": "..."}}, ...], "hint": "...", "source": "c1"}}]}}"""

_FLASHCARD_SYSTEM = f"""You write flashcards for a student from their own course material, to memorize key terms, important ideas and core concepts.

Rules:
{_COMMON_RULES}
- The front is a term, a concept or a short question. The back answers it in at most two sentences.

Reply with JSON only:
{{"title": "the deck's topic, at most 6 words", "cards": [{{"front": "...", "back": "...", "source": "c1"}}]}}"""

_DIFFICULTY = {
    "quiz": {
        "easy": "recall: definitions, terms and facts stated directly in the material",
        "medium": "understanding: explain, compare, or apply an idea to a short example",
        "hard": "reasoning: apply ideas to new situations, combine two ideas, or tell closely related concepts apart; wrong options are close calls",
    },
    "flashcards": {
        "easy": "key terms and their definitions",
        "medium": "concepts, how they work and how they relate to each other",
        "hard": "subtle distinctions, conditions and trade-offs: when, why and why not",
    },
}

_CHECK_SYSTEM = """You check study items against the passage each was written from.

An item is supported only if its passage alone establishes the answer. For a quiz question, the passage must show the option marked correct is right, and no other option may also be right. For a flashcard, the passage must state what the back says. An item that brings in a subject its passage doesn't discuss is not supported, even if each part is true somewhere.

Reply with JSON only: {"supported": [the numbers of the supported items]}"""


def item_count(kind: str, count: str) -> int:
    return COUNTS[kind][count]


def check_options(kind: str, options: dict) -> dict:
    """The options a request may carry, defaults filled in. ValueError when one is invalid."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    count = options.get("count", "standard")
    if count not in COUNTS[kind]:
        raise ValueError("count must be fewer, standard or more")
    difficulty = options.get("difficulty", "medium")
    if difficulty not in DIFFICULTIES:
        raise ValueError("difficulty must be easy, medium or hard")
    topic = options.get("topic") or ""
    if not isinstance(topic, str) or len(topic) > MAX_TOPIC_CHARS:
        raise ValueError(f"topic must be text of at most {MAX_TOPIC_CHARS} characters")
    item_ids = options.get("item_ids") or None
    if item_ids is not None and not (isinstance(item_ids, list) and all(isinstance(i, str) for i in item_ids)):
        raise ValueError("item_ids must be a list of source ids")
    return {"count": count, "difficulty": difficulty, "topic": topic.strip(), "item_ids": item_ids}


def _format_material(labelled: dict[str, dict]) -> str:
    lines = []
    current = None
    for label, chunk in labelled.items():
        source = chunk["citation"]["label"].split(" · ")[0]
        if chunk["citation"]["item_id"] != current:
            current = chunk["citation"]["item_id"]
            lines.append(f"\n## {source}")
        where = f" ({chunk['location']})" if chunk["location"] else ""
        lines.append(f"[{label}]{where} {chunk['text']}")
    return "\n".join(lines).strip()


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_question(raw) -> dict | None:
    if not isinstance(raw, dict) or not _text(raw.get("question")):
        return None
    options = raw.get("options")
    if not isinstance(options, list) or len(options) != 4:
        return None
    cleaned = []
    for option in options:
        if not isinstance(option, dict) or not _text(option.get("text")):
            return None
        cleaned.append({"text": _text(option["text"]), "correct": option.get("correct") is True, "rationale": _text(option.get("rationale"))})
    if sum(o["correct"] for o in cleaned) != 1 or len({o["text"].lower() for o in cleaned}) != 4:
        return None
    return {"question": _text(raw["question"]), "options": cleaned, "hint": _text(raw.get("hint"))}


def _clean_card(raw) -> dict | None:
    if not isinstance(raw, dict) or not _text(raw.get("front")) or not _text(raw.get("back")):
        return None
    return {"front": _text(raw["front"]), "back": _text(raw["back"])}


def _describe_for_check(kind: str, number: int, item: dict) -> str:
    lines = [f"Item {number}", f"Passage: {item['passage']}"]
    if kind == "quiz":
        lines.append(f"Question: {item['question']}")
        for letter, option in zip("ABCD", item["options"]):
            lines.append(f"{letter}) {option['text']}" + (" (marked correct)" if option["correct"] else ""))
    else:
        lines += [f"Front: {item['front']}", f"Back: {item['back']}"]
    return "\n".join(lines)


_FILLER = {"a", "an", "the", "some", "is", "are", "what", "of", "in", "for", "to", "and", "does", "do"}


def _words(text: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"\w+", text.lower()) if w not in _FILLER)


def _is_repeat(words: frozenset[str], seen: list[frozenset[str]]) -> bool:
    """Same question in other words: "What are some ethical metrics…" and
    "What are the ethical metrics…" share all their content words."""
    return any(len(words & other) >= 0.8 * max(len(words), len(other), 1) for other in seen)


MAX_ROUNDS = 2


def _write_round(kind, labelled, *, asked, difficulty, topic, avoid, llm) -> tuple[str, list]:
    noun = "questions" if kind == "quiz" else "flashcards"
    focus = topic or "the whole material, covering its main ideas"
    request = f"Write {asked} {noun}.\nDifficulty: {difficulty}, {_DIFFICULTY[kind][difficulty]}.\nFocus: {focus}\n"
    if avoid:
        request += "\nAlready written, so don't repeat these or ask about the same facts:\n" + "\n".join(f"- {a}" for a in avoid) + "\n"
    reply = llm.complete_json(
        [
            {"role": "system", "content": _QUIZ_SYSTEM if kind == "quiz" else _FLASHCARD_SYSTEM},
            {"role": "user", "content": f"{request}\nMaterial:\n{_format_material(labelled)}"},
        ],
        temperature=0.7,
    )
    if not isinstance(reply, dict):
        return "", []
    raw_items = reply.get("questions" if kind == "quiz" else "cards")
    return _text(reply.get("title")), raw_items if isinstance(raw_items, list) else []


def _check(kind, items, llm) -> list[int] | None:
    """1-based numbers of the items their passage supports, or None if the check failed."""
    verdict = llm.complete_json(
        [
            {"role": "system", "content": _CHECK_SYSTEM},
            {"role": "user", "content": "\n\n".join(_describe_for_check(kind, n, it) for n, it in enumerate(items, 1))},
        ]
    )
    supported = verdict.get("supported") if isinstance(verdict, dict) else None
    if not isinstance(supported, list):
        return None
    return [n for n in supported if isinstance(n, int)]


def generate(
    kind: str, chunks: list[dict], *, count: int, difficulty: str, topic: str, llm, rng: random.Random
) -> dict:
    """Write, validate and check one quiz or deck. Returns {title, items, stats,
    dropped}. When the check leaves too few, a second round asks for the rest;
    items can still end up fewer than count.

    dropped keeps what was thrown away and why, for grading the check itself
    (the artifact groundedness evaluation, design spec §12)."""
    labelled = {f"c{i + 1}": chunk for i, chunk in enumerate(chunks)}
    stats = {"generated": 0, "unsourced": 0, "malformed": 0, "unsupported": 0, "checked": True, "rounds": 0}
    items: list[dict] = []
    dropped: list[dict] = []
    # Only accepted items count as already written: one dropped for citing
    # the wrong passage may come back with the right one, which is what the
    # second round is for.
    accepted: list[frozenset[str]] = []
    title = ""

    for _ in range(MAX_ROUNDS):
        missing = count - len(items)
        stats["rounds"] += 1
        round_title, raw_items = _write_round(
            kind,
            labelled,
            # Spares for what the check drops: on a real course, gpt-4o-mini's
            # flashcards lost about half, mostly to citing the wrong passage.
            asked=missing + max(2, math.ceil(missing / 2)),
            difficulty=difficulty,
            topic=topic,
            avoid=[it["question"] if kind == "quiz" else it["front"] for it in items],
            llm=llm,
        )
        title = title or round_title
        stats["generated"] += len(raw_items)

        fresh, fresh_words = [], []
        for raw in raw_items:
            item = _clean_question(raw) if kind == "quiz" else _clean_card(raw)
            words = _words(item["question"] if kind == "quiz" else item["front"]) if item else frozenset()
            if item is None or _is_repeat(words, accepted + fresh_words):
                stats["malformed"] += 1
                continue
            chunk = labelled.get(_text(raw.get("source")))
            if chunk is None:
                stats["unsourced"] += 1
                dropped.append({"reason": "unsourced", "source": _text(raw.get("source")), **item})
                continue
            fresh.append({**item, "citation": chunk["citation"], "passage": chunk["text"]})
            fresh_words.append(words)

        if fresh:
            supported = _check(kind, fresh, llm)
            if supported is None:
                # The check itself failed: keep the items rather than lose the
                # whole quiz, and say so in the stats.
                stats["checked"] = False
            else:
                keep = set(supported)
                for n, it in enumerate(fresh, 1):
                    if n not in keep:
                        stats["unsupported"] += 1
                        dropped.append({"reason": "unsupported", **it})
                fresh_words = [w for n, w in enumerate(fresh_words, 1) if n in keep]
                fresh = [it for n, it in enumerate(fresh, 1) if n in keep]
        items += fresh
        accepted += fresh_words
        # Another round only helps when this one produced something usable.
        if len(items) >= count or not fresh:
            break

    if kind == "quiz":
        # Models put the right answer first far more often than chance.
        for item in items:
            rng.shuffle(item["options"])
    return {"title": title, "items": items[:count], "stats": stats, "dropped": dropped}


# --- storage and background runs --------------------------------------------

_lock = threading.Lock()
_idle = threading.Condition(_lock)
_RUNNING: set[str] = set()

_DEFAULT_TITLE = {"quiz": "Quiz", "flashcards": "Flashcards"}


def _dir(sm_home: Path, course_id: int) -> Path:
    return sm_home / "courses" / str(course_id) / "study"


def _path(sm_home: Path, course_id: int, artifact_id: str) -> Path:
    return _dir(sm_home, course_id) / f"{artifact_id}.json"


def _write(path: Path, data: dict) -> None:
    # Through a temp file, so a crash mid-write can't leave half a JSON file.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("status") == "generating" and data.get("id") not in _RUNNING:
        # Saved as generating by a backend that has since stopped.
        data = {**data, "status": "error", "error": "Generation was interrupted when the app closed. Try again."}
    return data


def _summary(artifact: dict) -> dict:
    return {
        "id": artifact["id"],
        "kind": artifact["kind"],
        "title": artifact["title"],
        "status": artifact["status"],
        "error": artifact.get("error"),
        "created_at": artifact["created_at"],
        "options": artifact["options"],
        "count": len(artifact.get("items") or []),
    }


def list_artifacts(sm_home: Path, course_id: int) -> list[dict]:
    """Newest first."""
    directory = _dir(sm_home, course_id)
    if not directory.is_dir():
        return []
    artifacts = [a for a in (_read(p) for p in directory.glob("*.json")) if a]
    return [_summary(a) for a in sorted(artifacts, key=lambda a: a["created_at"], reverse=True)]


def get_artifact(sm_home: Path, course_id: int, artifact_id: str) -> dict | None:
    return _read(_path(sm_home, course_id, artifact_id))


def delete_artifact(sm_home: Path, course_id: int, artifact_id: str) -> None:
    _path(sm_home, course_id, artifact_id).unlink(missing_ok=True)


def export_csv(sm_home: Path, course_id: int, artifact_id: str, out_dir: Path) -> Path:
    """Write a quiz or deck to out_dir as CSV (NotebookLM's "Download"), never
    over an existing file. KeyError if there's no such artifact."""
    artifact = get_artifact(sm_home, course_id, artifact_id)
    if artifact is None:
        raise KeyError(artifact_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if artifact["kind"] == "quiz":
        writer.writerow(["Question", "A", "B", "C", "D", "Answer", "Source"])
        for q in artifact["items"]:
            answer = next(letter for letter, o in zip("ABCD", q["options"]) if o["correct"])
            writer.writerow([q["question"], *(o["text"] for o in q["options"]), answer, q["citation"]["label"]])
    else:
        writer.writerow(["Front", "Back", "Source"])
        removed = set((artifact.get("progress") or {}).get("removed") or [])
        for i, card in enumerate(artifact["items"]):
            if i not in removed:
                writer.writerow([card["front"], card["back"], card["citation"]["label"]])
    stem = re.sub(r'[\\/:*?"<>|]+', " ", artifact["title"]).strip() or _DEFAULT_TITLE[artifact["kind"]]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}.csv"
    n = 2
    while path.exists():
        path = out_dir / f"{stem} ({n}).csv"
        n += 1
    path.write_text(buffer.getvalue(), encoding="utf-8-sig")  # the BOM lets Excel read it as UTF-8
    return path


def save_progress(sm_home: Path, course_id: int, artifact_id: str, progress: dict) -> None:
    """Where the student is: answers, Got it / Missed it, removed cards. The
    app decides its shape; this only keeps it. KeyError if there's no such artifact."""
    path = _path(sm_home, course_id, artifact_id)
    with _lock:
        artifact = _read(path)
        if artifact is None:
            raise KeyError(artifact_id)
        _write(path, {**artifact, "progress": progress})


def start(
    sm_home: Path,
    db_path: Path,
    course_id: int,
    kind: str,
    options: dict,
    *,
    llm,
    embed: Callable[[str], list[float]],
    describe_error: Callable[[Exception], str] = str,
) -> dict:
    """Save a "generating" artifact and write it in a background thread.
    options must already have been through check_options."""
    artifact_id = f"{'quiz' if kind == 'quiz' else 'cards'}-{uuid.uuid4().hex[:12]}"
    artifact = {
        "id": artifact_id,
        "kind": kind,
        "title": options["topic"][:60] or _DEFAULT_TITLE[kind],
        "status": "generating",
        "error": None,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "options": options,
        "items": [],
        "stats": None,
        "progress": {},
    }
    path = _path(sm_home, course_id, artifact_id)
    with _lock:
        _RUNNING.add(artifact_id)
        _write(path, artifact)

    def run():
        result = {"status": "error", "error": None}
        try:
            chunks = material_chunks(db_path, course_id, options["item_ids"])
            if not chunks:
                result["error"] = "There's no indexed material to study from yet. Sync the course or record a session first."
            else:
                over = sum(len(c["text"]) for c in chunks) > MATERIAL_BUDGET_CHARS
                query = embed(options["topic"]) if options["topic"] and over else None
                written = generate(
                    kind,
                    select_material(chunks, MATERIAL_BUDGET_CHARS, query),
                    count=item_count(kind, options["count"]),
                    difficulty=options["difficulty"],
                    topic=options["topic"],
                    llm=llm,
                    rng=random.Random(),
                )
                if written["items"]:
                    result = {
                        "status": "done",
                        "error": None,
                        "items": written["items"],
                        "stats": written["stats"],
                        "dropped": written["dropped"],
                    }
                    if written["title"]:
                        result["title"] = written["title"]
                else:
                    result["stats"] = written["stats"]
                    result["dropped"] = written["dropped"]
                    result["error"] = (
                        "Couldn't write anything the course material supports. Try another topic or more sources."
                    )
        except Exception as e:  # noqa: BLE001 — a failed run is saved, never raised into a dead thread
            result["error"] = describe_error(e)
        finally:
            with _lock:
                saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
                if saved is not None:  # not deleted while it ran
                    _write(path, {**saved, **result})
                _RUNNING.discard(artifact_id)
                _idle.notify_all()

    threading.Thread(target=run, name=f"study-{artifact_id}", daemon=True).start()
    return _summary(artifact)


def wait_idle(timeout: float) -> bool:
    """Tests: wait for every background run to finish."""
    with _lock:
        return _idle.wait_for(lambda: not _RUNNING, timeout)
