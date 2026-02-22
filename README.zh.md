[English](README.md) | [繁體中文](README.zh.md)

# git-worktrees

建立共享同一儲存庫的隔離工作空間，實現平行分支工作。

## 概述

Git worktrees 允許同時在多個分支上工作，無需切換分支。每個 worktree 是一個獨立的目錄，擁有自己的工作樹，但共享相同的 `.git` 資料。一個 worktree 中的變更不影響其他 worktree。

## 快速開始

```bash
# 檢查現有 worktree 目錄
ls -d .worktrees 2>/dev/null

# 建立新 worktree 並指定分支
git worktree add .worktrees/feature/auth -b feature/auth

# 列出所有 worktrees
git worktree list

# 合併後移除 worktree
git worktree remove .worktrees/feature/auth
```

## 功能特色

- **平行工作**：同時開發多個功能，無需切換分支
- **共享歷史**：所有 worktrees 共享相同的 `.git` 資料，保持歷史集中
- **自動設置**：偵測專案類型（Node.js、Python、Rust、Go）並執行適當的依賴安裝
- **乾淨基準**：在開始工作前驗證測試套件通過
- **安全清理**：妥善移除和修剪以保持儲存庫整潔

## 工作流程

1. 確定 worktree 目錄（`.worktrees/`、`worktrees/` 或 `~/worktrees/<project>/`）
2. 驗證目錄已被 git 忽略
3. 建立帶有新分支的 worktree
4. 自動執行專案設置（npm install、pip install、cargo build 等）
5. 執行測試驗證乾淨基準
6. 在隔離工作空間中開始開發

## 整合

- 與 **spec-kit** 配對，在規劃執行期間進行隔離實作
- 與 **team-tasks** 結合，在不同分支上進行多 agent 平行工作

## 授權

作為 Skills Collection 的一部分包含在 Claude Code 中。
