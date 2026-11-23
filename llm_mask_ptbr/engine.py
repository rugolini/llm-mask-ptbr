import re
from collections import Counter

from .vault import Vault

TOKEN = re.compile(r"\[[A-Z][A-Z_]*_\d+\]")
PARTIAL_TOKEN = re.compile(r"\[[A-Z_]*\d*$")


class Masker:
    def __init__(self, detectors, vault=None, allow=()):
        self.detectors = list(detectors)
        self.vault = vault or Vault()
        self.allow = {value.lower() for value in allow}

    def spans(self, text):
        found = sorted((s for detect in self.detectors for s in detect(text)), key=lambda s: (s.start, s.start - s.end))
        kept, end = [], 0
        for span in found:
            if span.start >= end and text[span.start:span.end].lower() not in self.allow:
                kept.append(span)
                end = span.end
        return kept

    def scan(self, text):
        return dict(Counter(span.kind for span in self.spans(text)))

    def mask(self, text, found=None):
        out, pos = [], 0
        for span in self.spans(text):
            if found is not None:
                found[span.kind] += 1
            out += [text[pos:span.start], self.vault.token(span.kind, text[span.start:span.end])]
            pos = span.end
        return "".join(out) + text[pos:]

    def restore(self, text, escape=lambda value: value):
        def original(match):
            value = self.vault.value(match.group())
            return match.group() if value is None else escape(value)
        return TOKEN.sub(original, text)
