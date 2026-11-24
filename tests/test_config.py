import os
import tempfile
import unittest

from llm_mask_ptbr.config import build_masker, load


def write(folder, name, text):
    path = os.path.join(folder, name)
    with open(path, "w") as file:
        file.write(text)
    return path


class ConfigTest(unittest.TestCase):
    def test_settings_come_from_the_file_and_the_environment_wins(self):
        folder = tempfile.mkdtemp()
        write(folder, "dictionary.yaml", "PESSOA:\n  - Maria Souza\n")
        path = write(folder, "config.yaml", f"""
upstream: http://gpustack
mode: shadow
vault: {folder}/vault.db
unmasked_models: [local]
detectors: [cpf, email]
dictionary_file: dictionary.yaml
dictionary:
  LOCAL: [Rua das Flores]
allow: [suporte@exemplo.com.br]
""")
        settings = load(path, {"LLM_MASK_MODE": "mask", "LLM_MASK_PORT": "9000"})
        self.assertEqual((settings.upstream, settings.mode, settings.unmasked_models, settings.port),
                         ("http://gpustack", "mask", ["local"], 9000))
        self.assertEqual(build_masker(settings).mask("Maria Souza, Rua das Flores, a@b.com, suporte@exemplo.com.br, 05422-030"),
                         "[PESSOA_1], [LOCAL_1], [EMAIL_1], suporte@exemplo.com.br, 05422-030")
        self.assertTrue(os.path.exists(f"{folder}/vault.db"))

    def test_the_environment_alone_is_enough_and_every_detector_is_on_by_default(self):
        settings = load(None, {"LLM_MASK_UPSTREAM": "http://provider"})
        self.assertEqual((settings.mode, settings.vault, settings.port), ("mask", ":memory:", 8400))
        self.assertEqual(build_masker(settings).mask("529.982.247-25 05422-030"), "[CPF_1] [CEP_1]")

    def test_a_bad_configuration_stops_the_start(self):
        folder = tempfile.mkdtemp()
        for text in ["mode: mask", "upstream: http://x\nmode: off", "upstream: http://x\ndetectors: [cpff]",
                     "upstream: http://x\ndictionary:\n  pessoa: [Maria]", "upstream: http://x\nupstrem: http://y"]:
            with self.assertRaises(ValueError, msg=text):
                load(write(folder, "config.yaml", text), {})

    def test_listed_secrets_are_masked_wherever_they_appear_and_tools_are_named(self):
        folder = tempfile.mkdtemp()
        write(folder, "secrets.txt", "correct-horse\n\n  battery-staple  \n")
        path = write(folder, "config.yaml", "upstream: http://x\nsecrets: [Tr0ub4dor]\nsecrets_file: secrets.txt\nsecret_tools: [browser_type]\n")
        settings = load(path, {})
        self.assertEqual(settings.secret_tools, ["browser_type"])
        self.assertEqual(build_masker(settings).mask("usei Tr0ub4dor, correct-horse e battery-staple"),
                         "usei [SEGREDO_1], [SEGREDO_2] e [SEGREDO_3]")


if __name__ == "__main__":
    unittest.main()
