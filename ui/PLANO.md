# ALC UI — Plano de Implementação

IDE web (estilo JetBrains) para acompanhar e gerenciar projetos que usam o **alc**
(Agentic Layer Compiler & Runtime) como ferramenta agêntica de desenvolvimento.

## Decisões de arquitetura (fechadas com o usuário)

| Decisão | Escolha |
|---|---|
| Backend | FastAPI **dentro do repo alc**, novo comando `alc ui` (extra opcional `alc[ui]`) |
| Frontend | **Monorepo** (decisão 2026-07-12): vive em `ui/` dentro do repo alc (React + Vite + TS); o repo alc-ui foi descontinuado |
| Distribuição | `npm run build:alc` (em `ui/`) publica em `src/alc/ui/static/` (gitignored); wheel/release sai com a UI embarcada — versionamento atômico API ↔ UI |
| Deploy | Local, single-user, localhost, **sem autenticação** |
| Observabilidade | **Pode modificar o alc**: event-log JSONL por run em `.alc/runs/` emitido pelo control plane — qualquer run (UI, terminal, cron) aparece ao vivo |
| Edição | Formulários estruturados + aba "Source" com Monaco (estilo settings do IntelliJ) |
| Processo | TDD, KISS, SOLID, sem over-engineering; desenvolvimento pelo agente programador (opus); UI sem emojis, ícones (lucide) |

## Visão geral

```
┌────────────────────────────┐        ┌─────────────────────────────────────┐
│  alc/ui/ (frontend)        │  HTTP  │  alc (mesmo repo, Python)           │
│  React + Vite + TS SPA     │ ─────► │  `alc ui` → FastAPI + WebSocket     │
│  dark theme JetBrains-like │  WS    │  · importa alc.models (pydantic)    │
│  Monaco · lucide · TanStack│ ◄───── │  · registry de projetos (~/.alc/ui) │
└────────────────────────────┘        │  · file-watching de .alc/ (watchfiles)│
                                      │  · dispara CLI alc em subprocess    │
                                      └─────────────┬───────────────────────┘
                                                    │ lê/escreve
                                     ┌──────────────▼──────────────┐
                                     │ projetos rastreados          │
                                     │ ~/git/proj-a/.alc/           │
                                     │ ~/git/proj-b/.alc/           │
                                     └─────────────────────────────┘
```

## Fase 0 — Observabilidade no alc (repo alc)

Novo módulo `src/alc/events.py` (stdlib puro, sem dependências):

- Emitter baseado em `contextvars`: `bind_run_log(path)` (context manager) + `emit(event, **payload)`.
  Sem log vinculado → no-op. Emissão **best-effort**: falha de I/O nunca derruba um run.
- Um arquivo por invocação top-level: `.alc/runs/<UTC-ts>-<kind>-<slug>-<uid>.jsonl`.
  No `alc tick`/fanout, cada task vincula seu próprio arquivo na thread worker.
- Eventos v1 (linha JSON com `ts` ISO-8601 UTC + `event` + payload):
  - `mandate_started` {blueprint, task, engine, model}
  - `act_started` {attempt} · `act_finished` {attempt, ok, usage?}
  - `verify_started` {attempt, checks} · `check_finished` {attempt, name, passed, output_tail}
  - `mandate_finished` {success, attempts, scorecard}
  - `flow_started` {flow, task, stages} · `stage_started`/`stage_finished` · `flow_finished` {success, scorecard, commit_sha?}
  - `task_started` {task_file, name, kind} · `task_finished` {success, branch?, merged?}
- Pontos de integração: `runner.py` (mandato), `assurance.py` (act/verify/check), `flow.py` (stages), `queue.py` (task lifecycle nos workers do tick).
- UI detecta "run ativo": último evento não-terminal + mtime do arquivo.

## Fase 1 — Backend `alc ui` (repo alc)

- Extra `[project.optional-dependencies] ui = [fastapi, uvicorn, watchfiles]`; import lazy no CLI
  (`alc ui` sem extra instalado → mensagem clara).
- `alc ui [--port 8642] [--ui-dist PATH] [--no-ui]` — serve API, WS e o frontend **por default**.
  Resolução do frontend: `--ui-dist` explícito (inválido → erro) → env `ALC_UI_DIST` (inválido →
  warning) → embarcado `src/alc/ui/static/` (gitignored; populado por `npm run build:alc` no repo
  alc-ui) → API-only com instrução. `--no-ui` desabilita explicitamente.
- **Registry de projetos**: `~/.alc/ui/projects.json` — add/remove por path absoluto; valida `.alc/`.
- **API REST** (`/api/projects/{id}/…`), sempre validando com os modelos pydantic do alc:
  - manifest GET/PUT · blueprints/flows/specialists/primers/prompts/loops CRUD (raw + parsed)
  - queue: pending + done (com reports) · enqueue · retry (um/todos) · delete pendente
  - loops: state + ledger · runs: lista + eventos de um run
  - lint (violations) · engines (health, tiers) · exec: run/flow/tick/conduct/cycle/specialist
- **Execuções**: `RunManager` — subprocess do CLI `alc`, stdout/stderr canalizados ao WS, cancelamento (terminate), status em memória.
- **WebSocket** `/ws`: subscribe por projeto; eventos tipados (`run_event`, `queue_changed`, `report_added`, `loop_changed`, `config_changed`, `exec_output`).
- **File-watching**: watchfiles sobre `.alc/` de cada projeto registrado → publica no WS.

## Fase 2 — Frontend shell (este repo)

Stack: **React 19 + Vite + TypeScript**, Tailwind CSS v4, lucide-react, TanStack Query,
react-router, `@monaco-editor/react`. Testes: **Vitest + React Testing Library**.
Design guiado pela skill *frontend-design* — tema escuro denso estilo IntelliJ/Darcula,
minimalista, ícones (nunca emojis).

Layout IDE:
- Activity bar esquerda (ícones): Dashboard · Queue · Runs · Loops · Conduct · Config
- Tool window esquerda: árvore do projeto (blueprints, flows, specialists, primers, prompts)
- Área central com **tabs** (editores e detalhes)
- Painel inferior: console de run ao vivo + Problems (lint)
- Status bar: projeto ativo, saúde dos engines, estado da conexão WS

Entregas da fase: shell + navegação, seletor/registro de projetos, views **read-only** em
tempo real (dashboard com scorecard, queue, runs com timeline Act/Verify/Repair, loops com ledger).

## Fase 3 — Mutations

Editores form + Monaco (manifest, blueprints, flows, specialists, loops, primers, prompts) com
validação server-side (pydantic) antes de salvar; enqueue e retry pela UI; delete de task pendente.

## Fase 4 — Execuções pela UI

Disparar `run`/`flow`/`tick`/`conduct`/`cycle`/`specialist` com console ao vivo (exec_output +
eventos do run), cancelamento, e fluxo do Conduct (goal → plano → run/enqueue).

## Fase 5 — Polimento

Problems view (lint) com navegação ao arquivo, health de engines na status bar, análise do
scorecard (histórico via reports + ledger), atalhos de teclado, empty states.

## TDD

- Backend (alc): pytest, testes herméticos com projetos em `tmp_path` (padrão já existente no
  repo), `TestClient` do FastAPI, engine mock. Teste antes da implementação em cada unidade.
- Frontend: Vitest + RTL por componente/hook/serviço; WS mockado; MSW para API se necessário.

## Critérios transversais

- KISS/SOLID, sem over-engineering: nada de camadas especulativas; abstração só quando o
  segundo caso de uso existir.
- Live-first: toda view reflete disco/execuções em tempo real via WS; nunca exigir refresh.
- O backend nunca reimplementa lógica do alc: parse/validação via `alc.models`, execução via CLI.
