import re
from typing import Callable, Iterable, NamedTuple


class Span(NamedTuple):
    start: int
    end: int
    kind: str


Detector = Callable[[str], Iterable[Span]]


def dictionary(terms: dict[str, list[str]]) -> Detector:
    kinds = {value.lower(): kind for kind, values in terms.items() for value in values}
    if not kinds:
        return lambda text: ()
    alternatives = "|".join(re.escape(v) for v in sorted(kinds, key=len, reverse=True))
    rx = re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)
    return lambda text: (Span(m.start(), m.end(), kinds[m.group().lower()]) for m in rx.finditer(text))


def _digits(text):
    return [int(c) for c in text if c.isdigit()]


def _regex(kind, pattern, valid=lambda text: True) -> Detector:
    rx = re.compile(pattern)
    return lambda text: (Span(m.start(), m.end(), kind) for m in rx.finditer(text) if valid(m.group()))


def _cpf(text):
    d = _digits(text)
    if len(set(d)) == 1:
        return False
    return all(sum(v * (n + 1 - i) for i, v in enumerate(d[:n])) * 10 % 11 % 10 == d[n] for n in (9, 10))


def _cnpj(text):
    d = _digits(text)
    if len(set(d)) == 1:
        return False
    weights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    return all((r := sum(v * w for v, w in zip(d[:n], weights[13 - n:])) % 11) < 2 and d[n] == 0 or d[n] == 11 - r
               for n in (12, 13))


def _luhn(text):
    d = _digits(text)[::-1]
    return (sum(d[0::2]) + sum(sum(divmod(2 * v, 10)) for v in d[1::2])) % 10 == 0


_PHONE = (r"(?<![\w+])(?:\+55\s?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}|\(\d{2}\)\s?9?\d{4}[-\s]?\d{4}"
          r"|55\d{2}9?\d{8}|\d{2}\s9\d{4}[-\s]?\d{4}|9\d{4}-\d{4})(?!\d)")

BUILTIN = {
    "email": _regex("EMAIL", r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "cpf": _regex("CPF", r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)", _cpf),
    "cnpj": _regex("CNPJ", r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)", _cnpj),
    "card": _regex("CARTAO", r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)", _luhn),
    "phone": _regex("TELEFONE", _PHONE),
    "cep": _regex("CEP", r"(?<!\d)\d{5}-\d{3}(?!\d)"),
}
