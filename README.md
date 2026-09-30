# Samsung PRISM: Theme 05 — Interruptible Real-Time Agents

A production-grade, voice-native assistant architecture featuring **dual-process execution (Fast & Slow paths)**, **sub-millisecond interruption handling**, **session slot tracking with localized self-repairs**, and **multimodal grounding**.

---

## Quick Start

### 1. Requirements
- Python 3.10 – 3.12 (standard library only for core engine)
- Optional dependencies: `pip install -r requirements.txt`

### 2. Run Evaluation Dashboard
Execute the deterministic streaming virtual clock harness across all 9 canonical scenarios:
```bash
python main.py
```

### 3. Run Automated Tests
```bash
python -m unittest discover tests
```

---

## Repository Structure

```
samsung_prism/
├── agent/                         # Core Agent Implementation
│   ├── __init__.py
│   ├── core.py                    # Main async queue loop & event dispatcher
│   ├── coordination.py            # Turn epochs, prompt cancellations & grace filtering
│   ├── fast_path.py               # Sub-100ms reflex engine & floor manager
│   ├── slow_path.py               # Asynchronous planner, slot extractor & response grounder
│   ├── state.py                   # Session slot manager & snapshot generator
│   ├── tools.py                   # Schema registry & IdempotencyGuard
│   └── multimodal.py              # Audio disfluency resolver & vision frame grounder
├── harness/                       # Evaluation & Virtual Clock Environment
│   ├── __init__.py
│   ├── virtual_clock.py           # Deterministic virtual clock & timeline scheduler
│   ├── mock_env.py                # Mock tool environment with latency & fault injection
│   ├── test_scenarios.py          # 9 Canonical Scenarios (Text, Audio, Visual)
│   └── evaluator.py               # Official 4-pillar scoring engine & multipliers
├── schemas/                       # Protocol Specifications
│   ├── __init__.py
│   ├── events.py                  # InputEvent definitions & convenience constructors
│   └── actions.py                 # OutputAction & StateSnapshot definitions
├── tests/                         # Integration & Unit Tests
│   └── test_scenarios_runner.py   # Full test suite validating 100/100 scores
├── docs/                          # Architecture & Research Documentation
│   └── ARCHITECTURE_PROPOSAL.md   # Comprehensive technical report for Samsung PRISM
├── requirements.txt
└── main.py                        # Benchmark CLI entry point
```
