# TradingAgents Sidecar Design

Date: 2026-04-12  
Status: Proposed after brainstorming, pending user review  
Scope: Add a `TradingAgents` + Hermes sidecar to the existing OpenClaw MNQ intraday paper-trading stack

## Goal

Build a sidecar that makes the trading system smarter every session without making it less safe.

In plain language:
- the deterministic spine should keep doing the actual trading
- `TradingAgents` should add market judgment, not execution
- `Hermes` should remember what the AI thought, what changed, and whether it helped
- the AI layer should earn influence quickly when it proves value, but it should never bypass risk or execution boundaries

Success means:
- better selectivity
- lower drawdown
- at least similar expectancy, ideally better
- fast learning from each session

Drawdown improvement is the primary success metric if trade-offs appear.

## North Star

The north star is a **self-improving filter on top of a safe trader**.

The base trader is OpenClaw:
- `C3PO` finds setups
- `Sentinel` controls approvals and sizing
- `Forge` executes
- `Watchtower` can freeze or halt independently

The sidecar improves judgment:
- `TradingAgents` studies rich context and forms opinions
- `Hermes` records those opinions and scores them against what actually happened
- a compiler turns only the allowed subset of those opinions into strict session rules

The system should execute mechanically, think reflectively, and learn cautiously.

## Context

Current repo shape:
- deterministic intraday and swing trading engine
- current target instrument for this project is `MNQ`
- current preferred active intraday setup families are `ORB` and `TREND_PULLBACK`
- broader architecture work already exists around the Market State Bus, Policy Compiler, and AI overlays

This design does not replace the deterministic spine. It adds a scored policy sidecar around it.

## Approaches Considered

### 1. Conservative sidecar

Use `TradingAgents` for premarket research only, with no machine effect initially.

Pros:
- simplest to trust
- easiest to debug
- lowest operational risk

Cons:
- slower path to measurable value
- AI layer stays mostly advisory for too long

### 2. Hybrid policy sidecar

Use `TradingAgents` as a research sidecar and narrow policy input. Start with premarket-first influence, allow a small conservative machine effect early, and score every session through Hermes.

Pros:
- balances upside and control
- gets measurable AI influence into the loop quickly
- preserves deterministic boundaries
- supports fast promotion of proven ideas

Cons:
- more moving parts than a pure advisory layer
- requires disciplined policy contracts and scoring

### 3. Ambitious adaptive mesh

Let `TradingAgents` and Hermes continuously update the session with broader influence from early phases.

Pros:
- highest theoretical upside
- fastest path to a rich adaptive system

Cons:
- easiest to overbuild
- hardest to debug and trust
- too much authority too early

### Recommendation

Choose **Approach 2**.

It is ambitious in learning and promotion speed, but conservative in direct trading control. That is the right balance for a system that needs to improve quickly without losing safety.

## Design Principles

1. `TradingAgents` is a **sidecar**, not a trader.
2. `Hermes` is a **memory and scoring layer**, not a broker-facing actor.
3. The first live or paper influence is **narrowing-only**.
4. The system should have **wide perception and narrow action**.
5. Learning can be broad from day one, but authority must be earned.
6. Promotion should be fast once evidence exists, but impossible without evidence.
7. The deterministic spine must still make sense and remain defensible without the sidecar.

## First-Version Operating Model

### Before the open

`TradingAgents` runs as the primary sidecar job before the session.

It reads:
- market structure and price context
- macro calendar
- news and sentiment
- internal recent trade history

It produces:
- a human-readable briefing
- a machine-readable structured output for the compiler

`Hermes` journals:
- what `TradingAgents` saw
- what it concluded
- confidence and metadata

The Policy Compiler transforms the structured output into a strict session artifact.

### During the session

`C3PO` continues to generate deterministic setups, but only inside the session artifact constraints.

`Sentinel` remains the final authority on:
- approvals
- reductions
- max entries
- sizing
- overall risk posture

`Forge` still owns all execution.

`Watchtower` still owns independent freeze and halt authority.

Intraday refreshes are allowed later, but version 1 is **premarket-first**: one authoritative premarket sidecar run per session, no automatic intraday refreshes. Fixed intraday checkpoints are a version 2 extension after the scorer proves value.

### After the session

`Hermes` stores:
- the sidecar judgment
- the compiled session artifact
- trades taken
- trades blocked
- resulting outcomes

A deterministic scorer grades whether the sidecar helped:
- did blocked trades tend to be bad?
- did blocked trades remove too many good opportunities?
- did drawdown improve?
- did expectancy hold up or improve?

The sidecar then carries forward memory into the next session.

## Component Design

### 1. TradingAgents Adapter

Purpose:
- isolate `TradingAgents` from the rest of the repo
- translate its rich output into the repo's own strict structured contract

Responsibilities:
- collect allowed upstream inputs
- call `TradingAgents`
- normalize output into stable JSON
- produce a human briefing artifact

Non-responsibilities:
- no direct writing into broker-facing systems
- no direct sizing decisions
- no direct order permissions

This adapter lets the repo depend on a stable local contract rather than the internals of the upstream `TradingAgents` project.

### 2. Hermes Journal

Purpose:
- preserve session-to-session memory and create a durable audit trail for AI judgment

Responsibilities:
- store every sidecar run
- store the compiled session artifact
- store outcome summaries
- store blocked-vs-allowed trade context
- support replay and scoring

Non-responsibilities:
- no broker interaction
- no direct playbook publication
- no direct approval authority

### 3. Hermes Scorer

Purpose:
- measure whether the sidecar is helping

Responsibilities:
- compare sidecar judgments to actual outcomes
- compute blocked-good-trade rate
- compute blocked-bad-trade rate
- estimate drawdown effect
- estimate expectancy effect
- track confidence drift and consistency

This scorer should be deterministic code so its outputs are stable and reviewable.

### 4. Policy Compiler

Purpose:
- convert sidecar outputs into a strict session artifact that the deterministic spine can consume safely

Version 1 contract should support only:
- disallowed setups
- blocked time windows

Version 2 may add:
- entry count caps
- size multiplier caps

The compiler must:
- validate schema
- reject stale or malformed sidecar output
- attribute the source of every restriction
- fail closed to deterministic baseline rules

### 5. Session Artifact

The first version should treat this as a **session playbook** rather than a general AI command channel.

It should be:
- versioned
- timestamped
- easy to diff
- easy to replay
- strict enough that `C3PO` and `Sentinel` can consume it deterministically

### 6. Playbook Enforcement

Minimal enforcement path in version 1:
- `C3PO` respects setup bans and blocked windows
- `Sentinel` continues to enforce baseline approval and sizing rules only
- `Forge` remains unchanged
- `Watchtower` remains unchanged

Version 2 may let `Sentinel` enforce entry caps and size caps once the scorer shows the sidecar is adding value.

This keeps the first implementation small while still giving the sidecar measurable leverage.

## Authority Boundaries

### What the sidecar can do

`TradingAgents` may:
- classify the session
- estimate event hazard
- recommend blocked windows
- recommend banning setups
- recommend capping aggression
- produce narrative context
- propose shadow ideas for later scoring

`Hermes` may:
- remember prior sessions
- score prior judgments
- generate reports
- feed scored context into future research workflows

### What the sidecar cannot do

Neither `TradingAgents` nor Hermes may:
- place, modify, or cancel orders
- bypass `Sentinel`
- bypass `Forge`
- increase size beyond the deterministic baseline
- auto-change core strategy logic
- mutate production code

All machine influence must pass through the compiler and then through the deterministic spine.

## Ambition Model

This design is intentionally ambitious in **learning** and **promotion speed**, not in immediate control breadth.

The guiding idea is:

**wide perception, narrow action**

That means:
- broad input context is allowed early
- broad journaling is allowed early
- broad shadow experimentation is allowed early
- narrow direct influence is allowed early
- broader influence is promoted quickly if the scoring evidence supports it

## Promotion Model

Promotion is where the ambition lives.

### Stage 1: observe broadly

The sidecar can produce rich judgments and shadow policy ideas from day one.

### Stage 2: influence narrowly

Early machine influence is limited to:
- setup bans
- blocked windows

After the sidecar proves itself, the next promotion step is:
- entry count caps
- size caps

### Stage 3: score every session

After each session, Hermes scoring determines whether the sidecar:
- improved drawdown
- preserved expectancy
- improved selectivity

### Stage 4: promote quickly

When a sidecar behavior proves itself over **20 scored sessions** with lower drawdown and no worse than 10% expectancy degradation versus baseline, it can move quickly:
- shadow only
- weak policy influence
- stronger paper influence
- later tiny live influence

The system is designed to be fast at promoting winners and strict about rejecting unproven behavior.

## Data Flow

1. Premarket context is collected.
2. `TradingAgents` produces a structured judgment bundle plus briefing text.
3. `Hermes` journals the sidecar run.
4. The compiler produces a strict session playbook.
5. `C3PO` generates deterministic setups within that playbook.
6. `Sentinel` validates and sizes.
7. `Forge` executes approved trades.
8. `Watchtower` supervises independently.
9. Post-session, Hermes scoring compares judgments and outcomes.
10. The next session can use that memory, but all live influence remains bounded by the same compiler and deterministic guards.

## Error Handling

### If TradingAgents fails

- no trading halt by default
- compiler falls back to baseline session rules
- Hermes records the failure

### If Hermes fails

- sidecar memory and scoring pause
- deterministic trading continues
- no new adaptive trust should be granted while scoring is degraded

### If the compiler fails

- fail closed to baseline deterministic rules
- no sidecar influence for that session or refresh window

### If scoring detects harm

- demote the relevant sidecar behavior back to shadow or report-only mode
- preserve the rest of the deterministic trading stack unchanged

## Testing Strategy

The first version should be validated with:

1. **Schema tests**
- adapter output shape
- compiler input/output validation

2. **Replay tests**
- same inputs produce the same session playbook
- same playbook produces the same filtered decisions

3. **Shadow comparison**
- compare baseline vs sidecar-filtered decision streams

4. **Session scoring checks**
- ensure Hermes metrics correctly attribute blocked-good and blocked-bad outcomes

5. **Failure-path tests**
- missing sidecar output -> baseline fallback
- malformed sidecar output -> baseline fallback
- Hermes unavailable -> scoring disabled, no added trust

## Out of Scope for Version 1

- continuous intraday AI refresh
- automatic strategy-code mutation
- automatic parameter changes entering production
- direct AI execution logic
- replacing `C3PO`, `Sentinel`, or `Forge`
- broad multi-asset rollout

These can be revisited after the sidecar proves that it improves drawdown and selectivity without damaging expectancy.

## Recommended First Sub-Project

Build the following as a single focused project:

**A `TradingAgents` + Hermes scored policy sidecar for MNQ intraday paper trading, with premarket-first influence and fast promotion of proven restrictions.**

This is narrow enough to plan and implement, but ambitious enough to move the system toward the broader architecture.


## Freshness and Fallback Rules

To keep the first version operationally clear:
- the authoritative sidecar run happens once before the session opens
- the session playbook expires at the end of that trading session
- if the premarket sidecar output is missing, malformed, or older than the current session date, the compiler falls back to baseline rules
- no previous-session playbook may carry into a new session
- Hermes scoring may use prior-session history, but the compiler in version 1 reads only the current session sidecar output plus deterministic baseline rules

This keeps learning broad while keeping the active control path easy to debug.
