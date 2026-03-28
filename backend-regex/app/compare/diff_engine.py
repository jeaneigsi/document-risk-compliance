"""Lexical diff engine abstractions for the compare pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import re
from typing import Iterable


TOKEN_RE = re.compile(r"\S+|\s+")


@dataclass
class DiffOp:
    op: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return {"op": self.op, "text": self.text}


class LexicalDiffEngine:
    """Abstract diff engine interface."""

    def diff_words(self, text_a: str, text_b: str) -> list[dict[str, str]]:
        raise NotImplementedError

    def classify_change(self, text_a: str, text_b: str, diff_ops: Iterable[dict[str, str]]) -> str:
        full_left = text_a or ""
        full_right = text_b or ""
        combined_delete = "".join(item["text"] for item in diff_ops if item["op"] == "delete")
        combined_insert = "".join(item["text"] for item in diff_ops if item["op"] == "insert")
        number_re = re.compile(r"\b\d[\d\s.,]*(?:€|eur|usd|\$|mad)?\b", re.IGNORECASE)
        date_re = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{2}[/-]\d{2})\b")
        ref_re = re.compile(r"\b[A-Z]{1,6}[-_/]?\d+[A-Z0-9._/-]*\b", re.IGNORECASE)
        if number_re.search(full_left) and number_re.search(full_right) and full_left.strip() != full_right.strip():
            return "numeric_change"
        if date_re.search(full_left) and date_re.search(full_right) and full_left.strip() != full_right.strip():
            return "date_change"
        if ref_re.search(full_left) and ref_re.search(full_right) and full_left.strip() != full_right.strip():
            return "reference_change"
        if number_re.search(combined_delete) and number_re.search(combined_insert):
            return "numeric_change"
        if date_re.search(combined_delete) and date_re.search(combined_insert):
            return "date_change"
        if ref_re.search(combined_delete) and ref_re.search(combined_insert):
            return "reference_change"
        if _contains_clause_signal(text_a) or _contains_clause_signal(text_b):
            return "clause_change"
        return "text_change"


class DiffMatchPatchEngine(LexicalDiffEngine):
    """Word-level diff powered by diff-match-patch when available."""

    def __init__(self) -> None:
        self._impl = None
        try:
            from diff_match_patch import diff_match_patch  # type: ignore

            self._impl = diff_match_patch()
        except Exception:
            self._impl = None

    def diff_words(self, text_a: str, text_b: str) -> list[dict[str, str]]:
        tokens_a = _tokenize(text_a)
        tokens_b = _tokenize(text_b)
        if self._impl is None:
            return _refine_replacements(_difflib_ops(tokens_a, tokens_b))

        chars_a, chars_b, token_array = _tokens_to_chars(tokens_a, tokens_b)
        diffs = self._impl.diff_main(chars_a, chars_b, False)
        self._impl.diff_cleanupSemantic(diffs)
        ops: list[DiffOp] = []
        for op, payload in diffs:
            text = "".join(token_array[ord(char)] for char in payload)
            mapped = "equal" if op == 0 else "insert" if op == 1 else "delete"
            if text:
                ops.append(DiffOp(op=mapped, text=text))
        return _refine_replacements(_merge_adjacent(ops))


def build_diff_engine() -> LexicalDiffEngine:
    return DiffMatchPatchEngine()


def _contains_clause_signal(text: str) -> bool:
    lowered = (text or "").lower()
    return any(token in lowered for token in ("shall", "must", "will", "may not", "doit", "devra", "notice", "termination"))


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return TOKEN_RE.findall(text)


def _tokens_to_chars(tokens_a: list[str], tokens_b: list[str]) -> tuple[str, str, list[str]]:
    token_array = [""]
    token_to_char: dict[str, str] = {}

    def encode(tokens: list[str]) -> str:
        chars: list[str] = []
        for token in tokens:
            char = token_to_char.get(token)
            if char is None:
                token_array.append(token)
                char = chr(len(token_array) - 1)
                token_to_char[token] = char
            chars.append(char)
        return "".join(chars)

    return encode(tokens_a), encode(tokens_b), token_array


def _difflib_ops(tokens_a: list[str], tokens_b: list[str]) -> list[dict[str, str]]:
    matcher = difflib.SequenceMatcher(a=tokens_a, b=tokens_b, autojunk=False)
    ops: list[DiffOp] = []
    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        if opcode == "equal":
            ops.append(DiffOp("equal", "".join(tokens_a[i1:i2])))
        elif opcode == "delete":
            ops.append(DiffOp("delete", "".join(tokens_a[i1:i2])))
        elif opcode == "insert":
            ops.append(DiffOp("insert", "".join(tokens_b[j1:j2])))
        elif opcode == "replace":
            deleted = "".join(tokens_a[i1:i2])
            inserted = "".join(tokens_b[j1:j2])
            if deleted:
                ops.append(DiffOp("delete", deleted))
            if inserted:
                ops.append(DiffOp("insert", inserted))
    return _merge_adjacent(ops)


def _merge_adjacent(ops: Iterable[DiffOp]) -> list[dict[str, str]]:
    merged: list[DiffOp] = []
    for op in ops:
        if not op.text:
            continue
        if merged and merged[-1].op == op.op:
            merged[-1].text += op.text
        else:
            merged.append(DiffOp(op=op.op, text=op.text))
    return [item.to_dict() for item in merged]


def _refine_replacements(ops: list[dict[str, str]]) -> list[dict[str, str]]:
    """Refine local delete/insert pairs to char-level when they are near-matches.

    The compare UI is issue-driven and word-first, but single-letter edits inside a
    token should still be visible when the aligned pair is correct.
    """
    refined: list[DiffOp] = []
    index = 0
    while index < len(ops):
        current = ops[index]
        nxt = ops[index + 1] if index + 1 < len(ops) else None
        if (
            nxt
            and current.get("op") == "delete"
            and nxt.get("op") == "insert"
            and _should_refine_replace(current.get("text", ""), nxt.get("text", ""))
        ):
            refined.extend(_char_level_replace(current["text"], nxt["text"]))
            index += 2
            continue
        refined.append(DiffOp(op=current["op"], text=current["text"]))
        index += 1
    return _merge_adjacent(refined)


def _should_refine_replace(delete_text: str, insert_text: str) -> bool:
    left = delete_text.strip()
    right = insert_text.strip()
    if not left or not right:
        return False
    if "\n" in left or "\n" in right:
        return False
    if max(len(left), len(right)) > 80:
        return False
    if len(left.split()) > 6 or len(right.split()) > 6:
        return False
    similarity = difflib.SequenceMatcher(a=left, b=right, autojunk=False).ratio()
    return similarity >= 0.45


def _char_level_replace(delete_text: str, insert_text: str) -> list[DiffOp]:
    matcher = difflib.SequenceMatcher(a=delete_text, b=insert_text, autojunk=False)
    rows: list[DiffOp] = []
    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        if opcode == "equal":
            rows.append(DiffOp("equal", delete_text[i1:i2]))
        elif opcode == "delete":
            rows.append(DiffOp("delete", delete_text[i1:i2]))
        elif opcode == "insert":
            rows.append(DiffOp("insert", insert_text[j1:j2]))
        elif opcode == "replace":
            deleted = delete_text[i1:i2]
            inserted = insert_text[j1:j2]
            if deleted:
                rows.append(DiffOp("delete", deleted))
            if inserted:
                rows.append(DiffOp("insert", inserted))
    return rows
