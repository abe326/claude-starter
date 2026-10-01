# 設計書（模擬）

## 変えたもの → 一緒に直す正本

| 変えたもの | 一緒に直す正本 | 備考 |
|:--|:--|:--|
| `**/auth*`・`**/rbac*`・`**/permission*`・`**/session*` | `05-セキュリティ設計.md` §3 → `06-品質設計.md` §6 | |
| `**/migrations/**`・`**/schema*`・`**/models/**`・`prisma/**` | `02-architecture.md` §4 → `07-開発運用設計.md` §4 | |
| `**/deploy*`・`.github/workflows/**`・`Dockerfile*`・`docker-compose*`・`compose*.y*ml`・`infra/**` | `07-開発運用設計.md` §5 → `02-architecture.md` §5 | |
| `**/test*`・`tests/**`・`**/*.spec.*`・`**/*_test.*` | `06-品質設計.md` §7 | |
| `docs/案件/02_打合せ/**` | `01-overview.md` → `03-ステークホルダー.md` → `08-利用者運用設計.md` | |
| `docs/設計書/decisions/**` | `decisions/README.md` → `docs/プロジェクト概要.html` | |
| `docs/設計書/01-overview.md` | `docs/プロジェクト概要.html` → `docs/用語.md` | |
| `package.json`・`pyproject.toml` | `02-architecture.md` §2 → `docs/用語.md` | |
| 人向けの行（glob なし） | 01 §1 | 機械は読まない |
