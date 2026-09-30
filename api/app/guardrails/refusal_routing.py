"""Model-free refusal routing (decisions D39): questions refused before any model call, because no answer to them
could be right. Deliberately narrow: only requests whose wording alone settles it. Everything else, forecasts,
personal data and off-topic questions included, is still the model's call under the prompt's refusal rules.

The eval's free tier runs this over every golden-set question, so a pattern that catches an answerable question
fails CI.
"""

import re

# reason -> (pattern, what the user is told). The first matching reason wins.
ROUTES = {
    "write": (
        (r"\b(delete|drop|truncate|insert|alter|update)\b[^.?!]{0,80}\b(tables?|rows?|records?)\b|\bdelete\s+from\b"
         r"|\b(raise|increase|lower|reduce|change|set)\b[^.?!]{0,60}\bcredit limit\b[^.?!]{0,20}\bto\b"),
        "I can only read the data; I can't change, delete or create anything.",
    ),
    "raw_data": (
        (r"\b(raw|staging|stg|intermediate)\s*\.\s*\w+|\b(raw|staging)\s+(tables?|schema|layer)\b|\bskip the marts\b"
         r"|\binformation_schema\b|\bpg_(catalog|shadow|authid|user|roles|read_file)\b"),
        "I can only query the governed marts, not the raw, staging or system tables.",
    ),
    "injection": (
        (r"\bignore\s+(all\s+|any\s+)?(the\s+|your\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompts?)\b"
         r"|\byou are now (in|an?|the)\b|\b(admin|maintenance|developer|god)\s+mode\b|\bsystem prompt\b"),
        "I can't change how I work on request. Ask me a question about the channel, quality or collections data.",
    ),
    "no_sql": (
        (r"\b(don'?t|do not|without)\s+(show(ing)?|includ(e|ing)|giv(e|ing)|mention(ing)?|say(ing)?)\s+(me\s+)?"
         r"(any\s+|the\s+)?(sql|quer(y|ies)|sources?|where it came from)\b"),
        "Every figure I give comes with the SQL behind it, so I can't give a number without showing its source.",
    ),
}
_COMPILED = {reason: re.compile(pattern, re.IGNORECASE) for reason, (pattern, _) in ROUTES.items()}


def route(question: str) -> str | None:
    """The reason this question is refused without a model call, or None to let the model decide."""
    return next((reason for reason, pattern in _COMPILED.items() if pattern.search(question)), None)


def message(reason: str) -> str:
    return ROUTES[reason][1]
