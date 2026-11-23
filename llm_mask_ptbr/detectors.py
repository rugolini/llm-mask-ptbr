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


def _pattern(kind, pattern, valid=lambda text: True, flags=0) -> Detector:
    """The span is group 1 when the pattern has one, the whole match otherwise."""
    rx = re.compile(pattern, flags)
    group = 1 if rx.groups else 0
    return lambda text: (Span(m.start(group), m.end(group), kind) for m in rx.finditer(text) if valid(m.group(group)))


def _labelled(kind, words, number) -> Detector:
    """A number that only means something next to the word that names it: "RG 123456789", "conta 12345-6"."""
    return _pattern(kind, rf"(?<!\w)(?:{words})(?!\w)[^\d\n]{{0,20}}?({number})(?!\w)", flags=re.IGNORECASE)


def _any(*detectors) -> Detector:
    return lambda text: (span for detect in detectors for span in detect(text))


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


def _cnh(text):
    d = _digits(text)
    if len(set(d)) == 1:
        return False
    first = sum(v * (9 - i) for i, v in enumerate(d[:9])) % 11
    second = sum(v * (1 + i) for i, v in enumerate(d[:9])) % 11 - (2 if first >= 10 else 0)
    second += 11 if second < 0 else 0
    return d[9:] == [0 if first >= 10 else first, 0 if second >= 10 else second]


def _voter(text):
    d = _digits(text)
    state = d[8] * 10 + d[9]
    if not 1 <= state <= 28:
        return False

    # Sources disagree on whether a remainder of 0 becomes 1 in SP and MG; accept both rather than let one through.
    def fits(total, digit):
        rest = total % 11
        return digit == rest % 10 or (rest == 0 and state in (1, 2) and digit == 1)

    return fits(sum(v * (i + 2) for i, v in enumerate(d[:8])), d[10]) and fits(d[8] * 7 + d[9] * 8 + d[10] * 9, d[11])


def _cns(text):
    d = _digits(text)
    if sum(v * (15 - i) for i, v in enumerate(d)) % 11:
        return False
    return d[0] in (7, 8, 9) or (d[0] in (1, 2) and d[11:13] == [0, 0] and d[13] in (0, 1))


_AREA = r"(?:1[1-9]|2[12478]|3[1-578]|4[1-9]|5[1345]|6[1-9]|7[13-579]|8[1-9]|9[1-9])"
_PHONE = (r"(?<![\w+])(?:\+55\s?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}|\(\d{2}\)\s?9?\d{4}[-\s]?\d{4}"
          rf"|55\d{{2}}9?\d{{8}}|\d{{2}}\s9\d{{4}}[-\s]?\d{{4}}|9\d{{4}}-\d{{4}}|{_AREA}9\d{{8}})(?!\d)")
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_DATE = r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{1,2}º?\s+de\s+[a-zç]+\s+de\s+\d{4}"
# The street name must be capitalised, so "a rua estava vazia. Em 2020" stays as it is.
_ADDRESS = (r"(?<!\w)(?i:rua|r\.|avenida|av\.?|alameda|al\.|travessa|tv\.|praça|rodovia|estrada|largo)\s+"
            r"(?:(?:[A-ZÀ-Ý0-9][\wÀ-ÿ'.-]*|de|da|do|das|dos|e)\s+){0,6}?[A-ZÀ-Ý][\wÀ-ÿ'-]*"
            r",?\s*(?:[nN][ºo°]\.?\s*)?\d{1,5}(?!\d)"
            r"(?:\s*[,-]?\s*(?i:ap(?:to|artamento)?\.?|bloco|casa|cj\.?|conjunto|sala|andar)\s*\w+)*")

# A punctuated document is masked by its shape alone: masking too much costs nothing, a typo in a check digit would leak.
# A bare run of digits needs valid check digits or the word that names it, or it would swallow order numbers and timestamps.
BUILTIN = {
    "email": _pattern("EMAIL", r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "cpf": _any(_pattern("CPF", r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)"),
                _pattern("CPF", r"(?<!\d)\d{9}-?\d{2}(?!\d)", _cpf)),
    "cnpj": _any(_pattern("CNPJ", r"(?<![A-Za-z\d])[A-Z\d]{2}\.[A-Z\d]{3}\.[A-Z\d]{3}/[A-Z\d]{4}-\d{2}(?!\d)"),
                 _pattern("CNPJ", r"(?<!\d)\d{14}(?!\d)", _cnpj)),
    "card": _pattern("CARTAO", r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)", _luhn),
    "phone": _pattern("TELEFONE", _PHONE),
    "cep": _pattern("CEP", r"(?<!\d)\d{5}-\d{3}(?!\d)"),
    "rg": _any(_pattern("RG", r"(?<![\d.])\d{1,2}\.\d{3}\.\d{3}-[\dXx](?!\w)"),
               _labelled("RG", "RG|identidade", r"\d[\d.]{4,11}(?:-?[\dXx])?")),
    "pis": _any(_pattern("PIS", r"(?<!\d)\d{3}\.\d{5}\.\d{2}-\d(?!\d)"),
                _labelled("PIS", "PIS|PASEP|NIT|NIS", r"\d{11}")),
    "cns": _any(_pattern("CNS", r"(?<!\d)\d{3} \d{4} \d{4} \d{4}(?!\d)"),
                _pattern("CNS", r"(?<!\d)\d{15}(?!\d)", _cns)),
    "cnh": _any(_pattern("CNH", r"(?<!\d)\d{11}(?!\d)", _cnh),
                _labelled("CNH", "CNH|habilita[çc][ãa]o", r"\d{9,11}")),
    "voter": _any(_pattern("TITULO", r"(?<!\d)\d{12}(?!\d)", _voter),
                  _labelled("TITULO", r"t[ií]tulo\s+(?:de\s+eleitor|eleitoral)", r"\d{4}\s?\d{4}\s?\d{4}")),
    "renavam": _labelled("RENAVAM", "RENAVAM", r"\d{9,11}"),
    "passport": _labelled("PASSAPORTE", "passaporte", r"[A-Z]{2}\d{6}"),
    "plate": _any(_pattern("PLACA", r"(?<![A-Za-z\d])(?:[A-Z]{3}-\d{4}|[A-Z]{3}\d[A-Z]\d{2})(?![A-Za-z\d])"),
                  _labelled("PLACA", "placa", r"[A-Z]{3}-?\d{4}")),
    "bank": _any(_labelled("AGENCIA", r"ag[êe]ncia|ag\.?", r"\d{3,5}(?:-[\dXx])?"),
                 _labelled("CONTA", r"conta(?:\s+(?:corrente|poupan[çc]a))?|c/c|c\.c\.", r"\d{3,12}-[\dXx]")),
    "pix": _labelled("PIX", "pix|chave", _UUID),
    "birth": _labelled("NASCIMENTO", r"nascimento|nascid[oa](?:\s+em)?|nasc\.?|anivers[áa]rio", _DATE),
    "address": _pattern("ENDERECO", _ADDRESS),
}
