# llm-mask-ptbr

Proxy que troca dados pessoais por marcadores antes de o pedido sair para um modelo de linguagem na nuvem, e põe os
valores de volta na resposta. Feito para texto em português do Brasil: CPF, CNPJ, RG, CNH, título de eleitor, cartão SUS, PIS, conta bancária,
telefone, endereço, CEP e a sua lista de nomes.

*English summary [at the end](#english-summary).*

```
seu app ou agente  →  llm-mask-ptbr  →  provedor (OpenAI, Anthropic, OpenRouter, LiteLLM, GPUStack...)

"Ligue para Maria Souza, CPF 529.982.247-25, sobre os R$ 1.234,56"
                   →  "Ligue para [PESSOA_1], CPF [CPF_1], sobre os R$ 1.234,56"

"Combinado, ligo para [PESSOA_1]."      ←  resposta do modelo
"Combinado, ligo para Maria Souza."     ←  o que o seu app recebe
```

O app não muda: só passa a apontar o `base_url` para o proxy.

## O que ele faz

- Fala a API da OpenAI (`/v1/chat/completions`) e a da Anthropic (`/v1/messages`, `/v1/messages/count_tokens`).
- Mascara o prompt de sistema, as mensagens, os resultados de ferramenta e os **argumentos das chamadas de ferramenta**
  (onde boa parte dos proxies deixa passar).
- Desfaz a máscara na resposta, com ou sem streaming. No streaming, segura o pedaço de um marcador cortado entre dois
  eventos, e escapa o valor quando ele volta dentro de JSON.
- Mapa fixo: o mesmo valor recebe sempre o mesmo marcador, inclusive depois de reiniciar. O cache de prompt do provedor
  continua valendo.
- Valores em dinheiro, datas e números comuns passam. A ideia é o modelo ainda conseguir fazer a conta.
- Modelos servidos em casa podem ficar de fora (`unmasked_models`): o pedido para eles passa inteiro.
- Senhas e chaves são mascaradas e só voltam nos argumentos de ferramentas que você autorizar; nunca no texto (ver [Senhas e chaves](#senhas-e-chaves-usadas-nunca-mostradas)).
- Avisa o modelo, no prompt de sistema, de que os marcadores são valores reais (ver [O aviso ao modelo](#o-aviso-ao-modelo)).
- Modo sombra: encaminha o texto original e só conta o que mascararia. Serve para medir antes de ligar.
- Falha fechada: pedido que ele não sabe inspecionar (`/v1/embeddings`, `/v1/responses`, corpo que não é JSON) é
  recusado com 501 ou 400. Nada segue sem passar pela máscara.

## O que é mascarado

O critério é o da LGPD (art. 5º, I): informação que identifica uma pessoa ou permite identificá-la. A lei não lista
documentos nem formatos; as regras abaixo vêm das especificações de cada documento brasileiro.

Três maneiras de reconhecer:

- **Pelo formato.** Documento escrito com pontuação é mascarado só pela cara, sem conferir dígito verificador. Mascarar
  a mais não custa nada (o valor volta na resposta); exigir dígito certo deixaria passar um CPF com erro de digitação.
- **Pelo dígito verificador.** Uma sequência só de dígitos só é mascarada se os dígitos verificadores fecharem com
  algum documento. Sem isso, todo número de pedido ou timestamp viraria marcador.
- **Pela palavra antes.** Números que sozinhos não dizem nada ("123456789") são mascarados quando vêm depois da palavra
  que os nomeia ("RG 123456789", "conta 12345-6").

| Tipo | Pelo formato | Pelo dígito (só dígitos) | Pela palavra antes |
|---|---|---|---|
| `CPF` | `529.982.247-25` | 11 dígitos válidos | |
| `CNPJ` | `11.222.333/0001-81`, alfanumérico `12.ABC.345/01DE-35` | 14 dígitos válidos | |
| `RG` | `12.345.678-9`, `1.234.567-X` | | `RG`, `identidade` |
| `CNH` | | 11 dígitos válidos | `CNH`, `habilitação` |
| `TITULO` (eleitor) | | 12 dígitos válidos | `título de eleitor`, `título eleitoral` |
| `CNS` (cartão SUS) | `850 7529 1703 4336` | 15 dígitos válidos | |
| `PIS` (PIS/PASEP/NIT) | `330.79244.02-1` | | `PIS`, `PASEP`, `NIT`, `NIS` |
| `RENAVAM` | | | `RENAVAM` |
| `PASSAPORTE` | | | `passaporte` + `FZ123456` |
| `PLACA` | `ABC-1234`, Mercosul `BRA2E19` | | `placa` + `ABC1234` |
| `AGENCIA`, `CONTA` | | | `agência`, `ag.`, `conta`, `c/c` |
| `PIX` (chave aleatória) | | | `pix`, `chave` |
| `CARTAO` | | 13 a 19 dígitos com Luhn | |
| `TELEFONE` | `(11) 98765-4321`, `+55 11 98765-4321`, `5511987654321` | celular com DDD: `11987654321` | |
| `EMAIL` | `maria@exemplo.com.br` (inclui o JID do WhatsApp) | | |
| `CEP` | `05422-030` | | |
| `NASCIMENTO` | | | `nascimento`, `nascido em`, `aniversário` + data |
| `ENDERECO` | `Rua das Flores, 123, ap 45` (tipo de via + nome com maiúscula + número) | | |
| o que você quiser | dicionário (`PESSOA`, `LOCAL`, `EMPRESA`...) | | |
| `PESSOA` fora do dicionário | opcional, por NER com o [Presidio](https://microsoft.github.io/presidio/) | | |

As regras de dígito de CPF, CNPJ, CNH, título e CNS foram conferidas contra a biblioteca
[validate-docbr](https://github.com/alvarofpp/validate-docbr) em centenas de milhares de números; onde as fontes
divergem (título de eleitor de SP e MG), o proxy aceita as duas regras.

O dicionário é a parte que mais importa: nomes da família, contatos, endereço. Ele ignora maiúsculas e só casa a palavra
inteira. Liste também as formas curtas (`Maria Souza` e `Maria`). Ele aceita qualquer texto, não só nomes: um número de
conta ou de matrícula que você queira sempre mascarado pode ir numa lista própria.

## Instalação

Precisa de Docker com Compose. Não há imagem publicada; o build é local.

```bash
git clone https://github.com/rugolini/llm-mask-ptbr.git
```

```bash
cd llm-mask-ptbr && mkdir -p config data
```

```bash
cp config.example.yaml config/config.yaml && cp dictionary.example.yaml config/dictionary.yaml && cp docker-compose.example.yml docker-compose.yml
```

Edite `config/config.yaml` (no mínimo o `upstream`) e `config/dictionary.yaml` (os seus nomes).

O contêiner roda como o uid `10001`. A pasta `data` precisa aceitar escrita dele:

```bash
sudo chown 10001 data
```

Suba e confira:

```bash
docker compose up -d --build
```

```bash
curl http://127.0.0.1:8400/_mask/health
```

Deve responder `{"status":"ok","mode":"shadow"}`.

### Sem Docker

```bash
pip install git+https://github.com/rugolini/llm-mask-ptbr.git
```

```bash
LLM_MASK_CONFIG=config/config.yaml LLM_MASK_VAULT=data/vault.db llm-mask-ptbr
```

## Configuração

`config/config.yaml`:

```yaml
upstream: https://openrouter.ai/api   # para onde o pedido segue depois da máscara
mode: shadow                          # shadow (só conta) ou mask (mascara)
vault: /data/vault.db                 # mapa valor ↔ marcador; mantenha num volume
unmasked_models: [local]              # modelos de casa: passam sem máscara
# detectors: [...]                    # todos ligados por padrão; liste para restringir
dictionary_file: dictionary.yaml      # relativo a este arquivo
allow:                                # nunca mascarar
  - suporte@exemplo.com.br
```

`config/dictionary.yaml`, um tipo por lista (o nome do tipo vira o marcador; use maiúsculas):

```yaml
PESSOA:
  - Maria Souza
  - Maria
LOCAL:
  - Rua das Flores, 123
```

Variáveis de ambiente vencem o arquivo: `LLM_MASK_UPSTREAM`, `LLM_MASK_MODE`, `LLM_MASK_VAULT`, `LLM_MASK_HOST`,
`LLM_MASK_PORT`. `LLM_MASK_CONFIG` diz onde está o arquivo. Mudou a configuração ou o dicionário: reinicie o contêiner.

O `upstream` é a base; o caminho que o cliente pede é somado a ela. Cliente chamando `/v1/chat/completions` com
`upstream: https://openrouter.ai/api` chega em `https://openrouter.ai/api/v1/chat/completions`. A chave de API é a do
cliente: o proxy repassa os cabeçalhos `Authorization` e `x-api-key` sem guardar nada.

## Como pôr em uso

Faça em três passos. O primeiro não muda nada no que o provedor recebe.

**1. Modo sombra.** Deixe `mode: shadow` e aponte o cliente para o proxy:

```python
# OpenAI SDK, ou qualquer cliente compatível
client = OpenAI(base_url="http://127.0.0.1:8400/v1", api_key="a-sua-chave")

# Anthropic SDK
client = Anthropic(base_url="http://127.0.0.1:8400", api_key="a-sua-chave")
```

Num agente dentro do Docker, ponha o proxy na mesma rede e troque o endereço do gateway pelo dele
(`http://llm-mask:8400/v1`).

**2. Medir.** Use o agente normalmente por uns dias e olhe:

```bash
curl http://127.0.0.1:8400/_mask/stats
```

```bash
docker compose logs llm-mask | tail
```

Cada pedido gera uma linha com contagens, nunca com os valores:

```json
{"path": "/v1/chat/completions", "model": "gpt", "action": "shadow", "found": {"PESSOA": 3, "CPF": 1}, "status": 200, "ms": 412}
```

Contagem de `PESSOA` baixa demais para o que você sabe que passou por ali quer dizer dicionário incompleto.

**3. Ligar.** Troque para `mode: mask` e reinicie. Teste com uma frase que tenha um nome do dicionário e confira no
painel do provedor (ou no log do seu gateway) que chegou o marcador.

**Voltar atrás:** aponte o `base_url` do cliente de novo para o provedor. O proxy não guarda estado do cliente.

## Senhas e chaves: usadas, nunca mostradas

Senha e chave de API têm regra própria, mais dura que a dos outros dados.

**Como são reconhecidas** (marcadores `[SENHA_n]` e `[SEGREDO_n]`):

- **Pelo rótulo:** `senha: ...`, `password = "..."`, `"api_key": "..."`, `DB_PASSWORD=...`, `Authorization: Bearer ...`,
  `usuario:senha@` numa URL. Em texto corrido ("a senha é ..."), só o que tem cara de senha: algum dígito ou símbolo.
- **Pelo formato de chave conhecida:** `sk-...`, `ghp_...`, `github_pat_...`, `glpat-...`, `AKIA...`, `AIza...`, `xox?-...`,
  JWT (`eyJ...`), chave do age, bloco `-----BEGIN ... PRIVATE KEY-----`.
- **Pelo valor exato:** os que você listar em `secrets` ou num `secrets_file` (um por linha) são mascarados onde aparecerem.
- **Pela memória do proxy:** um valor que já foi mascarado como segredo passa a ser mascarado sempre, com ou sem rótulo.
  Sem isso, a senha digitada por uma ferramenta voltaria em claro no histórico do pedido seguinte.

Variável (`${SENHA}`), campo de modelo (`{{...}}`, `<sua-chave>`), asteriscos e `null` não são tratados como segredo.

**Onde o valor é devolvido:** em lugar nenhum, por padrão. Nem no texto da resposta, nem para o próprio usuário. Só nos
argumentos das ferramentas listadas em `secret_tools`:

```yaml
secret_tools: [browser_type]   # só esta ferramenta recebe a senha de verdade
```

Assim uma página maliciosa que mande o modelo "pesquisar por `[SENHA_1]`" ou enviá-la numa mensagem recebe o marcador,
não a senha. Liste só ferramentas que escrevem num campo; nunca busca na web, envio de mensagem, pedido HTTP ou terminal.

O que continua passando: senha dita sem rótulo, fora da lista e nunca vista antes ("é abacaxi42").

## O aviso ao modelo

Sem explicação, os modelos tratam `[PESSOA_1]` como campo de formulário por preencher e se recusam a agir ("preciso dos
valores reais"). Aconteceu nos testes com OpenRouter e Anthropic. Por isso, no modo `mask`, o proxy acrescenta um aviso
fixo ao fim do prompt de sistema dizendo que os marcadores são dados reais protegidos e devem ser copiados como estão.
O texto é sempre o mesmo e vai depois do trecho em cache, então o cache do provedor continua valendo.

Para trocar o texto, use `notice: "..."` no `config.yaml`; `notice: ""` desliga.

Com o aviso, um efeito colateral bom: ao pedir para soletrar um CPF mascarado, um modelo respondeu `[-C-P-F-_-1-]` e
outro se recusou a quebrar o marcador.

## Nomes fora da lista (Presidio)

O dicionário só pega o que está nele. Para nomes novos, ligue a detecção por NER do Presidio com o modelo de português
do spaCy. Construa a imagem com `NER=1` (no `docker-compose.yml`: `build: {context: ., args: {NER: "1"}}`) e acrescente:

```yaml
ner:
  model: pt_core_news_lg
  entities: {PERSON: PESSOA}
  threshold: 0.5
```

Antes de ligar, saiba o custo. Medido num MacBook Air M5, texto de 50 mil caracteres, modelo pequeno (`pt_core_news_sm`):

| Detecção | Primeira vez | Texto repetido |
|---|---|---|
| Regras + dicionário de 2 mil nomes | 180 ms | menos de 1 ms |
| Presidio (NER) | 860 ms | menos de 1 ms |

O texto repetido sai do cache, e num agente quase tudo se repete: o histórico volta inteiro a cada pedido.

O NER erra para os dois lados. Na frase "a Fernanda Oliveira ligou para o Carlos em Curitiba sobre o servidor Unraid e
o Caddy", o modelo pequeno achou `Fernanda Oliveira` como pessoa, mas marcou `Carlos` e `Unraid` como lugar e `Caddy`
como empresa. Por isso o padrão é só `PERSON`, e os termos técnicos que ele confundir vão para o `allow`. Rode em modo
sombra antes e compare as contagens com e sem NER.

## Limites

Isto é pseudonimização: reduz o que sai de casa, não garante anonimato.

- **Nome fora do dicionário passa**, a não ser que o NER pegue. Apelido, erro de digitação e nome em minúsculas também.
- **O contexto ainda identifica.** "O marido de [PESSOA_1], que trabalha na empresa X e mora no bairro Y" diz quem é.
  Dados sensíveis da LGPD (saúde, religião, opinião política) e outros textos livres não são detectados.
- **Valores e datas passam de propósito.**
- **Número em campo numérico do JSON não é visto.** Um CPF enviado como número (`{"cpf": 52998224725}`) em argumento de
  ferramenta passa; só texto é inspecionado.
- **Imagens, áudio e arquivos anexos não são inspecionados.** As definições de ferramenta (`tools`) também não.
- **Blocos de raciocínio (`thinking`) não são alterados**, nem na ida nem na volta: o provedor assina esses blocos e
  recusa o pedido seguinte se o texto mudar. O raciocínio aparece para o cliente com os marcadores.
- **O modelo pode estragar um marcador** (escrever `PESSOA 1` em vez de `[PESSOA_1]`). Nesse caso ele volta como veio.
- **Mapa fixo permite correlação.** O provedor vê que `[PESSOA_1]` é sempre a mesma pessoa, sem saber quem.
- **RG e conta bancária sem pontuação e sem a palavra antes passam**: cada estado e cada banco tem sua regra de dígito.
- **Endereço em minúsculas ou sem número passa**; data de nascimento só é mascarada com a palavra antes.
- **Código de 3 letras e 4 dígitos** (`INC-0042`) é mascarado como placa. Não vaza nada, mas o modelo vê um marcador.
- Só as rotas listadas em [O que ele faz](#o-que-ele-faz). A Responses API da OpenAI é recusada.

## Segurança

- **O cofre guarda os valores originais em texto puro** (`vault.db`, SQLite, permissão `600`). Ele mora no seu
  servidor; trate como dado sensível e inclua no backup cifrado, não em repositório.
- **Não exponha a porta.** O proxy não tem login próprio. Quem alcança a porta consegue ver as contagens e, com uma
  chave válida do provedor, usar o proxy para trocar marcador por valor. Deixe-o numa rede Docker interna ou em
  `127.0.0.1`.
- O dicionário tem dado pessoal: o `.gitignore` já deixa `config/` e `data/` de fora.
- Os logs levam caminho, modelo, contagens por tipo, status e tempo. Nunca o texto.

## Desenvolvimento

```bash
uv sync --extra ner
```

```bash
uv run python -m spacy download pt_core_news_sm
```

```bash
uv run python -m unittest discover -s tests
```

Os testes ficam em duas interfaces: o motor (`Masker.mask` / `restore`) e o proxy HTTP de ponta a ponta contra um
provedor falso, que devolve o que recebeu em pedaços de 1 a 11 caracteres para exercitar todo corte possível de um
marcador. Sem o extra `ner`, o teste do Presidio é pulado.

| Arquivo | Papel |
|---|---|
| `llm_mask_ptbr/detectors.py` | documentos, telefone, e-mail, endereço, dicionário |
| `llm_mask_ptbr/engine.py` | `Masker`: mascara, desfaz, conta |
| `llm_mask_ptbr/vault.py` | mapa valor ↔ marcador em SQLite |
| `llm_mask_ptbr/payload.py` | onde está o texto num pedido OpenAI ou Anthropic |
| `llm_mask_ptbr/stream.py` | desfaz a máscara em eventos SSE |
| `llm_mask_ptbr/proxy.py` | o servidor |
| `llm_mask_ptbr/ner.py` | detector opcional com Presidio |

## English summary

`llm-mask-ptbr` is a small self-hosted proxy that replaces personal data with stable tokens (`[PESSOA_1]`, `[CPF_1]`)
before a request leaves for a cloud LLM, and restores the real values in the reply. It is built for Brazilian
Portuguese text: CPF, CNPJ, RG, CNH, voter ID, SUS card, PIS, bank accounts, Brazilian phone formats, street addresses,
CEP, and your own dictionary of names.

- OpenAI Chat Completions and Anthropic Messages, streaming included; tool-call arguments are masked and restored.
- The same value always gets the same token (SQLite vault), so provider prompt caching keeps working.
- Amounts and dates pass through on purpose. Models you run at home can be exempted.
- Shadow mode counts what would be masked without changing the request. Requests it cannot inspect are refused.
- Optional name detection through Microsoft Presidio with a Portuguese spaCy model.

It is pseudonymization, not a guarantee of anonymity: names missing from the dictionary pass, and context can still
identify a person. The vault stores the original values in plain text on your own server. See the sections above
(in Portuguese) for installation, configuration and the full list of limits.

## Licença

MIT.
