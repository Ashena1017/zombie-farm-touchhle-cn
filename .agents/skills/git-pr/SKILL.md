---
name: git-pr
description: 用脚本从已提交分支安全推送并创建 GitHub/Gitee Pull Request；用户要求开 PR 或仓库贡献流程要求 PR 时使用。单纯 commit 或直接推送不使用此 skill。
whenToUse: 用户明确要求创建 PR，或目标仓库的贡献说明要求 PR；也用于排查 PR 脚本的凭据、推送权限和重复 PR 问题。
---

# 用 `git-pr.mjs` 创建 PR（Gitee / GitHub 通用）

本 skill 的执行脚本 `git-pr.mjs` 与本文件同目录。脚本使用 Node.js 18+ 内置模块，零第三方依赖。

## 一、先确认工作流与提交

先读仓库贡献说明和当前任务要求，确认目标确实是 PR。用户明确要求直接推送，或仓库说明规定维护者直接推送时，不要用本脚本；它会创建 PR，不能当作通用 `git push` 包装器。

`git-pr.mjs` 只推送**已有 commit**并创建 PR，不会 `git add`、`git commit` 或包含未提交改动。先检查工作区与目标提交范围，完成需要的 commit 后再运行。若需要创建 commit，身份缺失时只在目标仓库设置 `user.name` / `user.email`，不要用 `--global`。

## 二、预演与执行

```powershell
# 1) 预演：检查身份、权限、目标分支和当前分支，不推送或创建 PR
$gitPr = Join-Path (Get-Location) '.agents\skills\git-pr\git-pr.mjs'
node $gitPr --repo <仓库路径> --branch <分支> --title "<标题>"

# 2) 真提交：推 fork + 开 PR + 回读校验（幂等，可重复运行）
node $gitPr --repo <仓库路径> --branch <分支> `
  --title "feat(scope): 说明" --body-file <PR描述.md> --apply
```

| 参数 | 说明 |
|---|---|
| `--repo` | 本地仓库路径（必填） |
| `--branch` | 分支名，须与当前 HEAD 一致（必填） |
| `--title` | PR 标题（必填） |
| `--body-file` | PR 正文 md（可选，按 UTF-8 读） |
| `--upstream` | 上游 `owner/repo`，默认从 origin 推导 |
| `--base` | 目标分支，默认使用上游仓库的默认分支 |
| `--apply` | 真正执行；不加则只预演 |
| `--dry-run` | 显式预演（与不加 `--apply` 等价） |
| `--help` | 打印脚本自带帮助 |

脚本会从上游仓库读取默认分支，并在推送前验证目标分支存在；特殊工作流可用 `--base` 覆盖。预演仍会读取平台 API 和 Git 凭据，但不添加 remote、不推送、不创建 PR。

若 GitHub CLI 报 base 分支不存在，先确认项目真实目标分支；不要假设所有 GitHub 仓库都用 `main` 或 `master`：

```powershell
git -C <仓库> remote show origin | Select-String 'HEAD branch'
```

⚠️ **脚本只认上表参数，未知参数直接报错**——这是有意的：避免「以为在预演、
其实已经推送并开了 PR」。别自己发明 `--force` 之类的参数。

脚本会自动：识别平台（从 origin URL 判断 Gitee/GitHub）→ 读取令牌（不打印）→
校验令牌身份 → 探测上游推送权限 → 按 remote 的 push URL 选择目标仓库 → 推送 → 开 PR →
按实际推送仓库确定 PR head、检查重复 PR 并回读文件清单。指定 `--body-file` 但文件不存在时会立即报错。
API 请求最长等待 30 秒；超时会报出对应请求路径。

## 三、权限与重复 PR

### 1. 403 的根因通常是「推错了仓库」，不是令牌无效

上游仓库一般 `permission.push = false`，直接推 `origin` 必然 **403**。
必须推**自己的 fork**。脚本先探测上游权限，不可推时自动改用 `fork`；
若 fork 也没有权限，它会**明确报错**，而不是让你对着 403 猜。

### 2. 令牌只进变量、绝不打印

`git credential fill` 会**输出明文令牌**。脚本只打印用户名和长度。
自己写脚本时同样不要把令牌 echo 出来（会留进会话记录）。

⚠️ **PowerShell 里取令牌有个静默陷阱**：`git credential fill` 返回的是
**字符串数组**（一行一个元素），不是单个字符串。直接对它做正则替换只会逐元素
替换；更糟的是 `$x.Length` 此时是**元素个数**而不是字符数 —— 实测一个 40 字符的
令牌会显示成 `4`，看起来「取到了值」，实际后面全是坏的。必须先 join 再解析：

```powershell
$raw = (("protocol=https`nhost=github.com`n`n" | git credential fill 2>$null) -join "`n")
$tok = (($raw -split "`n") | Where-Object { $_ -like 'password=*' }) -replace '^password=', ''
if (-not $tok) { throw '未取到令牌' }   # 别把空值带进后续请求
```

### 3. 中文标题/正文必须按 UTF-8 字节发送

`ConvertTo-Json` 的字符串直接当 HTTP body 会按 **Latin-1** 编码 → 中文乱码。
要 `[Text.Encoding]::UTF8.GetBytes($json)`；Node 里用 `Buffer.from(payload, 'utf8')`。

### 4. 幂等判重必须用对字段

重复提同一 PR 时，Gitee 回 HTTP **400**（`已存在相同源分支、目标分支的 Pull
Request`），GitHub 回 **422**。这是「已经提过了」，**不是失败**。

⚠️ 判重**不能**用 `head.label`：Gitee 的 `head.label` **只有分支名、不含 owner**，
拿它比对 `owner:branch` 会**永不命中**，于是重复运行仍去 POST → 400。
正确判据是 `head.ref` + `head.repo.full_name` + `base.ref`（两家平台都可靠）。

### 5. 不要交互

必须设 `GIT_TERMINAL_PROMPT=0` 与 `GCM_INTERACTIVE=never`，
否则会卡在凭据提示上（在自动化会话里等于挂死）。
脚本还带 20 秒超时，凭据助手缺失时直接报错而非挂住。

## 四、凭据未配置时

脚本通过 Git credential helper 读取凭据，并禁用交互提示。可先检查 helper 是否配置：

```powershell
git config --show-origin --get-all credential.helper
```

如果没有可用凭据，先按所用 Git credential helper 的正常登录流程完成一次 HTTPS 操作，
再重跑预演。不要把令牌粘贴到会话、命令行或文件中；`git credential fill` 会输出明文凭据，
检查时不要回显它的结果。

## 五、网络故障排查

先区分 DNS/TLS 连接失败与 HTTP 403/权限拒绝。若 `api.github.com` 可访问但 Git 报 `Could not resolve host: github.com`，不要改 remote、关闭 TLS 验证或把令牌塞进 URL。检查当前 Git 的 SSL backend；如果它指向此安装不支持的 backend，可临时用 Windows Schannel，并通过 `http.curloptResolve` 给 GitHub HTTPS 主机指定一个当前可达且证书有效的 IP：

```powershell
git -c http.sslBackend=schannel `
  -c http.curloptResolve=github.com:443:<已验证的 GitHub HTTPS IP> `
  ls-remote origin HEAD
```

先让 `ls-remote` 成功，再对同一命令加对应 `git -c` 参数执行 push；或通过 `GIT_CONFIG_COUNT` 环境项仅对脚本子进程传入这两个临时配置。不要写入 `--global` 配置，也不要长期复用未经重新验证的 IP。DNS/SSL workaround 只解决 Git 传输连接，不会改变仓库权限。

## 六、推之前值得做的检查

- **基线**：分支是否基于**当前上游默认分支的 HEAD**？先用 `git fetch` 确认
  （Gitee 多为 `master`，GitHub 多为 `main`）。
  基线过旧会把上游较新的提交一起带进 PR，看起来像「回退」别人的工作。
- **目标 remote**：脚本可能推有权限的上游，也可能推个人 fork；预演输出的目标仓库应与本次意图一致。不要只凭 remote 名称 `origin` / `fork` 判断目的地。
- **改动范围**：`git diff --stat <base>..HEAD` 是否只有预期文件。

## 七、安全红线

- **绝不打印**凭据文件内容、令牌、AK/SK。
- 令牌不写入任何文件、不 `echo`、不贴进会话。
- 读取系统凭据只在必要时执行，且输出中不得回显凭据内容。

GitHub REST 请求应带 `User-Agent`；脚本已统一添加，避免受限网络策略返回误导性的 403。
