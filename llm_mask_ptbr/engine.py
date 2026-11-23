import re
from collections import Counter

from .vault import Vault

TOKEN = re.compile(r"\[[A-Z][A-Z_]*_\d+\]")
CACHED_TEXTS = 512
PARTIAL_TOKEN = re.compile(r"\[[A-Z_]*\d*$")


class Masker:
    def __init__(self, detectors, vault=None, allow=()):
        self.detectors = list(detectors)
        self.vault = vault or Vault()
        self.allow = {value.lower() for value in allow}
        self.cache = {}

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
        if text not in self.cache:
            if len(self.cache) >= CACHED_TEXTS:
                del self.cache[next(iter(self.cache))]
            out, pos, spans = [], 0, self.spans(text)
            for span in spans:
                out += [text[pos:span.start], self.vault.token(span.kind, text[span.start:span.end])]
                pos = span.end
            self.cache[text] = "".join(out) + text[pos:], Counter(span.kind for span in spans)
        masked, kinds = self.cache[text]
        if found is not None:
            found.update(kinds)
        return masked

    def restore(self, text, escape=lambda value: value):
        def original(match):
            value = self.vault.value(match.group())
            return match.group() if value is None else escape(value)
        return TOKEN.sub(original, text)
