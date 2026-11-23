# Benchmark results

| Task | Hive (Opus 5.5 Queen + Haiku 5.5 bees) | Claude Sonnet 5.5 alone | Claude Opus 5.5 alone |
|---|---|---|---|
| dates (bug fix) | ✅ $0.22 · 1.2m | ✅ $0.06 · 0.3m | ✅ $0.20 · 0.5m |
| discounts (feature) | ✅ $0.14 · 0.8m | ✅ $0.05 · 0.2m | ✅ $0.15 · 0.5m |
| inventory (multi-file feature) | ✅ $0.14 · 1.1m | ✅ $0.06 · 0.3m | ✅ $0.24 · 0.9m |
| reports (feature + refactor) | ✅ $0.22 · 2.2m | ✅ $0.07 · 0.3m | ✅ $0.35 · 1.3m |
| ttlcache (implement from spec) | ✅ $0.17 · 1.4m | ✅ $0.07 · 0.3m | ✅ $0.36 · 1.5m |
| **Total** | **5/5 passed · $0.89** | **5/5 passed · $0.30** | **5/5 passed · $1.30** |
