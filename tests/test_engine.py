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

    def test_a_punctuated_document_is_masked_by_its_shape_even_with_wrong_check_digits(self):
        masker = Masker(BUILTIN.values())
        cases = {
            "CPF 529.982.247-26": "CPF [CPF_1]",
            "CNPJ 11.222.333/0001-82": "CNPJ [CNPJ_1]",
            "CNPJ novo 12.ABC.345/01DE-35": "CNPJ novo [CNPJ_2]",
            "RG 12.345.678-9 e 1.234.567-X": "RG [RG_1] e [RG_2]",
            "PIS 330.79244.02-1": "PIS [PIS_1]",
            "SUS 850 7529 1703 4336": "SUS [CNS_1]",
            "placa ABC-1234 ou BRA2E19": "placa [PLACA_1] ou [PLACA_2]",
        }
        for text, expected in cases.items():
            self.assertEqual(masker.mask(text), expected)

    def test_a_bare_run_of_digits_is_masked_only_when_its_check_digits_fit_a_document(self):
        masker = Masker(BUILTIN.values())
        valid = {"52998224725": "[CPF_1]", "11222333000181": "[CNPJ_1]", "54323194879": "[CNH_1]", "685995282038": "[TITULO_1]",
                 "078666611694": "[TITULO_2]", "252760189550006": "[CNS_1]", "797971157104974": "[CNS_2]",
                 "10339823509": "[CNH_2]", "435709200280": "[TITULO_3]"}
        for number, token in valid.items():
            self.assertEqual(masker.mask(f"doc {number}."), f"doc {token}.")
        for number in ["11222333000182", "54323194870", "685995282039", "252760189550007", "1795300957", "123456789", "01420388900",
                       "12345678901", "123456789012"]:
            self.assertEqual(masker.mask(f"doc {number}."), f"doc {number}.")

    def test_brazilian_contact_and_document_numbers_are_masked(self):
        masker = Masker(BUILTIN.values())
        cases = {
            "fale com maria.souza@exemplo.com.br hoje": "fale com [EMAIL_1] hoje",
            "zap +55 11 98765-4321": "zap [TELEFONE_1]",
            "fixo (11) 3456-7890 ok": "fixo [TELEFONE_2] ok",
            "cel 11 98765-4321.": "cel [TELEFONE_3].",
            "de 5511987654321@s.whatsapp.net": "de [EMAIL_2]",
            "jid 5511987654321 visto": "jid [TELEFONE_4] visto",
            "cel 11987654321 ok": "cel [TELEFONE_5] ok",
            "CEP 05422-030": "CEP [CEP_1]",
            "CNPJ 11.222.333/0001-81": "CNPJ [CNPJ_1]",
            "cartão 4111 1111 1111 1111": "cartão [CARTAO_1]",
        }
        for text, expected in cases.items():
            self.assertEqual(masker.mask(text), expected)

    def test_a_number_named_by_the_word_before_it_is_masked(self):
        masker = Masker(BUILTIN.values())
        cases = {
            "RG 123456789": "RG [RG_1]",
            "identidade nº 12345678-X emitida": "identidade nº [RG_2] emitida",
            "PIS: 67127684264": "PIS: [PIS_1]",
            "RENAVAM 60313721592": "RENAVAM [RENAVAM_1]",
            "passaporte FZ123456 válido": "passaporte [PASSAPORTE_1] válido",
            "título de eleitor 6859 9528 2039": "título de eleitor [TITULO_1]",
            "CNH 54323194870": "CNH [CNH_1]",
            "Banco 341, agência 1234-5, conta corrente 12345-6": "Banco 341, agência [AGENCIA_1], conta corrente [CONTA_1]",
            "ag. 0123 c/c 0045678-9": "ag. [AGENCIA_2] c/c [CONTA_2]",
            "chave Pix 123e4567-e89b-12d3-a456-426614174000": "chave Pix [PIX_1]",
            "nascido em 05/03/1980": "nascido em [NASCIMENTO_1]",
            "data de nascimento: 5 de março de 1980": "data de nascimento: [NASCIMENTO_2]",
            "placa ABC1234": "placa [PLACA_1]",
        }
        for text, expected in cases.items():
            self.assertEqual(masker.mask(text), expected)

    def test_a_street_address_with_a_number_is_masked(self):
        masker = Masker(BUILTIN.values())
        cases = {
            "moro na Rua das Flores, 123, ap 45, em Pinheiros": "moro na [ENDERECO_1], em Pinheiros",
            "Av. Paulista 1000 fica longe": "[ENDERECO_2] fica longe",
            "entrega na Alameda Santos, nº 2200 - conjunto 51.": "entrega na [ENDERECO_3].",
            "na Rua 25 de Março, 100": "na [ENDERECO_4]",
            "a rua estava vazia. Em 2020 choveu": "a rua estava vazia. Em 2020 choveu",
            "a avenida principal tem 3 faixas": "a avenida principal tem 3 faixas",
        }
        for text, expected in cases.items():
            self.assertEqual(masker.mask(text), expected)

    def test_a_word_right_after_a_written_out_line_break_is_still_recognised(self):
        masker = Masker([dictionary({"PESSOA": ["Maria Souza"]}), *BUILTIN.values()])
        command = r'printf "RG 123456789\nconta 12345-6\nMaria Souza\nRua das Flores, 123\tnascido em 05/03/1980"'
        self.assertEqual(masker.mask(command), r'printf "RG [RG_1]\n[CONTA_1]\n[PESSOA_1]\n[ENDERECO_1]\tnascido em [NASCIMENTO_1]"'
                         .replace("[CONTA_1]", "conta [CONTA_1]"))

    def test_passwords_and_keys_are_masked_by_label_or_shape(self):
        masker = Masker(BUILTIN.values())
        pem = "-----BEGIN OPENSSH PRIVATE KEY-----" + chr(10) + "abc" + chr(10) + "-----END OPENSSH PRIVATE KEY-----"
        cases = {
            "senha: Abacaxi#42": "senha: [SENHA_1]",
            'password = "hunter2!"': 'password = "[SENHA_2]"',
            "a senha é Xk9$mPq2 mesmo": "a senha é [SENHA_3] mesmo",
            "DB_PASSWORD=s3cr3t-valor": "DB_PASSWORD=[SEGREDO_1]",
            '{"api_key": "abc123def456ghi789"}': '{"api_key": "[SEGREDO_2]"}',
            "Authorization: Bearer abcdefghijklmnop1234": "Authorization: Bearer [SEGREDO_3]",
            "postgres://app:Tr0ub4dor@db:5432/x": "postgres://app:[SENHA_4]@db:5432/x",
            "chave sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWx no log": "chave [SEGREDO_4] no log",
            "token ghp_0123456789abcdefghijABCDEFGHIJ012345 aqui": "token [SEGREDO_5] aqui",
            "key gpustack_0123456789abcdef_0123456789abcdef0123456789abcdef": "key [SEGREDO_6]",
            pem: "[SEGREDO_7]",
            '{"password": "Zebra_99"}': '{"password": "[SENHA_5]"}',
        }
        for text, expected in cases.items():
            self.assertEqual(masker.mask(text), expected)

    def test_placeholders_and_talk_about_passwords_stay(self):
        masker = Masker(BUILTIN.values())
        for text in ["a senha é obrigatória", "troque a senha no painel", "DB_PASSWORD=${DB_PASSWORD}", "senha: {{secret:X}}",
                     "password: ********", "API_KEY=<sua-chave>", "token: null", "o token expirou ontem", "senha: [SENHA_9]"]:
            self.assertEqual(masker.mask(text), text)

    def test_a_secret_seen_once_is_masked_everywhere_afterwards_even_without_a_label(self):
        path = os.path.join(tempfile.mkdtemp(), "vault.db")
        masker = Masker(BUILTIN.values(), Vault(path), secrets=["correct-horse"])
        self.assertEqual(masker.mask("digitei Abacaxi#42 no campo"), "digitei Abacaxi#42 no campo")
        self.assertEqual(masker.mask("senha: Abacaxi#42"), "senha: [SENHA_1]")
        self.assertEqual(masker.mask("digitei Abacaxi#42 no campo"), "digitei [SENHA_1] no campo")
        self.assertEqual(masker.mask('{"text": "Abacaxi#42"} e correct-horse'), '{"text": "[SENHA_1]"} e [SEGREDO_1]')
        self.assertEqual(Masker(BUILTIN.values(), Vault(path)).mask("de novo Abacaxi#42"), "de novo [SENHA_1]")

    def test_a_secret_token_is_only_restored_when_asked_for(self):
        masker = Masker(BUILTIN.values())
        masker.mask("senha: Abacaxi#42, CPF 529.982.247-25")
        self.assertEqual(masker.restore("use [SENHA_1] e [CPF_1]"), "use [SENHA_1] e 529.982.247-25")
        self.assertEqual(masker.restore("use [SENHA_1] e [CPF_1]", secrets=True), "use Abacaxi#42 e 529.982.247-25")

    def test_amounts_dates_and_ordinary_numbers_pass_through(self):
        masker = Masker(BUILTIN.values())
        for text in ["R$ 12.345,67 em 15/02/2027", "120 ações MSFT a US$ 512,30", "saldo de R$ 1.234.567,89",
                     "pedido 4111 1111 1111 1112", "porta 8123, 192.168.0.10, 2026-11-23 14:30:05",
                     "o roteador GLX3000 e o commit 2b2069f548cb935824e9913eb53e6b41f42cb1e4",
                     "a conta de luz veio R$ 312,40", "reunião em 05/03/2027", "container 123e4567-e89b-12d3-a456-426614174000",
                     "o título do livro é 1984", "epoch 1795300957 e 1795300957123"]:
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
