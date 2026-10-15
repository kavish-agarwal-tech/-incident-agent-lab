"""Inspectable chunking strategies and lexical retrieval, without embeddings.

All entry points consume already-authorized documents. Never use a public index
to fetch parent text without checking the parent document's access labels.
"""

from dataclasses import asdict, dataclass
import re


@dataclass(frozen=True)
class Chunk:
    id: str
    document_id: str
    scope: dict
    start: int
    end: int
    text: str
    parent_id: str | None = None
    parent_start: int | None = None
    parent_end: int | None = None


STRATEGIES = ("fixed", "sliding", "recursive", "structure", "semantic_mock", "parent_child")


def word_windows(text, start, end, size, overlap=0):
    words = list(re.finditer(r"\S+", text[start:end]))
    for index in range(0, len(words), size - overlap):
        last = min(index + size, len(words)) - 1
        yield start + words[index].start(), start + words[last].end()
        if last == len(words) - 1:
            break


def section_spans(text):
    boundaries = [m.start() for m in re.finditer(r"(?m)^#{1,6} ", text)]
    if not boundaries or boundaries[0] != 0:
        boundaries.insert(0, 0)
    boundaries.append(len(text))
    return [(a, b) for a, b in zip(boundaries, boundaries[1:]) if text[a:b].strip()]


def recursive_spans(text, start, end, size, separators=("\n\n", "\n", ". ")):
    if len(text[start:end].split()) <= size:
        return [(start, end)]
    if not separators:
        return list(word_windows(text, start, end, size))
    separator, *rest = separators
    parts = list(re.finditer(re.escape(separator), text[start:end]))
    if not parts:
        return recursive_spans(text, start, end, size, rest)
    spans, cursor = [], start
    for match in parts:
        boundary = start + match.end()
        spans.extend(recursive_spans(text, cursor, boundary, size, rest))
        cursor = boundary
    if cursor < end:
        spans.extend(recursive_spans(text, cursor, end, size, rest))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def chunk_document(document, strategy, size=35, overlap=8):
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy}")
    if size < 1 or not 0 <= overlap < size:
        raise ValueError("Require size > 0 and 0 <= overlap < size")
    text = document["text"]
    parents = section_spans(text)
    if strategy in {"fixed", "sliding"}:
        spans = [(a, b, None) for a, b in word_windows(
            text, 0, len(text), size, overlap if strategy == "sliding" else 0)]
    elif strategy == "recursive":
        spans = [(a, b, None) for a, b in recursive_spans(text, 0, len(text), size)]
    elif strategy == "structure":
        spans = [(a, b, None) for a, b in parents]
    elif strategy == "semantic_mock":
        # Topic boundaries supplied by the fixture author; no semantic model is run.
        spans = [(a, b, None) for a, b in document.get("topic_spans", parents)]
    else:
        spans = [(a, b, parent) for parent, (start, end) in enumerate(parents)
                 for a, b in word_windows(text, start, end, size)]
    chunks = []
    for index, (start, end, parent) in enumerate(spans):
        parent_span = parents[parent] if parent is not None else (None, None)
        chunks.append(Chunk(
            id=f"{document['id']}:{strategy}:{index}", document_id=document["id"],
            scope=dict(document["scope"]), start=start, end=end, text=text[start:end],
            parent_id=f"{document['id']}:section:{parent}" if parent is not None else None,
            parent_start=parent_span[0], parent_end=parent_span[1],
        ))
    return chunks


def retrieve(documents, strategy, query, top_k=2, size=35):
    """Caller has authorized every document. Scope metadata survives chunking."""
    tokens = lambda value: set(re.findall(r"[a-z0-9]+", value.lower()))
    query_words = tokens(query)
    ranked = []
    by_id = {doc["id"]: doc for doc in documents}
    for document in documents:
        for chunk in chunk_document(document, strategy, size):
            score = len(query_words & tokens(chunk.text))
            if score:
                ranked.append((score, chunk.id, chunk))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    results, seen = [], set()
    for score, _, chunk in ranked:
        item = asdict(chunk)
        key = chunk.parent_id or chunk.id
        if key in seen:
            continue
        seen.add(key)
        if chunk.parent_id:
            source = by_id[chunk.document_id]["text"]
            item.update(text=source[chunk.parent_start:chunk.parent_end],
                        start=chunk.parent_start, end=chunk.parent_end)
        results.append({**item, "score": score})
        if len(results) == top_k:
            break
    return results


def event_chunks(evidence, mode="time", window=60):
    if mode not in {"time", "trace"} or window <= 0:
        raise ValueError("Choose time/trace mode and a positive window")
    groups = {}
    for index, record in enumerate(evidence["records"]):
        key = record["time"] // window if mode == "time" else record["trace"]
        groups.setdefault(str(key), []).append({"record_index": index, **record})
    return [{"id": f"{evidence['id']}:{mode}:{key}", "document_id": evidence["id"],
             "scope": evidence["scope"], "records": records}
            for key, records in groups.items()]
