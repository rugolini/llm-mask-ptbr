import re
from collections import Counter

from .detectors import Span
from .vault import Vault

TOKEN = re.compile(r"\[([A-Z][A-Z_]*)_\d+\]")
CACHED_TEXTS = 512
PARTIAL_TOKEN = re.compile(r"\[[A-Z_]*\d*$")
# A secret is used, never shown: its token is only restored where the caller asks for it.
SECRET_KINDS = {"SENHA", "SEGREDO"}
SHORTEST_SECRET = 4


def _worth_learning(value):
    # A lowercase word after "senha:" is as likely prose as a password; learnt, it would be masked in every later text.
    return len(value) >= SHORTEST_SECRET and not (value.isalpha() and value.islower())


class Masker:
    def __init__(self, detectors, vault=None, allow=(), secrets=()):
        self.detectors = list(detectors)
        self.vault = vault or Vault()
        self.allow = {value.lower() for value in allow}
        self.cache = {}
        # Once a value was masked as a secret it is masked wherever it shows up again, label or not:
        # a password typed into a tool comes back bare in the next request's history.
        self.secrets = {value for value in secrets if len(value) >= SHORTEST_SECRET}
        self.secrets |= {value for value, (kind, _) in self.vault.by_value.items()
                         if kind in SECRET_KINDS and _worth_learning(value)}
        self.known = None

    def _known_secrets(self, text):
        if not self.secrets:
            return ()
        if self.known is None:
            self.known = re.compile("|".join(re.escape(value) for value in sorted(self.secrets, key=len, reverse=True)))
        return (Span(m.start(), m.end(), "SEGREDO") for m in self.known.finditer(text))

    def spans(self, text):
        found = sorted((s for detect in (self._known_secrets, *self.detectors) for s in detect(text)),
                       key=lambda s: (s.start, s.start - s.end))
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
            out, pos, spans, learned = [], 0, self.spans(text), False
            for span in spans:
                value = text[span.start:span.end]
                out += [text[pos:span.start], self.vault.token(span.kind, value)]
                pos = span.end
                if span.kind in SECRET_KINDS and value not in self.secrets and _worth_learning(value):
                    self.secrets.add(value)
                    learned = True
            if learned:
                self.known = None
                self.cache.clear()
            self.cache[text] = "".join(out) + text[pos:], Counter(span.kind for span in spans)
        masked, kinds = self.cache[text]
        if found is not None:
            found.update(kinds)
        return masked

    def restore(self, text, escape=lambda value: value, secrets=False):
        def original(match):
            value = self.vault.value(match.group())
            if value is None or (match.group(1) in SECRET_KINDS and not secrets):
                return match.group()
            return escape(value)
        return TOKEN.sub(original, text)
