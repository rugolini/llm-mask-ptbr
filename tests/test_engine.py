import importlib.util
import os
import tempfile
import unittest

from llm_mask_ptbr.config import Settings, build_masker
from llm_mask_ptbr.detectors import BUILTIN, Span, dictionary
from llm_mask_ptbr.engine import Masker
from llm_mask_ptbr.vault import Vault


class MaskerTest(unittest.TestCase):
    def test_a_listed_name_becomes_a_token_and_comes_back(self):
        masker = Masker([dictionary({"PESSOA": ["Maria Souza"]})])
        masked = masker.mask("Ligue para Maria Souza amanhã.")
        self.assertEqual(masked, "Ligue para [PESSOA_1] amanhã.")
        self.assertEqual(masker.restore("Ok, ligo para [PESSOA_1]."), "Ok, ligo para Maria Souza.")

    def test_a_cpf_is_masked_only_when_its_check_digits_are_right(self):
        masker = Masker([BUILTIN["cpf"]])
        self.assertEqual(masker.mask("CPF 529.982.247-25 e 52998224725"), "CPF [CPF_1] e [CPF_2]")
        self.assertEqual(masker.mask("pedido 529.982.247-26, total 12345678901"), "pedido 529.982.247-26, total 12345678901")

    def test_brazilian_contact_and_document_numbers_are_masked(self):
        masker = Masker(BUILTIN.values())
        cases = {
            "fale com maria.souza@exemplo.com.br hoje": "fale com [EMAIL_1] hoje",
            "zap +55 11 98765-4321": "zap [TELEFONE_1]",
            "fixo (11) 3456-7890 ok": "fixo [TELEFONE_2] ok",
            "cel 11 98765-4321.": "cel [TELEFONE_3].",
            "de 5511987654321@s.whatsapp.net": "de [EMAIL_2]",
            "jid 5511987654321 visto": "jid [TELEFONE_4] visto",
            "CEP 05422-030": "CEP [CEP_1]",
            "CNPJ 11.222.333/0001-81": "CNPJ [CNPJ_1]",
            "cartão 4111 1111 1111 1111": "cartão [CARTAO_1]",
        }
        for text, expected in cases.items():
            self.assertEqual(masker.mask(text), expected)

    def test_amounts_dates_and_ordinary_numbers_pass_through(self):
        masker = Masker(BUILTIN.values())
        for text in ["R$ 12.345,67 em 15/02/2027", "120 ações MSFT a US$ 512,30", "CNPJ 11.222.333/0001-82",
                     "pedido 4111 1111 1111 1112", "porta 8123, 192.168.0.10, 2026-11-23 14:30:05"]:
            self.assertEqual(masker.mask(text), text)

    def test_the_same_value_keeps_its_token_after_a_restart(self):
        path = os.path.join(tempfile.mkdtemp(), "vault.db")
        first = Masker([dictionary({"PESSOA": ["Maria", "João"]})], Vault(path))
        self.assertEqual(first.mask("João e Maria"), "[PESSOA_1] e [PESSOA_2]")
        second = Masker([dictionary({"PESSOA": ["Maria", "João", "Ana"]})], Vault(path))
        self.assertEqual(second.mask("Ana, Maria"), "[PESSOA_3], [PESSOA_2]")
        self.assertEqual(second.restore("[PESSOA_1]"), "João")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_allowed_strings_are_never_masked(self):
        masker = Masker([BUILTIN["email"], dictionary({"PESSOA": ["Caddy"]})], allow=["suporte@exemplo.com.br", "caddy"])
        text = "Caddy caiu; escreva para suporte@exemplo.com.br ou ana@exemplo.com.br"
        self.assertEqual(masker.mask(text), "Caddy caiu; escreva para suporte@exemplo.com.br ou [EMAIL_1]")

    def test_scan_counts_findings_by_kind_without_touching_the_vault(self):
        masker = Masker([BUILTIN["email"], BUILTIN["cpf"]])
        self.assertEqual(masker.scan("a@b.com, c@d.com, 529.982.247-25"), {"EMAIL": 2, "CPF": 1})
        self.assertEqual(masker.mask("a@b.com"), "[EMAIL_1]")

    def test_a_text_seen_before_is_not_analysed_again(self):
        calls = []

        def slow_detector(text):
            calls.append(text)
            return [Span(0, 4, "PESSOA")]

        masker = Masker([slow_detector])
        self.assertEqual([masker.mask("Aldo veio"), masker.mask("Aldo veio")], ["[PESSOA_1] veio", "[PESSOA_1] veio"])
        self.assertEqual(calls, ["Aldo veio"])

    @unittest.skipUnless(importlib.util.find_spec("presidio_analyzer") and importlib.util.find_spec("pt_core_news_sm"),
                         "needs the ner extra and the pt_core_news_sm model")
    def test_presidio_finds_a_name_that_is_in_no_list(self):
        settings = Settings(upstream="http://x", detectors=[], ner={"model": "pt_core_news_sm", "entities": {"PERSON": "PESSOA"}})
        self.assertEqual(build_masker(settings).mask("Ontem a Fernanda Oliveira ligou."), "Ontem a [PESSOA_1] ligou.")


if __name__ == "__main__":
    unittest.main()
