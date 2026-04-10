# Final AI Trading Architecture — Design Spec

**Date:** 2026-04-10
**Status:** Draft pending operator sign-off on `[confirm]` values
**Supersedes:** [docs/2026-04-10-refined-ai-trading-architecture.md](../../2026-04-10-refined-ai-trading-architecture.md)
**Primary instrument:** MNQ
**Primary timeframe:** 5-minute bars
**Repo umbrella name:** OpenClaw (not a component — the repository that houses the deterministic spine)

---

## Goal

Build a **durable, automated, risk-managed trading system that compounds without blowing up.** The system is explicitly not optimized for "most profit." It is optimized for sustainable, measurable edge on a liquid instrument, with structural protections against the failure modes that kill retail systematic traders: sizing errors, slippage erosion, data quality bugs, clock bugs, untested overlays, and AI layer drift.

### Target performance envelope

The following targets are the reference point for every tuning decision. If the system consistently under-performs this envelope over six months of live trading, the architecture is not producing its intended value and should be reviewed. Targets can be revised only with explicit sign-off and a recorded rationale.

- Annualized net return: `[confirm: 15–25%]` on equity, after all costs
- Max drawdown: ≤ `[confirm: 15%]` of equity from peak
- Sharpe (after costs, annualized): ≥ `[confirm: 1.0]`
- Operator time: ≤ `[confirm: 1 hour per week]` in steady state
- Uptime: ≥ `[confirm: 98%]` of scheduled trading hours

---

## 1. Principles (14 invariants)

These are the load-bearing rules the architecture preserves. Every component, every phase, every failure mode is derived from them. Violating any of these is not a tradeoff — it is a defect.

1. **Separation of powers.** Intelligence is separated from execution. The AI layer produces judgment. It cannot place, modify, or cancel orders. It cannot bypass any layer. This is a hard invariant, not a policy preference.

2. **Deterministic spine must stand alone.** C3PO + Sentinel + Forge + Watchtower must be profitable (or at least defensible) with zero AI involvement. If the baseline is not real, no overlay can save it. Phase 0 exists to prove this before any AI code is written.

3. **AI can only narrow, never expand.** Every AI-sourced constraint composes monotonically with a permissive base playbook. The Policy Compiler enforces this at the type level — it is structurally impossible for an AI input to unlock a setup, increase size, or widen a window. Relaxation to "narrow-expand within caps" is permitted only in Phase 4 Mode C, and only after the AI Scorer proves sustained reliability.

4. **Fail closed to Phase 1 baseline.** If the AI layer is unavailable, the compiler fails, the playbook is stale, or anything else goes wrong in the research/compile path, the system falls back to Phase 1 deterministic rules (Mode A baseline + macro event blocks). This is the same failure mode you exercise every Phase-1-only day, so it cannot rot.

5. **Watchtower has independent halt authority.** Watchtower can stop the system regardless of what C3PO, Sentinel, the Policy Compiler, or the AI layer think. Its halt path does not depend on the playbook, the compiler, or any LLM.

6. **Forge is the only component that touches the broker.** Order submission, bracket placement, fills, reconciliation — all of it. Every other component speaks to the broker through Forge or not at all.

7. **No LLM in the decision loop until Phase 3.** Phases 0, 1, and 2 are entirely deterministic. The first time an LLM influences the system is when the Policy Compiler consumes TradingAgents output in Phase 3, and even then the influence is narrowing-only and graded by the AI Scorer.

8. **Measurement before intelligence.** Every claim about edge, regime, slippage, or AI value must be backed by instrumented measurements against forward outcomes. Phase 0 is not optional. The AI Scorer is not optional.

9. **No unvalidated change reaches live.** Every new setup, parameter change, risk-rule change, or AI overlay must complete the full promotion ladder: backtest → shadow paper → constrained paper → tiny live → scaled live. There is no "obvious improvement" path that skips steps. This applies to AI-proposed changes, human-proposed changes, and emergency fixes equally.

10. **Sizing discipline is Sentinel's monopoly.** No component other than Sentinel sets position size. C3PO proposes; the Policy Compiler narrows; the AI layer can recommend caps — but only Sentinel translates an approved intent into a contract count. The sizing rules (fixed fractional per trade, max daily loss circuit breaker, revenge-trade lockout, max concurrent positions) are hard-coded in Sentinel and cannot be disabled or overridden. They can only be tightened further by narrowing, never relaxed.

11. **Every decision is replayable from recorded state.** If today's Market State Bus events are fed into a fresh system instance, it produces the same intents, the same approvals, and the same fills (modulo broker-side non-determinism). This is the foundation of debugging, backtesting, and trust. It forces the bus to be first-class.

12. **Paper and live trading share one code path.** Forge treats the paper broker and the live broker as interchangeable implementations of a single broker interface. C3PO, Sentinel, Watchtower, and the Policy Compiler have no knowledge of which broker is active. Switching from paper to live is a configuration change, not a code change.

13. **Clock discipline.** The system has a single authoritative time source. All components read time from it, not from local process clocks. All timestamps inside the Market State Bus are UTC. Display conversion to ET happens only at presentation time. Watchtower monitors clock drift against the authoritative source and halts the system if drift exceeds `[confirm: 250ms]`. Clock going backwards is a halt-worthy anomaly.

14. **Capital scaling is Sentinel's schedule.** Contract count is a rule owned by Sentinel, applied automatically from predeclared criteria. Operator authority over sizing is limited to scaling down (narrowing) or pausing the schedule. See Sentinel's scaling schedule in §2.

---

## 2. Component map

Seven components, with unambiguous authority boundaries. Components marked **(exists)** already live in the repo — this spec describes their role in the final architecture, not their current implementation.

### 2.1 Market State Bus *(new first-class layer, Phase 2)*

**Role.** Single, authoritative source of truth. Every market event, fill, position update, PnL snapshot, health reading, and calendar entry flows through the bus as a timestamped, append-only, replayable record.

**Consumes.** IB market data, broker fills from Forge, position updates, macro event calendar feeds, component health heartbeats, slippage measurements.

**Produces.** Normalized state objects, event streams, historical artifacts. Everything is timestamped UTC, immutable, and replayable.

**Authority.** None. The bus is infrastructure. It records, it serves, it does not decide.

**Dependencies.** None upstream (it is the root). Downstream: every other component reads from it.

**Failure mode.** If the bus is down, nothing can read truth. Watchtower halts the system. No fallback — every fallback is computed against the bus.

**Data quality gate (Phase 0).** The bus rejects ingest events that fail sanity checks before they land in the append log:

- Price in reasonable range vs last known close (rejects `close = 0` IB glitches)
- Bar timestamps monotonically advance within expected cadence (rejects out-of-order / duplicated bars)
- Volumes non-negative
- Bid ≤ ask on quotes
- Bar OHLC internally consistent (L ≤ O,C ≤ H)

Rejected events are not silently dropped — they are logged with a reason and Watchtower counts rejection rates per feed. A burst (> `[confirm: 5]` rejections in `[confirm: 60]` seconds) halts the system.

**Clock authority (Phase 0).** The bus owns the authoritative time source. All components requesting a timestamp ask the bus, not `datetime.now()`. The bus verifies its clock against NTP (`[confirm: time.nist.gov]`) on boot and hourly. Drift > `[confirm: 250ms]` is a halt condition. Bus records are UTC internally; timezone-naive timestamps are forbidden at ingest.

**Status.** Partially exists. `shared/state_store.py` and `shared/ledger.py` do parts of this job today but are not consolidated, not uniformly timestamped, and not replayable end-to-end. Phase 2 promotes these into a first-class named layer.

---

### 2.2 C3PO *(exists, Phase 0)*

**Role.** Deterministic alpha engine. Reads the bus, detects setups (ORB, trend pullback in Phase 0; VWAP, NEWS_DIRECTIONAL held back), scores them, and emits trade intents. No LLM involvement, ever.

**Consumes.** Market state from the bus, the active Session Playbook (Phase 2+), strategy configuration.

**Produces.** Trade intents: `{ setup_id, direction, stop, target, size_proposal, reason, bar_ts }`. The `reason` field names the specific rule that fired.

**Authority.** C3PO can **propose** intents. It cannot approve, cannot size beyond proposing a target, cannot touch the broker.

**Dependencies.** Market State Bus (read). Session Playbook (read, Phase 2+). No dependency on AI layer ever.

**Failure mode.** If C3PO is down, no new intents are generated. Open positions remain managed by Sentinel + Forge + Watchtower. Survivable — miss trades but don't mis-trade.

**Shadow mode (required from Phase 2).** C3PO supports running as a shadow instance: reads the bus, evaluates setups, emits intents into a shadow journal, but intents do not reach Sentinel and are never executed. This is infrastructure, not a Phase 3 feature — it must exist before Phase 3. In Phase 2, used to test hand-written Playbooks against live data without fills. In Phase 3, used to evaluate the AI layer: one C3PO runs with the AI-compiled Playbook (live), one runs with the Phase 1 base (shadow). The Scorer compares the two streams. Shadow and live differ only in routing (shadow intents → shadow journal; live intents → Sentinel), preserving the paper/live parity principle.

**Status.** Exists (`workspace-c3po/`). Phase 0 work: instrumentation — per-trade journaling, realized-vs-modeled slippage capture, expectancy tracking. Shadow mode is new infrastructure for Phase 2.

---

### 2.3 Policy Compiler *(new, Phase 3)*

**Role.** Translates AI research outputs into a machine-enforceable Session Playbook using **monotonic narrowing semantics**. Every AI input can only add constraints to a permissive base playbook. The compiler is the sole legal interface between the AI Research Mesh and the deterministic trading layers.

**Merge semantics (monotonic narrowing).** The compiler starts from a permissive base playbook matching Phase 1 defaults. Every AI input is expressed as a set of restrictions (blocked windows, disallowed setups, size caps, max entries). The final playbook is:

```
playbook = base ∩ restriction_1 ∩ restriction_2 ∩ ... ∩ restriction_n
```

Constraints compose monotonically — you are only ever ANDing restrictions together. Conflicts are impossible by construction. More pessimistic input = more restrictions. Missing input = no restrictions added (base rules apply). Every constraint in the final playbook is attributed to a specific source for audit.

**Refresh schedule.** Scheduled recompile points: 07:00, 09:25, 12:00, 14:00 ET (configurable). Each refresh is a full recompile — no partial updates. The most recent successfully compiled playbook is the active one.

**Consumes.** Structured JSON from TradingAgents-service, the Phase 1 deterministic event calendar, Hermes Journal (historical AI performance context), the base playbook.

**Produces.** A versioned, timestamped Session Playbook with expiration and source attribution for every constraint, written to the Market State Bus.

**Authority.** Can **publish playbooks**. Cannot trade, cannot size, cannot bypass Sentinel. Sole publisher of playbooks.

**Failure mode.** If the compiler fails, the previous playbook continues until expiration. On expiration without a successful recompile, the system falls back to the Phase 1 base playbook (Mode A + macro event blocks). Trading continues.

**Status.** New. Schema exists at `shared/schemas/daily_playbook.schema.json` and should be renamed to `session_playbook.schema.json` to reflect the scheduled-refresh cadence from Q5. Example at `openclaw_trader/config/daily_playbook.example.json`.

---

### 2.4 Sentinel *(exists, Phase 0)*

**Role.** Constitutional validator. Validates trade intents AND Session Playbook constraints before execution. Has final veto authority on every trade. Owns position sizing as a monopoly.

**Consumes.** Trade intents from C3PO, the active Session Playbook, Market State Bus (positions, PnL, drawdown, session state).

**Produces.** Approved orders (intent → sized → bracketed → signed off) or rejection records with reasons. Every rejection is journaled.

**Authority.** **Approve, reduce, defer, deny, freeze, halt.** Final veto. Hard-coded sizing rules cannot be disabled or overridden. AI can only narrow them further.

**Dependencies.** Market State Bus, Session Playbook. No dependency on the AI layer.

**Failure mode.** Sentinel down → no new approvals, no new trades. Watchtower ensures open positions stay managed by Forge with last-known brackets. Sentinel restart reconstructs state from the bus.

**Scaling schedule (Phase 0 hooks, activated Phase 4).** Sentinel owns a scaling schedule that controls contract count as a function of equity. Phase 0 exposes the hook but hard-codes contract count to 1 (paper). Schedule activates in Phase 4 live trading.

Default rule:
- Baseline: 1 contract
- Promotion: +1 contract per `[confirm: 20%]` net equity gain from high-water mark, capped by Kelly-fraction-computed limit at quarter-Kelly using realized expectancy and variance
- Demotion: -1 contract on drawdown of `[confirm: 8%]` from peak; schedule locked until equity recovers to within `[confirm: 2%]` of peak
- Operator override: can only narrow (reduce, pause); cannot widen

The schedule lives in Sentinel's config, version-controlled in git, loaded read-only at boot. Changes go through the promotion pipeline.

**Status.** Exists (`workspace-sentinel/sentinel.py`, `posture.py`). Phase 0 work: audit that sizing rules are adversarial (C3PO cannot talk Sentinel into larger size by resubmitting), audit posture machine halts on drawdown breach, audit revenge-trade lockout exists. Scaling schedule is new infrastructure.

---

### 2.5 Forge *(exists, Phase 0)*

**Role.** Execution kernel. Only component that touches the broker. Boring, deterministic, idempotent, auditable.

**Consumes.** Approved orders from Sentinel. Broker responses (fills, rejections, errors).

**Produces.** Broker submissions, bracket placements, position updates, fill records, reconciliation state. All fed back into the Market State Bus.

**Authority.** **Execute approved orders.** Cannot originate, cannot size, cannot skip Sentinel.

**Paper/live parity.** Forge treats `paper_broker.py` and `ib_broker.py` as interchangeable implementations of a single broker interface. Switching is a config change, not a code change. This structurally enforces principle 12.

**Failure mode.** Forge down → no execution. Watchtower flattens or freezes. Restart reconciles broker state against the bus.

**Status.** Exists (`workspace-forge/forge.py` and brokers). Phase 0 work: instrument `slippage_tracker.py` so every fill's realized-vs-modeled slippage lands in the bus.

---

### 2.6 Watchtower *(exists, promoted to cross-cutting halt authority, Phase 0)*

**Role.** Reliability monitor and independent halt authority. Observes the bus, the broker connection, and every other component's heartbeats. Can halt the system regardless of what any other component thinks.

**Consumes.** Market State Bus heartbeats, broker connection state, component health reports, data feed staleness metrics, bracket integrity checks, clock drift readings, data quality gate rejection rates.

**Produces.** Health reports into the bus, halt signals to Sentinel and Forge, emergency-flatten commands.

**Authority.** **Freeze** (no new entries), **halt** (stop cleanly), **emergency flatten** (close everything now). Independent — halt path does not depend on the playbook, the compiler, or any LLM.

**Dependencies.** Market State Bus (read). Nothing else. Specifically not dependent on Sentinel, C3PO, or Policy Compiler being alive to do its job.

**Failure mode.** If Watchtower itself fails, that is a severe condition. System halts on loss of Watchtower heartbeat — Watchtower is the safety layer, its absence is unsafe.

**Drawing note.** In architecture diagrams, Watchtower is drawn as a cross-cutting observer encircling the pipeline, not as a layer inside it.

**Status.** Exists (`workspace-watchtower/watchtower.py`). Phase 0 work: wire staleness detection, bracket reconciliation, clock drift monitoring, and data quality gate signals.

---

### 2.7 AI Research Mesh *(new, Phase 3+)*

A single logical component composed of sub-services that fail independently. The mesh is the only source of AI judgment in the system. It does not touch orders, positions, or the broker. It speaks to the rest of the system exclusively through the Policy Compiler.

#### 2.7a TradingAgents-service *(Phase 3)*

- **Role.** Produces structured regime labels, bias assessments, event-hazard ratings, and scenario analyses. MiroFish is folded in as "scenario mode" — a different prompt shape, not a different system.
- **Consumes.** Market State Bus (read-only), macro event calendar, Hermes Journal.
- **Produces.** Structured JSON outputs, schema-validated, consumed by the Policy Compiler. Never free-form text in the decision path.
- **Authority.** Produce research. Cannot trade, cannot publish playbooks directly, cannot bypass the compiler.
- **Failure mode.** Down → compiler receives no input from this source; falls back to base + other inputs.
- **External repo:** https://github.com/TauricResearch/TradingAgents — adapted as a service that produces compiler-compatible JSON.

#### 2.7b Hermes-service *(Phase 4 for full build; Phase 3 gets minimal Journal only)*

Conceptually three sub-modules sharing a repo but failing independently. **The three sub-modules are distinct failure domains.** If one is down, the others continue.

- **Scheduler.** Runs scheduled workflows (compile playbook, run TradingAgents, score yesterday's trades, compose briefing). Deterministic, cron-like, low-write.
- **Journal.** Append-only AI memory. Stores every AI judgment with a timestamp and forward-outcome fields to be filled by the Scorer. **Separate from `shared/ledger.py`.** The ledger is the authoritative trading decision record. The Journal is the authoritative AI judgment record. Cross-referenced by id, not duplicated.
- **Briefing.** Stateless report generator. Reads bus, ledger, Journal; writes daily/weekly reports. Killable and restartable with no state loss.
- **Authority.** None over trading.
- **Failure mode.** Scheduler down → no scheduled AI runs; manual still works; deterministic spine unaffected. Journal down → AI runs happen but lose memory; Scorer degrades. Briefing down → no reports; no trading impact.
- **External repo:** https://github.com/NousResearch/hermes-agent — adapted.

#### 2.7c AI Scorer *(Phase 3 — mandatory from day one of AI layer)*

- **Role.** Grades the AI layer over time. Every AI judgment stored in the Journal is scored against its forward outcome. Produces weekly AI performance reports.
- **Consumes.** Hermes Journal, Market State Bus (forward outcomes), ledger (actual trade results).
- **Produces.** Scoring records back into the Journal, weekly AI performance summary, and a **demotion signal**: if AI filters measurably hurt expectancy over `[confirm: 20]` trading days, the Scorer flips a flag that demotes the AI layer to research-only mode. The compiler stops consuming that AI source until the demotion is cleared by human review.
- **Fast-path demotion.** The Scorer also watches for AI flakiness *before* outcome evidence arrives: if a source produces > `[confirm: 10%]` schema-invalid outputs in a rolling `[confirm: 20]`-run window, it is fast-path demoted pending human review. This catches "AI is degraded now" without waiting weeks for expectancy data.
- **Authority.** Can **demote** AI sources. Cannot promote — promotion is a human decision after review.
- **Failure mode.** Scorer down → AI layer is flying blind; compiler treats AI layer as unproven (more conservative narrowing or base-only, configurable). Deliberate: no grading = no trust.

---

### 2.8 Authority summary

| Component | Propose | Size | Approve | Execute | Halt | Write Playbook |
|---|---|---|---|---|---|---|
| C3PO | ✓ | — | — | — | — | — |
| Sentinel | — | **✓ (monopoly)** | ✓ | — | ✓ | — |
| Forge | — | — | — | ✓ | — | — |
| Watchtower | — | — | — | — | **✓ (independent)** | — |
| Policy Compiler | — | — | — | — | — | **✓ (monopoly)** |
| AI Research Mesh | — | — | — | — | — | — |

---

## 3. Data flow

Four flows: baseline deterministic trade cycle, Phase 3 trade cycle with AI narrowing, playbook refresh lifecycle, and post-trade / scoring flow.

### 3.1 Baseline trade cycle (Phase 0/1, or any day the AI is down)

```
1. Market data tick ──► Market State Bus (append, with data quality gate)
2. C3PO reads bus ──► evaluates setups on the latest bar
                   ──► emits trade intent if rule fires
                       { setup_id, direction, stop, target,
                         size_proposal, reason, bar_ts }
3. Intent ──► Sentinel
     a. validate against Phase 1 deterministic playbook
        (session windows, macro event blocks, max entries)
     b. validate against portfolio state
        (drawdown, margin, posture, concurrent positions)
     c. compute final size via Sentinel's sizing monopoly
        (fixed fractional, daily loss cap, revenge lockout,
         scaling schedule)
     d. approve / reduce / deny / freeze
4. Approved order ──► Forge
     a. broker submission (paper or IB — same code path)
     b. bracket placement
     c. fill record ──► Market State Bus
5. Position updates + PnL ──► Market State Bus
6. Watchtower observes bus, heartbeats, broker health
     - freezes / halts / flattens if anything trips
```

Contains zero LLM calls and has no dependency on the AI Research Mesh. If every LLM in the world went down, this flow continues unchanged.

### 3.2 Phase 3 trade cycle with AI narrowing active

Same as 3.1 with one insertion: C3PO and Sentinel read the compiled Session Playbook instead of the static Phase 1 rules.

```
(Playbook lifecycle runs in parallel, described in 3.3)

1. Market data tick ──► Market State Bus
2. C3PO reads bus + active Session Playbook
     - Playbook restricts allowed setups, blocked windows,
       and max entries via monotonic narrowing
     - C3PO skips any setup the playbook disallows
     - emits intent only for allowed setups
3. Intent ──► Sentinel
     - validates against active Playbook + Phase 1 base
     - Sentinel computes size_S from its monopoly rules
       (fixed fractional, daily loss cap, scaling schedule,
        posture, etc.)
     - Playbook exposes size_P = base_units × playbook_cap_multiplier
     - final size = min(size_S, size_P)
       ^^^ monotonic narrowing: tighter always wins
4. Approved order ──► Forge ──► broker
5. Fills ──► Market State Bus
6. Watchtower unchanged
```

The AI layer is not called during the trade cycle. The trade cycle reads a precompiled artifact. This keeps the live path LLM-free.

### 3.3 Playbook refresh lifecycle

Runs on scheduled refresh points: 07:00, 09:25, 12:00, 14:00 ET (configurable). Each refresh is a full recompile.

```
Scheduled trigger (Hermes Scheduler, or cron fallback)
       │
       ▼
Compiler starts recompile
       │
       ├── Read base playbook (Phase 1 deterministic rules
       │   + macro event calendar for today)
       │
       ├── Read TradingAgents-service output (latest JSON)
       │   - If stale (> N minutes) or missing: skip input
       │
       ├── Read Hermes Journal (historical performance context)
       │   - If stale: skip input
       │
       ├── Apply monotonic narrowing:
       │     playbook = base ∩ restrictions_from_each_input
       │
       ├── Validate schema, check for impossible rules
       │   (e.g., all-setups-disallowed + min-trades > 0)
       │
       ├── If valid: publish as the new active playbook,
       │             write to Market State Bus with
       │             source attribution for every constraint
       │
       └── If invalid or empty: keep previous playbook if
                                 unexpired, otherwise fall
                                 back to the Phase 1 base
```

Every constraint in the final playbook is attributed to its source. Debugging "why didn't we trade the 10:00 ORB?" answers back with "Playbook blocked ORB from 09:30–10:15; source = TradingAgents 09:25 run, reason = 'regime unclear'."

### 3.4 Post-trade and scoring flow

```
Fill arrives at Forge
      │
      ▼
Fill record ──► Market State Bus
      │
      ├── realized vs modeled slippage computed
      │   (written to bus + slippage tracker)
      │
      ├── position + PnL updated
      │
      └── trade journal entry with full context:
          - intent source (which C3PO rule fired)
          - playbook constraints active at intent time
          - Sentinel approval trail
          - execution details
          - attribution chain (base / event / TA / Journal)

End-of-day (Scheduler trigger):
      │
      ├── AI Scorer reads today's Journal entries
      │   - each AI judgment scored vs forward outcome
      │   - "regime was bullish" vs "market actually did X"
      │   - "blocked ORB at 09:30" vs "ORB would have paid Y"
      │
      ├── Scorer updates running statistics:
      │   - blocked-good-trade rate
      │   - blocked-bad-trade rate
      │   - over-tightening bias
      │   - regime-call accuracy
      │
      ├── Briefing service composes daily report
      │
      └── If AI filter is hurting expectancy over [confirm: 20] days:
             Scorer flips demotion flag ──► Compiler ignores
             that source until human review
```

There is no "AI grades itself" loop. The Scorer compares AI judgments to ground truth from the ledger and the bus. Scorer is deterministic code, not prompts.

---

## 4. Phase map and exit criteria

Phases are gated by numerical exit criteria, measured over specified windows, with evidence in the ledger. Soft "it feels ready" transitions are forbidden.

### Phase 0 — Baseline Proof *(exists, needs instrumentation)*

Goal: prove the deterministic baseline is real.

**In scope:**
- C3PO producing ORB + trend pullback intents on MNQ 5m
- Sentinel enforcing hard risk limits and sizing monopoly
- Forge executing paper fills with realized-vs-modeled slippage capture
- Watchtower running reconciliation, clock drift monitoring, data quality gate
- New instrumentation: expectancy tracker, per-setup slippage, drawdown distribution, trade journal with full metadata

**Exit criteria (all must pass, same sample):**
- Trade count: ≥ 100 paper trades across ≥ `[confirm: 30]` trading days
- Net expectancy: ≥ `[confirm: 0.15R]` per trade after realized slippage (not modeled)
- Expectancy confidence: lower bound of 95% CI on net expectancy > 0
- Max drawdown: < `[confirm: 15R]` over the sample
- Worst single trade: no single trade > `[confirm: 3R]` loss
- Slippage sanity: realized slippage within `[confirm: 1.5×]` modeled on the 90th percentile of trades
- Data quality: < `[confirm: 0.5%]` of bus events rejected by the data quality gate

**Phase 0 failure response.** If exit criteria fail, the project does not proceed to Phase 1. Based on which criterion failed:

- **Net expectancy below target, slippage matches model:** the setup family is not edge-positive on MNQ 5m under current rules. Demote setup to research-only. Options: different parameters (via promotion pipeline, no hot-patches), different setup family, or reconsider whether MNQ 5m is the right instrument.
- **Net expectancy below target, realized slippage > modeled:** slippage model is wrong, not the setup. Fix the slippage model using Phase 0 data, re-measure. Do not change the setup until slippage is honest.
- **Expectancy acceptable but drawdown too deep:** stop logic or position sizing is too loose. Tighten stops or reduce base size in Sentinel, re-run.
- **Single-trade loss exceeds 3R:** bracket logic is broken. Halt until the bracket failure mode is reproduced and fixed. This is a correctness bug, not a tuning issue.
- **Data quality gate rejecting too many events:** fix the ingest layer or the feed, not the strategy.
- **Three or more criteria fail simultaneously and root causes aren't clear:** the project is not ready for systematic automation on this instrument. Pause, reconsider scope, possibly return to manual paper trading to rebuild understanding.

### Phase 1 — Deterministic Event Safety *(runs in parallel with Phase 0)*

Goal: handle macro events deterministically before any AI shows up.

**In scope:**
- Macro event calendar ingestion (econoday / investpy / equivalent)
- Event severity tagging (tier 1/2/3)
- Auto-blocks around tier 1 events, enforced by Sentinel
- Auto-size-reduction on event days
- Pure deterministic rules. No LLM.

**Exit criteria (all must pass over ≥ `[confirm: 10]` tier-1 macro event days):**
- Left-tail improvement: 5th percentile daily PnL improves by ≥ `[confirm: 25%]` in absolute terms vs Phase 0 baseline
- Event-day expectancy does not degrade on non-event days by more than `[confirm: 10%]` (catches over-blocking)
- Block accuracy: < `[confirm: 5%]` of blocks are "good trades you missed" per post-hoc analysis
- Clock discipline: no unjustified clock-drift halts (verified by replay)
- Calendar reliability: zero missed tier-1 events during the sample

### Phase 2 — Market State Bus + Playbook Ingestion

Goal: build the enforcement spine for a Playbook before any AI exists to produce one.

**In scope:**
- Promote Market State Bus to a first-class layer (consolidate `state_store.py`, `ledger.py`, health state, event calendar)
- Rename `daily_playbook.schema.json` → `session_playbook.schema.json`
- Wire C3PO and Sentinel to read the Session Playbook
- Fallback: no playbook → Phase 1 deterministic rules
- Stub Playbook source: hand-written JSON, operator-edited. No AI yet.
- C3PO shadow mode infrastructure

**Exit criteria (all must pass):**
- Hand-written Playbook honored: ≥ `[confirm: 5]` consecutive trading days with a hand-written Playbook active; every constraint correctly applied by C3PO and Sentinel (verified by replay)
- Attribution chain correct: every rejection record in the ledger names the specific Playbook constraint that caused it, plus the source
- Fallback tested: ≥ 1 forced failure of the Playbook reader, automatic fall-back to Phase 1 base, no trade disruption, Watchtower did not halt
- Shadow mode working: C3PO shadow instance runs in parallel with live for ≥ `[confirm: 5]` trading days, zero divergence from live on identical inputs

### Phase 3 — Policy Compiler + TradingAgents + AI Scorer

Goal: replace the hand-written Playbook with one compiled from a single AI source.

**In scope:**
- Policy Compiler with monotonic narrowing (§2.3)
- TradingAgents-service as the only AI input initially
- Minimal Hermes Journal (write + read)
- AI Scorer from day one (Scorer is mandatory, not optional)
- Shadow evaluation: AI-filtered path runs live; baseline path runs in shadow; Scorer compares

**Exit criteria (all must pass over ≥ `[confirm: 30]` trading days in shadow mode):**
- Drawdown improvement: AI-filtered path shows lower max drawdown than shadow baseline at 95% CI
- Expectancy preservation: AI-filtered path net expectancy is within `[confirm: 10%]` of shadow baseline (either direction)
- Scorer quality: blocked-bad-trade rate > blocked-good-trade rate by ≥ `[confirm: 1.5×]`
- Compiler uptime: ≥ `[confirm: 95%]` of scheduled recompile points produced a valid Playbook
- Fail-closed exercised: ≥ 1 successful compiler failure with automatic fallback to Phase 1 base, no trade disruption
- No demotion events: AI Scorer did not flip any demotion flags during the window
- Attribution correctness: every AI-sourced constraint in every compiled Playbook traces to a specific TradingAgents output in the Journal

### Phase 4 — Full AI Research Mesh *(steady state)*

Goal: the full architecture, running as intended.

**In scope:**
- Full Hermes-service (Scheduler + Journal + Briefing)
- Scenario mode as a second TradingAgents entry point
- Activation of Sentinel's capital scaling schedule for live trading
- Operating Mode C becomes *possible* but only with sustained Scorer reliability
- Post-close reports, weekly reviews, promotion pipeline for AI-proposed improvements

**Steady-state criteria (ongoing, not an exit):**
- Monthly review of AI Scorer statistics
- Quarterly review of the scaling schedule
- Weekly drift check (Phase 0 baseline metrics still true?)
- Three consecutive weeks of Phase 0 baseline metrics below exit criteria triggers mandatory review; possible demotion of AI layer to research-only

---

## 5. Failure modes, testing, disaster recovery, and out-of-scope

### 5.1 Failure modes

#### Data failures

| Failure | Detection | Automatic response | Operator action |
|---|---|---|---|
| Stale market data | Watchtower bus heartbeat | Freeze new entries; existing positions continue | Investigate feed, acknowledge, unfreeze |
| Bad bar values (OHLC inconsistent, zero prices) | Bus data quality gate | Event rejected; Watchtower counts | Investigate if > 5 rejections in 60s |
| Out-of-order bars | Bus monotonicity check | Rejected; logged | Investigate feed quality |
| Missing bars across expected cadence | Watchtower cadence check | Freeze new entries after `[confirm: 3]` missing | Reconnect, verify continuity |
| Clock drift > 250ms | Bus clock monitor | Halt | Resync NTP, verify, restart |
| Clock going backwards | Bus clock monitor | Halt immediately | Investigate process; possibly restart host |

#### Component failures

| Failure | Detection | Automatic response | Operator action |
|---|---|---|---|
| C3PO down | Watchtower heartbeat timeout | No new intents; existing positions continue | Restart; bus replay brings it back in sync |
| Sentinel down | Heartbeat timeout | Forge refuses new orders; Watchtower freezes | Restart; verify posture from bus |
| Forge down | Heartbeat timeout or broker connection loss | Sentinel stops approving; Watchtower assesses exposure | Restart; reconcile broker vs bus |
| Watchtower down | Meta-watchdog / process supervisor | System halts — safety layer absent is unsafe | Investigate; restart; verify all heartbeats green |
| Market State Bus down | Every component detects missing reads | All components freeze | Hard problem; triggers full DR flow |
| Policy Compiler down | Scheduler notices missed compile | Previous playbook active until expiration; then Phase 1 base | Investigate; restart; next refresh runs |
| TradingAgents-service down | Compiler notices missing input | Playbook from remaining inputs; if all AI down → base only | No immediate action; investigate off-hours |
| Hermes Journal down | Scorer degrades; compiler loses context | Compiler still runs; Scorer pauses grading | Restart; lost scoring window is permanent gap |
| AI Scorer down | Compiler checks Scorer freshness | Compiler treats AI layer as unproven (more conservative or base-only) | Restart; no backfill — scoring resumes forward |

#### Broker failures

| Failure | Detection | Automatic response | Operator action |
|---|---|---|---|
| IB connection loss | Forge broker ping | Forge marks broker offline; Watchtower freezes; existing brackets stay at IB | Reconnect; reconcile positions and open orders |
| Order rejected by broker | Forge fill callback | Intent journaled with rejection; Sentinel notified | Investigate if recurring |
| Bracket not placed after entry fill | Forge post-fill verification | Emergency-flatten orphaned position; halt | Investigate; fix bracket logic before resuming |
| Partial fill weirdness | Forge reconciliation | Sentinel sees actual exposure; Watchtower verifies | Acknowledge; auto-handled if reconciliation succeeds |
| Duplicate fill / broker replay | Forge idempotency (hashed order IDs) | Duplicate rejected | Investigate if frequent |

#### AI layer failures

| Failure | Detection | Automatic response | Operator action |
|---|---|---|---|
| TradingAgents schema-invalid output | Compiler schema validator | Input rejected; compile with remaining inputs | Investigate; recurring triggers fast-path demotion |
| TradingAgents flaky (> 10% schema-invalid in rolling 20-run window) | Scorer fast-path check | TA source fast-path demoted until human review | Review TA health; revert or update prompts; clear flag |
| TradingAgents hallucinates a setup name | Compiler validates against known setups | Field rejected; partial compile with valid fields | Investigate; prompt update |
| Scorer shows AI adding no value after `[confirm: 20]` days | Standard grading loop | Demotion flag flipped; compiler stops that source | Human review: accept demotion (research-only) or identify cause and re-promote |
| Compiler produces contradictory playbook | Compiler self-validation | Compile fails; previous playbook continues | Investigate contradictions; usually an input problem |
| AI layer latency spike | Compiler timeout | Compile aborts; previous playbook continues | Investigate; tune timeout or diagnose upstream |

#### Operator failures

| Failure | Detection | Automatic response | Operator action |
|---|---|---|---|
| Config file with uncommitted changes on live run | Watchtower git check on boot | Refuses to start | Commit or revert; restart |
| Hand-written Playbook with impossible rules | Compiler validation | Falls back to previous or base | Fix and re-publish |
| Operator tries to increase size via override | Sentinel narrowing-only invariant | Change refused; logged | Use scaling schedule |
| Wrong environment (paper config at IB) | Bus environment fingerprint check on boot | Refuses to start on mismatch | Verify env, correct config |

#### Catastrophic failures

| Failure | Detection | Automatic response | Operator action |
|---|---|---|---|
| Process crash | OS supervisor + Watchtower heartbeat gap | Supervisor restarts; Watchtower re-verifies from bus + broker before resuming | Verify recovery; investigate root cause |
| Host power loss | Loss of all heartbeats | On reboot: recovery mode — bus replay, broker reconciliation, position verification before new trading | Manual verification of broker positions vs bus |
| Network partition (broker ok, feed lost) | Forge OK; Watchtower feed stale | Freeze new entries; monitor existing positions via broker directly | Investigate; restore feed |
| Network partition (feed ok, broker lost) | Forge broker ping fails | Freeze; no new orders | Investigate; verify broker-side state on reconnect |
| Disk full (bus cannot append) | Bus write failure | Halt — cannot trade against unrecorded state | Free space; verify bus integrity |
| Bus corruption | Integrity check (hash chain) on boot | Refuse to start | Restore from backup; manual reconciliation |

#### Silent failures

These don't trigger automatic responses in real time — they show up in aggregate via the Scorer, weekly review, and Phase 0 drift check.

| Failure | Detection | Response |
|---|---|---|
| Realized slippage drifts worse over time | Weekly slippage review vs Phase 0 baseline | Mandatory review; possibly widen model and re-run Phase 0 check |
| Baseline edge erodes (expectancy decays) | Weekly Phase 0 metrics drift check | 3 consecutive weeks below: demote baseline, pause live, investigate regime / setup decay |
| AI layer quietly stops being right but not wrong enough to demote | Monthly Scorer review | Human judgment: continue, demote, or re-prompt |
| Clock drift within tolerance but consistently growing | Bus clock trend detection | Investigate host; resync; possibly migrate |
| Bracket integrity holds but realized stops get worse | Fill analysis vs modeled stops | Investigate slippage model or order routing |

### 5.2 Testing strategy

Five layers:

1. **Unit tests per component.** Components communicate through well-defined interfaces (typed bus events, typed intents, typed playbooks) so unit testing in isolation is straightforward.
2. **Integration tests against a scripted bus.** Canned bus event sequences driven through the full pipeline; assertions on resulting state. These are the contract between components.
3. **Replay tests.** Recorded days' bus events replayed through a fresh system instance; asserts that resulting intents, approvals, and fills match recorded. Any divergence is non-determinism or regression.
4. **Shadow mode in production.** Phase 2+. Shadow C3PO runs in parallel with live; any divergence on identical inputs is a bug. Also the Phase 3 evaluation mechanism.
5. **Chaos tests.** Deliberately fail components during paper trading; verify recovery. Kill Sentinel mid-session; verify Forge refuses new orders; restart; verify state rebuild from bus; verify clean resume. Run before promoting any phase to live.

**Promotion pipeline as ongoing test:** backtest → shadow paper → constrained paper → tiny live → scaled live is a staged acceptance system. No hot-patches, no skipping.

**Config versioning requirement:** all configs in git. Watchtower runs `git status` on the config directory at boot and refuses to start if anything is uncommitted on a live run. Catches the "quick test change that never got reverted" failure mode — the single most common retail blow-up cause.

**Audit trail requirement:** an integration test asserts that every trade ledger entry has a valid cross-reference to the Journal entries that contributed to its Playbook constraints (Phase 3+), or records "no AI input" (Phases 0–2). Catches silent breakage of the audit trail.

### 5.3 Disaster recovery

**Warm restart (component-level).** Single component crashes. Process supervisor restarts. On boot, component reads the bus to reconstruct state. Watchtower verifies health before re-enabling trading. No manual intervention. Existing entry points (`run_cycle.py` etc.) support this.

**Cold restart (host-level).** Host rebooted. Recovery sequence:
1. Bus integrity check (hash chain). Refuse to proceed on corruption.
2. Broker reconciliation: query broker for positions, open orders, brackets; compare vs bus last-known; mismatch triggers manual review.
3. Clock resync against NTP. Refuse to proceed on drift > 250ms.
4. Start components in dependency order: bus → Watchtower → Sentinel → Forge → C3PO → (Phase 3+) compiler and AI mesh.
5. Paper: auto-resume after verification. Live: operator confirmation required.

**Emergency flatten.** Operator-initiated or Watchtower-triggered. All positions closed at market; open orders cancelled; system enters halted state. Existing `run_emergency_flatten.py` implements this. After flatten, no auto-resume — operator must explicitly clear the halt after investigation.

### 5.4 Out of scope

- **Not a discretionary trading system.** No operator-initiated trades. No "feelings about today."
- **Not a multi-asset system at launch.** MNQ only in Phase 0–3.
- **Not a multi-timeframe system at launch.** 5m only.
- **Not a market-making system.** Directional entries with fixed brackets.
- **Not a latency-sensitive system.** 5m candles. Do not design for microseconds.
- **Not a self-modifying system.** AI layer cannot change its own rules, prompts, or schema. All AI changes are code changes going through git and the promotion pipeline.
- **Not a research environment.** Research happens in notebooks outside the live pipeline.
- **Not a backtesting framework.** Uses existing tools (`backtest/`). Architecture focuses on live paper and live; backtesting is input, not component.
- **Not a tax / accounting / compliance system.**
- **Not a social / signal / copy-trading platform.**
- **Not an operator UI project.** Minimal console (status, halt, unhalt) in scope. Rich dashboard separate.
- **Not "an AI trading system."** AI is a narrowing-only risk overlay. The deterministic spine is the engine.

---

## 6. Relationship to prior architecture doc

This spec supersedes [`docs/2026-04-10-refined-ai-trading-architecture.md`](../../2026-04-10-refined-ai-trading-architecture.md) (the "locked-in target architecture" of the same date). Key differences:

- **Component names resolved.** "OpenClaw" is now explicitly the repo/umbrella name, not a component. C3PO, Sentinel, Forge, and Watchtower are the real deterministic components. The prior doc implied this but was not explicit.
- **Watchtower promoted to a named first-class component.** The prior doc omitted it.
- **MiroFish folded into TradingAgents.** The prior doc kept MiroFish as a separate system without justifying what it does that TradingAgents cannot.
- **Hermes split into Scheduler / Journal / Briefing as independent failure domains.** The prior doc bundled all three.
- **Market State Bus promoted to a first-class named layer with a data quality gate and clock authority.** The prior doc mentioned it but did not specify ingest sanity checks or clock discipline.
- **AI Scorer added as a mandatory component from the first day of the AI layer.** The prior doc had no AI grading loop.
- **Policy Compiler merge semantics specified as monotonic narrowing.** The prior doc left this open.
- **"Daily Playbook" renamed to "Session Playbook" with scheduled intraday refresh points.** The prior doc used "Daily" but the examples were intraday, which was incoherent.
- **Phase exit criteria made numerical.** The prior doc used conversational exit language.
- **Phase 0 failure response decision tree added.**
- **Shadow mode added as Phase 2 infrastructure** (prior doc had no shadow story).
- **Sentinel sizing monopoly, capital scaling schedule, and paper/live code-path parity added as explicit invariants.**

---

## 7. Items requiring operator sign-off before implementation

The following `[confirm]` values appear throughout this spec as placeholders. All must be reviewed and confirmed by the operator before implementation begins. Values listed here are defaults chosen by analysis but not yet ratified.

### Goal / target envelope
- Annualized net return target: `15–25%`
- Max drawdown target: `≤ 15%`
- Sharpe target: `≥ 1.0`
- Operator time target: `≤ 1 hour per week`
- Uptime target: `≥ 98%`

### Clock and data quality thresholds
- Clock drift halt threshold: `250ms`
- NTP source: `time.nist.gov`
- Data quality gate burst threshold: `> 5 rejections in 60 seconds`

### Capital scaling schedule
- Promotion step: `+1 contract per 20% net equity gain from high-water mark`
- Demotion step: `-1 contract on 8% drawdown from peak`
- Schedule unlock: `equity recovers to within 2% of peak`
- Kelly cap: `quarter-Kelly from realized expectancy and variance`

### Phase 0 exit
- Trade count: `≥ 100 trades`
- Window: `≥ 30 trading days`
- Net expectancy: `≥ 0.15R after realized slippage`
- Max drawdown: `< 15R`
- Worst single trade: `≤ 3R loss`
- Slippage sanity: `realized ≤ 1.5× modeled at 90th percentile`
- Data quality rejection rate: `< 0.5%`

### Phase 1 exit
- Window: `≥ 10 tier-1 macro event days`
- 5th percentile daily PnL improvement: `≥ 25%`
- Non-event-day expectancy degradation: `≤ 10%`
- Block accuracy: `< 5% false blocks`

### Phase 2 exit
- Hand-written Playbook: `≥ 5 consecutive days`
- Shadow mode: `≥ 5 days with zero divergence`

### Phase 3 exit
- Window: `≥ 30 trading days shadow`
- Expectancy preservation: `within 10% of baseline`
- Scorer quality: `blocked-bad > blocked-good × 1.5`
- Compiler uptime: `≥ 95% of scheduled refreshes valid`

### AI flakiness fast-path demotion
- Schema-invalid rate: `> 10% in rolling 20-run window`

### Scorer standard demotion
- Hurting-expectancy window: `20 trading days`

### Data cadence
- Missing bars before freeze: `3 consecutive missing bars`

---

## 8. What this spec does not do

This spec defines the *target architecture* and the *phase discipline* for reaching it. It does not:

- Produce an implementation plan. That is the next step (writing-plans skill).
- Mandate specific libraries, frameworks, or versions beyond what already exists in the repo.
- Specify per-component file layouts or module names. Those are implementation decisions.
- Guarantee profitability. The architecture protects edge; it does not create edge. Phase 0 determines whether edge exists.
- Commit to building Phases 3 or 4. Phase discipline means later phases are earned by earlier phases' exit criteria. If Phase 0 fails, none of the AI layer is ever built, and that is a correct outcome.
