# MIREAL SNS Agent

MIREAL株式会社 公式 Instagram / Facebook の完全無人運用エージェント。

## アーキテクチャ

```
GitHub Actions (cron)
        ↓
   Claude Code Agent
        ↓
[playbook/] ガイドライン読込
        ↓
[scripts/] 投稿・画像生成・世情チェック
        ↓
Meta Graph API
        ↓
IG / FB に投稿
```

## ディレクトリ構造

| パス | 役割 |
|---|---|
| `playbook/` | ブランドガイドライン・訴求柱・投稿フォーマット・カレンダー |
| `scripts/` | Meta API呼び出し・画像生成・安全チェックの実装 |
| `data/` | 投稿履歴・パフォーマンスログ |
| `.github/workflows/` | 接続テスト・テスト投稿・本番運用のCI定義 |
| `kill_switch.txt` | `STOP` と書いて push すれば次回以降の自動投稿が止まる |
| `CLAUDE.md` | Claude Codeへの運用指示書 |

## 必要な GitHub Secrets

| 名前 | 中身 |
|---|---|
| `META_APP_ID` | Metaアプリの App ID |
| `META_APP_SECRET` | Metaアプリの App Secret |
| `FB_PAGE_ID` | MIREAL.Official Facebookページの ID |
| `FB_PAGE_ACCESS_TOKEN` | 無期限 Page Access Token |
| `IG_BUSINESS_ACCOUNT_ID` | Instagram Business Account の ID |
| `ANTHROPIC_API_KEY` | Anthropic API キー |

## 運用フロー

1. **接続テスト**（投稿しない）: Actions → `01 - Connection Test` → Run workflow
2. **テスト投稿**（消せる投稿1本）: Actions → `02 - Test Post` → Run workflow
3. **本番運用**（毎日自動）: cron で `03 - Daily Post` が起動、Claude Code がエージェント駆動

## 緊急停止

`kill_switch.txt` の中身を `STOP` にして push すれば、次回起動時に自動的に停止します。
通常は `GO` または空のまま。
