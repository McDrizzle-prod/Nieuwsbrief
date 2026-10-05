"""Onderwerpen (EBW, EUDI, ...) en MOZa-thema's herkennen en een score toekennen."""

from __future__ import annotations

import re
from dataclasses import dataclass

DIRECTE_MOZA_THEMAS = {"berichten", "identiteit", "verplichtingen"}
PRIORITEIT_BONUS = {1: 2, 2: 1}


@dataclass
class Rule:
    id: str
    naam: str
    gewicht: int
    patterns: list[re.Pattern]


def compile_term(term: str) -> re.Pattern:
    """Zoekterm uit onderwerpen.yaml omzetten naar een reguliere expressie."""
    term = term.strip()
    if term.startswith("re:"):
        return re.compile(term[3:], re.IGNORECASE)
    prefix = term.endswith("*")
    core = term.rstrip("*")
    body = re.escape(core).replace(r"\ ", r"[\s\-]+")
    acronym = not any(c.islower() for c in core)
    if prefix:
        tail = r"[\w\-]*"
    elif acronym:
        tail = ""
    else:
        tail = r"(?:s|es)?"
    pattern = rf"(?<![\w]){body}{tail}(?![\w])"
    return re.compile(pattern, 0 if acronym else re.IGNORECASE)


def build_rules(entries: list[dict]) -> list[Rule]:
    return [
        Rule(e["id"], e["naam"], int(e.get("gewicht", 1)), [compile_term(t) for t in e.get("termen", [])])
        for e in entries
    ]


def match_rules(text: str, rules: list[Rule]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for rule in rules:
        found = []
        for pattern in rule.patterns:
            match = pattern.search(text)
            if match:
                found.append(" ".join(match.group(0).split()))
        if found:
            unique = sorted({f.lower(): f for f in found}.values(), key=str.lower)
            hits[rule.id] = unique[:6]
    return hits


class Classifier:
    def __init__(self, onderwerpen_config: dict):
        self.topic_rules = build_rules(onderwerpen_config["onderwerpen"])
        self.theme_rules = build_rules(onderwerpen_config["moza_themas"])
        self.topic_weight = {r.id: r.gewicht for r in self.topic_rules}
        self.theme_weight = {r.id: r.gewicht for r in self.theme_rules}

    def excerpt(self, text: str, max_sentences: int = 3, limit: int = 700, window: int = 260) -> str:
        """Zinnen uit een lange tekst waarin een onderwerp wordt genoemd.

        Bij een heel lange 'zin' (bijv. een agenda zonder punten) wordt alleen het stuk
        rond de gevonden term getoond.
        """
        parts = []
        for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
            sentence = " ".join(sentence.split())
            match = next((m for r in self.topic_rules for p in r.patterns if (m := p.search(sentence))), None)
            if match is None:
                continue
            if len(sentence) > window:
                start = max(0, match.start() - window // 3)
                end = min(len(sentence), start + window)
                piece = sentence[start:end]
                if start > 0:
                    piece = "… " + piece.split(" ", 1)[-1]
                if end < len(sentence):
                    piece = piece.rsplit(" ", 1)[0] + " …"
                sentence = piece
            parts.append(sentence)
            if len(parts) == max_sentences:
                break
        fragment = " … ".join(parts).replace("… …", "…")
        return fragment if len(fragment) <= limit else fragment[:limit].rsplit(" ", 1)[0] + " …"

    def classify(self, title: str, summary: str, source: dict) -> dict | None:
        """Geeft classificatievelden terug, of None als het bericht niet relevant is."""
        text = f"{title}\n{summary}"
        topic_hits = match_rules(text, self.topic_rules)
        if not topic_hits and source.get("filter"):
            return None
        default = source.get("standaard_onderwerp")
        if default:  # het vaste onderwerp van de bron geldt altijd
            topic_hits.setdefault(default, [])
        theme_hits = match_rules(text, self.theme_rules)
        topics = [r.id for r in self.topic_rules if r.id in topic_hits]
        themes = [r.id for r in self.theme_rules if r.id in theme_hits]
        theme_score = sum(self.theme_weight[t] for t in themes)
        score = (
            sum(self.topic_weight.get(t, 0) for t in topics)
            + min(4, theme_score)
            + PRIORITEIT_BONUS.get(int(source.get("prioriteit", 2)), 0)
        )
        if ("ebw" in topics and DIRECTE_MOZA_THEMAS & set(themes)) or theme_score >= 4:
            level = "hoog"
        elif themes or "ebw" in topics:
            level = "middel"
        else:
            level = "laag"
        return {
            "topics": topics,
            "topic_hits": {k: v for k, v in topic_hits.items() if v},
            "moza": [{"thema": t, "termen": theme_hits[t]} for t in themes],
            "moza_level": level,
            "score": score,
        }
