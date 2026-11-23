# Benchmark results

| Task | Hive (Opus 5.5 + Haiku 5.5 bees) | Claude Sonnet 5.5 alone | Claude Opus 5.5 alone |
|---|---|---|---|
| dates (bug fix) | ✅ $0.23 · 1.4m | ✅ $0.08 · 0.3m | ✅ $0.22 · 0.6m |
| discounts (feature) | ✅ $0.22 · 2.5m | ✅ $0.05 · 0.2m | ✅ $0.18 · 0.7m |
| inventory (multi-file feature) | ✅ $0.21 · 1.6m | ✅ $0.06 · 0.3m | ✅ $0.25 · 1.0m |
| reports (feature + refactor) | ✅ $0.17 · 1.8m | ✅ $0.06 · 0.2m | ✅ $0.30 · 1.3m |
| ttlcache (implement from spec) | ✅ $0.19 · 0.9m | ✅ $0.11 · 0.5m | ✅ $0.59 · 1.8m |
| **Total** | **5/5 passed · $1.02** | **5/5 passed · $0.35** | **5/5 passed · $1.53** |
