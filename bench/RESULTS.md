# Benchmark results

| Task | Hive (Opus 5.5 + Haiku 5.5 bees) | Claude Sonnet 5.5 alone | Claude Opus 5.5 alone |
|---|---|---|---|
| dates (bug fix) | ✅ $0.80 · 2.9m | ✅ $0.08 · 0.3m | ✅ $0.22 · 0.7m |
| discounts (feature) | ✅ $0.60 · 2.0m | ✅ $0.06 · 0.2m | ✅ $0.25 · 0.8m |
| inventory (multi-file feature) | ✅ $0.87 · 3.3m | ✅ $0.07 · 0.3m | ✅ $0.28 · 1.0m |
| reports (feature + refactor) | ✅ $1.07 · 4.6m | ✅ $0.07 · 0.2m | ✅ $0.34 · 1.3m |
| ttlcache (implement from spec) | ✅ $1.10 · 5.3m | ✅ $0.12 · 0.3m | ✅ $0.43 · 1.4m |
| **Total** | **5/5 passed · $4.45** | **5/5 passed · $0.41** | **5/5 passed · $1.54** |
