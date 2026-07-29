<div align="center">

# 🛠️ ALC — Agentic Layer Compiler & Runtime

**Declare uma vez como seus agentes devem trabalhar. Rode em qualquer coding engine — com as garantias embutidas.**

![python](https://img.shields.io/badge/python-3.12+-blue)
![status](https://img.shields.io/badge/status-experimental-orange)
![engines](https://img.shields.io/badge/engines-claude%20code%20·%20gemini%20·%20mock-8A2BE2)

[English](README.md) | **Português**

</div>

---

O ALC é um **control plane para agentic coding**. Ele mantém as boas práticas — verificação, foco, isolamento, revisão — *fora* do modelo, em código determinístico comum. O coding engine (Claude Code, Gemini, …) vira um executor fino e trocável.

A ideia central: boas práticas deixam de ser disciplina que você precisa lembrar e viram defaults que você não consegue pular.

## ✨ Destaques

- 🛡️ **Garantias fora do modelo** — o Assurance Loop roda seus checks e repara até passarem. Nada é dado como pronto enquanto não estiver de fato.
- 🔌 **Agnóstico de engine** — Claude Code, Gemini ou um Mock gratuito, atrás de um contrato de três métodos. Troque com uma flag; o control plane não muda.
- 🎯 **Um agente, um propósito** — cada tarefa é um Single Mandate focado. Sem poluição de contexto.
- 🧩 **Composável** — Blueprints → Flows → um Conductor que transforma um objetivo nos Flows certos.
- 🌙 **Não-assistido** — largue tarefas numa fila; o `alc tick` (via cron) as drena, isoladas, enquanto você está fora.
- 🧠 **Specialists** — agentes que mantêm um Knowledge File e ficam melhores numa área com o tempo.
- 🔒 **Isolado** — `--isolate` roda o trabalho numa branch descartável de git-worktree, mantendo sua working tree limpa.

## 🚀 Início Rápido

> Novo no ALC? O **[guia de primeira execução](docs/first-run.md)** te leva do install a uma mudança verificada, com as arestas sinalizadas.
>
> Se você configurou com `uv sync`, prefixe os comandos abaixo com `uv run` (ex.: `uv run alc lint`).

**Instalar**

```bash
uv tool install alc-runtime          # instala o comando `alc`
uv tool install "alc-runtime[ui]"    # …com a UI web (dashboard, runs ao vivo)
```

> O pacote no PyPI é **`alc-runtime`**; ele coloca o comando **`alc`** no seu PATH.
>
> **Ainda não está no PyPI?** Instale o build atual direto do git:
> `uv tool install "alc-runtime[ui] @ git+https://github.com/gifflet/alc.git"`.
> Desenvolvendo o próprio ALC? `uv sync` num clone e prefixe os comandos com `uv run`.

**Preparar um projeto** — três passos de zero a um Operator Layer validado:

```bash
cd seu-projeto
alc init --setup     # 1. gera o .alc/ (detecta o stack) + instala a skill do editor
alc onboard          # 2. adota os checks que o projeto JÁ declara (targets de Makefile,
                     #    scripts de package.json) — propõe primeiro, você aprova
alc lint             # 3. valida o Operator Layer
```

**Rodar**

```bash
# Seguro por padrão: o manifest gerado usa o engine Mock (gratuito, sem chamar modelo).
alc run chore "remover o endpoint de export não usado"

# Use um engine real quando quiser:
alc run chore "organizar os imports"           --engine claude-code
alc run chore "organizar os imports"           --engine claude-code --tier standard
alc flow ship "adicionar entrada no changelog" --engine claude-code --isolate
alc conduct "o README está desatualizado, atualize as docs" --engine claude-code --parallel
alc primer new meu-contexto                    # cria .alc/primers/meu-contexto.md
alc tick --concurrency 4                       # drena a fila 4 tarefas ao mesmo tempo
```

## 🧭 Comandos

**Por intenção** — o caminho rápido quando você já sabe o que quer:

| Intenção | Use |
|---|---|
| **Descobrir** o projeto | `alc status` · `alc lint` · `alc team status` · `alc audit` |
| **Rodar** uma unidade verificada | `alc run <blueprint> "…"` · `alc spike "…"` · `alc flow <flow> "…"` |
| **A partir de um objetivo**, o ALC planeja | `alc conduct "<objetivo>"` |
| **Explorar** alternativas | `alc explore … --variants N` → `alc compare --diff` → `alc adopt` |
| **Rodar não-assistido** | `alc enqueue …` → `alc tick` · `alc cycle` / `alc loop` |
| **Integrar** o resultado | `alc land` · `alc discard` |

<details>
<summary><strong>Referência completa de comandos</strong> (clique para expandir)</summary>

| Comando | O que faz |
|---|---|
| `alc init [--setup]` | Gera um Operator Layer `.alc/` padrão; detecta o stack do projeto e cria checks reais (e instala a skill do editor) |
| `alc onboard [--yes] [--stage NOME]` | Adota os checks que o projeto JÁ declara (targets de Makefile, scripts de `package.json`) num check_set `project` e os fia nos seus Blueprints — propõe primeiro, aplica na aprovação (`--yes` pula o prompt); `--stage` também registra o estágio do produto |
| `alc lint` | Valida o Operator Layer contra o Policy Gate |
| `alc run <blueprint> "<tarefa>"` | Roda um Blueprint como um Single Mandate verificado; `--tier NOME` substitui o compute tier para esta invocação |
| `alc spike "<tarefa>"` | Açúcar sobre o Blueprint `spike` do Prototyper (`mode: spike`) — uma exceção cercada ao gate de checks: força isolamento, zero reparos, proíbe commit/auto-merge, fica fora do streak do Scorecard |
| `alc flow <flow> "<tarefa>"` | Roda um pipeline multi-estágio (ex.: plan → build); `--tier NOME` aplica a todos os estágios; estágios verify-only atuam como check gates puros (só checks, sem turno de engine) |
| `alc conduct "<objetivo>" [--parallel]` | Deixa o ALC escolher quais Flows rodar; `--parallel` despacha unidades independentes em paralelo em worktrees isoladas; `--enqueue` para enfileirar |
| `alc specialist <nome> "<tarefa>"` | Roda um Specialist de área (Recall → Act → Learn) |
| `alc tick [--concurrency N]` | Drena a fila de tarefas — chame isto via cron; `--concurrency N` processa até N tarefas isoladas em paralelo |
| `alc enqueue <nome> "<tarefa>"` | Escreve uma tarefa direto na fila, sem turno de planner; `--kind flow\|specialist`, `--touches` serializa automaticamente edições que se sobrepõem, `--from-file` enfileira várias de uma vez |
| `alc land [branch...] [--all] [--push\|--pr]` | Integra branches de demanda `alc/*` na branch atual (cherry-pick linear); sem argumentos, lista as não mergeadas; `--push` empurra a branch atual para o remote de entrega depois, `--pr` também abre um pull request via `gh` — uma falha de push/PR nunca reprova o land |
| `alc discard [branch...] [--all-unmerged]` | Apaga branches `alc/*` à força, poda worktrees obsoletas (`--worktrees`) ou remove bundles antigos (`--bundles --older-than N`) — sempre pede confirmação |
| `alc explore <blueprint> "<tarefa>" --variants N` | Roda N variantes da mesma unidade em worktrees isoladas (produto cartesiano opcional `--engine`/`--tier`); nunca faz auto-merge — imprime uma tabela por variante (branch, checks, scorecard, custo, diffstat) |
| `alc compare <branch\|stem>...` | Põe as variantes exploradas lado a lado — as mesmas colunas que o `explore` imprime |
| `alc adopt <branch>` | Integra a variante escolhida e descarta as demais branches `alc/variant-*` perdedoras — sempre pede confirmação |
| `alc primer new <nome>` | Cria um novo arquivo Primer em `.alc/primers/<nome>.md` |
| `alc new <kind> <nome>` | Cria um novo blueprint/flow/specialist/loop/primer a partir de um template do core; `--from NOME` clona uma unidade existente |
| `alc status [--json]` | Retrato de saúde num único comando, para monitoração: tarefas pendentes, falhas em aberto, estado dos loops, branches não mergeadas — sempre sai com código 0 |
| `alc runs list\|show\|tail` | Inspeciona os run logs (`.alc/runs/*.jsonl`): lista os runs recentes, mostra um por inteiro, ou exibe os últimos N eventos |
| `alc audit --since 7d` | Agrega os reports arquivados da fila numa janela de tempo: contagem de tarefas, totais/médias do Scorecard, arquivos alterados e uso/custo de engine |
| `alc metrics [--check NOME] [--json]` | Mostra a série temporal de um metric check gravada no ledger do projeto: valor, delta contra a medição anterior e tendência — somente leitura, populada por checks `metric` (`alc run`/`alc flow`/`alc tick`/…) |
| `alc team hire\|list\|retire\|status` | Cria, lista ou aposenta um Archetype Pack — os cinco são `prototyper`, `builder`, `sweeper`, `grower`, `maintainer`. O hire é ADITIVO (escreve só os arquivos que faltam do pack; `--force` sobrescreve). `alc init --stage pre-pmf\|growth\|strong-pmf` instala o combo daquele estágio; `status` também mostra o Mix Health quando `stage` está declarado |
| `alc checks audit [--json]` | Redetecta o(s) stack(s) e PROPÕE upgrades de check_set contra o Manifest — nunca escreve; aponta checks ainda comentados por falta de binário |
| `alc signal ingest --kind K --source S --title T` | Ingere um sinal tipado de uso real (`error`\|`feedback`\|`issue`\|`review`); `--from-file PATH` aceita um payload JSON já formado; `alc signal list [--json]` mostra o que está pendente de consumo por um loop de replenish `signals` |
| `alc serve --webhook [--host H] [--port P] [--token T]` | Uma porta HTTP mínima sobre a ingestão de sinais e o caminho de enqueue — `POST /signal`, `POST /enqueue`, `GET /health`; só valida e escreve, nunca executa; `alc tick`/`alc cycle` drena o que chega |
| `alc artifacts [<stem>] [--json]` | Lista os artefatos de evidência e2e capturados por um run (screenshots, respostas curladas, o log do health poll) — a prova de que o `capture:` de um run `needs_service` de fato verificou o app ao vivo; sem argumento, usa o run mais recente com artefatos |
| `alc schedule install\|list\|remove <tick\|cycle NOME> --every 15m` | Gera e administra a entrada de cron (ou imprime a linha para colar, quando não há `crontab` disponível) que dispara `alc tick`/`alc cycle` num intervalo — install idempotente, remove restrito ao que o próprio ALC marcou |
| `alc setup [--engine]` | Instala/atualiza a skill user-level do editor (Claude Code ou Gemini) |
| `alc ui [--port 8642]` | Sobe a IDE web (dashboard, fila, runs ao vivo, loops, config) — requer o extra opcional `ui` |

Adicione `--engine claude-code|gemini|mock` para escolher o executor e `--isolate` para conter as edições numa branch de git-worktree.

Blueprints suportam `max_repairs` para limitar o orçamento de reparos do Assurance Loop, e `check_set` para referenciar um conjunto de checks nomeado e reutilizável declarado no Manifest. Checks rodam por código de saída sem shell por padrão; adicione um `shell:` one-liner a uma entrada de check para rodá-lo via `sh -c` (atenção: o resultado é decidido exclusivamente pelo código de saída — stdout/stderr são capturados e alimentam a diretiva de reparo, mas não afetam a decisão de passar ou falhar).

</details>

## 🖥 Web UI

`alc ui` sobe uma IDE web local, single-user — uma sala de controle estilo IntelliJ para cada
projeto registrado: dashboard, fila, runs ao vivo (timeline do Assurance Loop), loops e config,
tudo atualizado em tempo real via WebSocket (sem refresh, nunca).

```bash
uv tool install "alc-runtime[ui]"   # ou: uv sync --extra ui
alc ui                              # http://127.0.0.1:8642 — frontend servido por default
```

O frontend vive em [`ui/`](ui/) (React + Vite + TypeScript). Fluxo de desenvolvimento:

```bash
cd ui && npm install
npm run dev        # dev server do Vite com proxy de /api e /ws para 127.0.0.1:8642
npm run build:alc  # publica o build de produção em src/alc/ui/static/ (gitignored; embarcado no wheel)
```

`--ui-dist PATH` serve um build alternativo; `--no-ui` sobe apenas API/WebSocket.

## 🧱 Como as peças se encaixam

O ALC vive num anel ao redor do seu codebase — o **Operator Layer** (`.alc/`), separado do código da aplicação:

- **Blueprint** — um template para uma classe de trabalho (chore, bug, feature…), com seus próprios checks e report.
- **Flow** — Blueprints compostos num pipeline; cada estágio é um mandato próprio, passando contexto adiante.
- **Conductor** — transforma um objetivo de alto nível nos Flows certos e os roda ou enfileira.
- **Specialist** — um agente com um Knowledge File de uma área, que melhora conforme trabalha.
- **Assurance Loop** — `Act → Verify → Repair`. Seus checks são a lei.
- **Scorecard** — acompanha Span / Passes / Streak / Touch, rumo à entrega hands-off.

## 🪜 Onde você está na escada

O ALC cresce com você: **Attended** (você roda) → **Detached** (roda sozinho a partir da fila) → **Conducted** (um Conductor conduz os Flows por você). Você não começa no topo — você sobe.

## 📚 Documentação

- [Conceitos e vocabulário](docs/concepts.md) — as palavras que o ALC usa e o modelo de dois planos
- [Arquitetura](docs/architecture.md) — o diagrama control plane / execution plane
- [Contrato da engine](docs/engine-contract.md) — o que é preciso para plugar um engine
- [MVP e roadmap](docs/mvp.md)

## 🧪 Status

Experimental, mas de verdade: cada feature tem cobertura de testes herméticos e foi validada ao vivo contra Claude Code e Gemini. Python 3.12 + uv, sem dependências pesadas.

## 📄 Licença

[MIT](LICENSE) © gifflet
