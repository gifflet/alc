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

> Se você configurou com `uv sync`, prefixe os comandos abaixo com `uv run` (ex.: `uv run alc lint`).

**Instalar**

```bash
uv sync                 # ambiente de desenvolvimento
# — ou instale o CLI globalmente —
uv tool install .       # disponibiliza um `alc` global
```

**Preparar um projeto**

```bash
cd seu-projeto
alc init --setup        # gera o .alc/ + instala a skill do editor (Claude Code por padrão)
alc lint                # confere se o Operator Layer está bem-formado
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

| Comando | O que faz |
|---|---|
| `alc init [--setup]` | Gera um Operator Layer `.alc/` padrão; detecta o stack do projeto e cria checks reais (e instala a skill do editor) |
| `alc lint` | Valida o Operator Layer contra o Policy Gate |
| `alc run <blueprint> "<tarefa>"` | Roda um Blueprint como um Single Mandate verificado; `--tier NOME` substitui o compute tier para esta invocação |
| `alc flow <flow> "<tarefa>"` | Roda um pipeline multi-estágio (ex.: plan → build); `--tier NOME` aplica a todos os estágios; estágios verify-only atuam como check gates puros (só checks, sem turno de engine) |
| `alc conduct "<objetivo>" [--parallel]` | Deixa o ALC escolher quais Flows rodar; `--parallel` despacha unidades independentes em paralelo em worktrees isoladas; `--enqueue` para enfileirar |
| `alc specialist <nome> "<tarefa>"` | Roda um Specialist de área (Recall → Act → Learn) |
| `alc tick [--concurrency N]` | Drena a fila de tarefas — chame isto via cron; `--concurrency N` processa até N tarefas isoladas em paralelo |
| `alc primer new <nome>` | Cria um novo arquivo Primer em `.alc/primers/<nome>.md` |
| `alc setup [--engine]` | Instala/atualiza a skill user-level do editor (Claude Code ou Gemini) |

Adicione `--engine claude-code|gemini|mock` para escolher o executor e `--isolate` para conter as edições numa branch de git-worktree.

Blueprints suportam `max_repairs` para limitar o orçamento de reparos do Assurance Loop, e `check_set` para referenciar um conjunto de checks nomeado e reutilizável declarado no Manifest. Checks rodam por código de saída sem shell por padrão; adicione um `shell:` one-liner a uma entrada de check para rodá-lo via `sh -c` (atenção: o resultado é decidido exclusivamente pelo código de saída — stdout/stderr são capturados e alimentam a diretiva de reparo, mas não afetam a decisão de passar ou falhar).

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

Ainda sem licença — adicione um arquivo `LICENSE` antes de compartilhar publicamente.
