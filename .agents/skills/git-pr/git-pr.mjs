#!/usr/bin/env node
/**
 * git-pr.mjs —— 一键把本地分支提交成 PR（推 fork + 开 PR + 回读校验）。
 *
 * 支持 **Gitee** 与 **GitHub**：从 origin 的 URL 自动识别托管平台，
 * 用对应的 API 基址与鉴权头。
 *
 * 设计要点（都是踩过的坑）：
 *  1. **不要求用户粘贴令牌**：从 git 凭据助手（Windows 凭据管理器）读取
 *     （`git credential fill`）。⚠️ 令牌**只进变量、绝不打印**。
 *  2. **自动选对 remote**：上游通常没有推送权限（403）。先探测上游
 *     `permission.push`，不可推就改用 fork，并在 fork 无权限时**明确报错**，
 *     而不是让你对着 403 猜。
 *  3. **中文不乱码**：请求体按 UTF-8 字节发送。
 *  4. **默认预演**：不加 `--apply` 只检查、不改动。
 *
 * 用法：
 *   node git-pr.mjs --repo <仓库路径> --branch <分支> --title <标题> \
 *        [--body-file <md>] [--upstream <owner/repo>] [--base master] [--apply|--dry-run]
 *
 * ⚠️ 默认即**预演**（只检查权限与分支，不改动任何东西）；`--apply` 才真正推送并开 PR。
 *    未知参数会直接报错（避免「以为在预演、其实已提交」）。
 *
 * 退出码：0 成功/预演通过；1 失败（stderr 给出确切原因）。
 */
import { execFileSync } from 'node:child_process'
import { readFileSync, existsSync } from 'node:fs'

const argv = process.argv.slice(2)
const nodeMajor = Number(process.versions.node.split('.')[0])
if (nodeMajor < 18) {
  console.error('需要 Node.js 18 或更新版本（脚本使用内置 fetch）')
  process.exit(1)
}

const opt = (name, dflt) => {
  const i = argv.indexOf(`--${name}`)
  return i === -1 ? dflt : argv[i + 1]
}
const flag = (name) => argv.includes(`--${name}`)

/**
 * 参数白名单。
 *
 * ⚠️ **未知参数必须报错，不能静默忽略**：否则文档里写了 `--dry-run` 而实现没有时，
 * 脚本会**照样真推送、真开 PR** —— 用户以为在预演，实际已经提交了。
 */
const KNOWN_FLAGS = new Set(['--apply', '--dry-run', '--help'])
const KNOWN_OPTS = new Set(['--repo', '--branch', '--title', '--body-file', '--upstream', '--base'])
for (let i = 0; i < argv.length; i++) {
  const a = argv[i]
  if (KNOWN_FLAGS.has(a)) continue
  if (KNOWN_OPTS.has(a)) {
    if (!argv[i + 1] || argv[i + 1].startsWith('--')) {
      console.error(`参数 ${a} 缺少值`)
      process.exit(1)
    }
    i++
    continue
  }
  console.error(`未知参数: ${a}\n支持的参数: ${[...KNOWN_OPTS, ...KNOWN_FLAGS].join(' ')}`)
  process.exit(1)
}

if (flag('help')) {
  console.log(`git-pr.mjs —— 推 fork + 开 PR（Gitee / GitHub 通用）

用法:
  node git-pr.mjs --repo <仓库路径> --branch <分支> --title <标题> [选项]

选项:
  --repo <路径>        本地仓库路径（必填）
  --branch <分支>      要提交的分支名，须与当前 HEAD 一致（必填）
  --title <标题>       PR 标题（必填）
  --body-file <md>     PR 正文文件（可选，按 UTF-8 读取）
  --upstream <o/r>     上游仓库，默认从 origin 推导
  --base <分支>        目标分支，默认 master
  --apply              真正执行（不加则只预演，不做任何改动）
  --dry-run            显式预演（与不加 --apply 等价）
  --help               显示本帮助

退出码: 0 成功/预演通过；1 失败。`)
  process.exit(0)
}

const repo = opt('repo')
const branch = opt('branch')
const title = opt('title')
const bodyFile = opt('body-file')
const base = opt('base', 'master')
// 默认预演；`--apply` 才真正执行。`--dry-run` 是显式别名。
const apply = flag('apply') && !flag('dry-run')

if (!repo || !branch || !title) {
  console.error('缺少参数。至少需要 --repo --branch --title（详见文件头注释）')
  process.exit(1)
}
if (!existsSync(repo)) {
  console.error(`仓库路径不存在: ${repo}`)
  process.exit(1)
}
let body = ''
if (bodyFile) {
  try {
    body = readFileSync(bodyFile, 'utf8')
  } catch (error) {
    console.error(`无法读取 PR 正文文件 ${bodyFile}: ${error.message}`)
    process.exit(1)
  }
}

const git = (...args) =>
  execFileSync('git', ['-C', repo, ...args], {
    encoding: 'utf8',
    env: { ...process.env, GIT_TERMINAL_PROMPT: '0', GCM_INTERACTIVE: 'never' },
  }).trim()

const parseRepoUrl = (url) => {
  const match = /(gitee\.com|github\.com)[/:]([^/]+)\/([^/]+?)(?:\.git)?$/.exec(url)
  if (!match) return null
  return { host: match[1], fullName: `${match[2]}/${match[3]}` }
}

/** 托管平台差异集中在这里：API 基址、鉴权头、权限字段名。 */
const HOSTS = {
  'gitee.com': {
    label: 'Gitee',
    apiBase: 'https://gitee.com/api/v5',
    authHeader: (t) => ({ Authorization: `token ${t}` }),
    // Gitee 用单数 `permission.push`
    pushFlag: (r) => r.permission?.push === true,
  },
  'github.com': {
    label: 'GitHub',
    apiBase: 'https://api.github.com',
    authHeader: (t) => ({
      Authorization: `Bearer ${t}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    }),
    // GitHub 用复数 `permissions.push`
    pushFlag: (r) => r.permissions?.push === true,
  },
}

/**
 * 从 git 凭据助手取令牌。⚠️ 返回值绝不打印。
 * 加超时：凭据助手缺失时不应把会话挂死。
 */
function readToken(host) {
  let out
  try {
    out = execFileSync('git', ['credential', 'fill'], {
      input: `protocol=https\nhost=${host}\n\n`,
      encoding: 'utf8',
      timeout: 20000,
      env: { ...process.env, GIT_TERMINAL_PROMPT: '0', GCM_INTERACTIVE: 'never' },
    })
  } catch (error) {
    throw new Error(
      `未能从 git 凭据助手读取 ${host} 的令牌（${error.message.split('\n')[0]}）。\n` +
      `  先手动 push 一次并完成登录，凭据就会存进 Windows 凭据管理器。`
    )
  }
  const user = /^username=(.*)$/m.exec(out)?.[1]
  const pass = /^password=(.*)$/m.exec(out)?.[1]
  if (!pass) {
    throw new Error(
      `${host} 没有可用令牌（凭据助手返回空）。\n` +
      `  先手动 push 一次并登录，或运行：\n` +
      `    git credential approve  （协议 https、host ${host}、填用户名与令牌）`
    )
  }
  return { user, pass }
}

const run = async () => {
  // 0) 识别平台
  const origin = parseRepoUrl(git('remote', 'get-url', 'origin'))
  if (!origin) throw new Error('无法从 origin 识别托管平台；只支持 gitee.com / github.com 仓库 URL')
  const { host } = origin
  const platform = HOSTS[host]

  const api = async (path, init = {}, token) => {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 30000)
    let res
    let text
    try {
      res = await fetch(`${platform.apiBase}${path}`, {
        ...init,
        headers: { ...platform.authHeader(token), ...(init.headers ?? {}) },
        signal: controller.signal,
      })
      text = await res.text()
    } catch (error) {
      if (error.name === 'AbortError') throw new Error(`API 请求超时（30 秒）: ${path}`)
      throw error
    } finally {
      clearTimeout(timer)
    }
    let json
    try { json = JSON.parse(text) } catch { json = text }
    if (!res.ok) {
      const detail = typeof json === 'string' ? json.slice(0, 300) : JSON.stringify(json).slice(0, 300)
      throw new Error(`HTTP ${res.status} ${path}\n${detail}`)
    }
    return json
  }

  const { user, pass } = readToken(host)
  console.log(`平台      : ${platform.label} (${host})`)
  console.log(`凭据用户名: ${user}（令牌长度 ${pass.length}，未打印内容）`)

  // 1) 令牌身份
  const me = await api('/user', {}, pass)
  console.log(`令牌身份  : ${me.login} (${me.name ?? ''})`)

  // 2) 上游与权限
  const upstream = opt('upstream', origin.fullName)
  if (!/^[^/]+\/[^/]+$/.test(upstream)) {
    throw new Error(`上游仓库格式无效，应为 owner/repo: ${upstream}`)
  }
  console.log(`上游仓库  : ${upstream}`)

  const up = await api(`/repos/${upstream}`, {}, pass)
  const canPushUpstream = platform.pushFlag(up)
  const pushRepoFull = canPushUpstream
    ? upstream
    : `${me.login}/${upstream.split('/')[1]}`
  console.log(canPushUpstream
    ? '上游权限  : push=true → 推送到上游'
    : '上游权限  : push=false → 推送到个人 fork')

  // Verify the repository behind the selected push remote. `origin` can itself
  // be a fork, so its name alone is not enough to identify the PR head.
  if (!canPushUpstream) {
    let fork
    try {
      fork = await api(`/repos/${pushRepoFull}`, {}, pass)
    } catch (error) {
      throw new Error(
        `读不到 fork ${pushRepoFull}：${error.message}\n` +
        `  请先在 ${platform.label} 上 fork ${upstream}，再重跑本脚本。`
      )
    }
    if (!platform.pushFlag(fork)) {
      throw new Error(`fork ${pushRepoFull} 没有推送权限；请确认它属于 ${me.login} 且你有写权限`)
    }
    console.log(`fork      : ${pushRepoFull} (push=true)`)
  }

  const remotes = git('remote').split('\n').filter(Boolean)
  const remoteRepos = new Map(remotes.map((name) => {
    const parsed = parseRepoUrl(git('remote', 'get-url', '--push', name))
    return [name, parsed?.fullName.toLowerCase()]
  }))
  let pushRemote = remotes.find((name) => remoteRepos.get(name) === pushRepoFull.toLowerCase())
  if (!pushRemote) {
    const preferredName = canPushUpstream ? 'upstream' : 'fork'
    pushRemote = preferredName
    let suffix = 2
    while (remotes.includes(pushRemote)) pushRemote = `${preferredName}-${suffix++}`
    const remoteUrl = `https://${host}/${pushRepoFull}.git`
    if (apply) {
      git('remote', 'add', pushRemote, remoteUrl)
      console.log(`已添加 remote ${pushRemote} -> ${pushRepoFull}`)
    } else {
      console.log(`[预演] 将添加 remote ${pushRemote} -> ${pushRepoFull}`)
    }
  }
  console.log(`推送目标  : ${pushRepoFull} (remote ${pushRemote})`)

  // 4) 分支与未提交改动
  const head = git('rev-parse', '--abbrev-ref', 'HEAD')
  if (head !== branch) throw new Error(`当前分支是 ${head}，与 --branch ${branch} 不符`)
  const dirty = git('status', '--porcelain')
  if (dirty) console.log(`⚠️ 工作区有未提交改动（不会被推送）:\n${dirty}`)
  const lastMsg = git('log', '-1', '--pretty=%s')
  console.log(`分支      : ${branch} @ ${git('rev-parse', '--short', 'HEAD')}  "${lastMsg}"`)

  if (!apply) {
    console.log('\n[预演] 一切就绪。加 --apply 执行：push + 开 PR。')
    return
  }

  // 5) 推送
  console.log(`\n推送 ${branch} -> ${pushRemote} ...`)
  console.log(git('push', pushRemote, branch) || '(无输出)')

  // 6) 开 PR（UTF-8 字节，避免中文乱码）
  //
  // ⚠️ **幂等**：对「同源分支 + 同目标分支」的重复 PR，Gitee 回 HTTP 400
  // （`已存在相同源分支、目标分支的 Pull Request`），GitHub 回 422。
  // 这不是失败，而是「已经提过了」—— 故先查已有 PR，命中就复用它。
  //
  // ⚠️ **判据必须用实测过的字段**：Gitee 的 `head.label` **只有分支名**
  // （`feat/xxx`），**不含 owner**；owner 在 `head.repo.full_name`。
  // 第一版误用 `head.label` 比对 `owner:feat/xxx` 于是永不命中，重复运行仍去
  // POST → 400。`head.ref` + `head.repo.full_name` 在两家平台上都可靠。
  const existing = await api(`/repos/${upstream}/pulls?state=open&per_page=100`, {}, pass)
  const dup = existing.find((p) =>
    p.head?.ref === branch
    && p.head?.repo?.full_name?.toLowerCase() === pushRepoFull.toLowerCase()
    && p.base?.ref === base)
  let pr
  if (dup) {
    pr = dup
    console.log(`\nℹ️ 已存在同一源/目标分支的 PR，复用它（未重复创建）`)
  } else {
    const headOwner = pushRepoFull.split('/')[0]
    const head = pushRepoFull.toLowerCase() === upstream.toLowerCase()
      ? branch
      : `${headOwner}:${branch}`
    const payload = JSON.stringify({ title, head, base, body })
    pr = await api(`/repos/${upstream}/pulls`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: Buffer.from(payload, 'utf8'),
    }, pass)
    console.log(`\n✅ 已创建 PR`)
  }
  console.log(`   #${pr.number}  [${pr.state}]  ${pr.html_url}`)

  // 7) 回读校验
  const files = await api(`/repos/${upstream}/pulls/${pr.number}/files`, {}, pass)
  console.log('   改动文件:')
  for (const f of files) console.log(`     ${f.filename}  +${f.additions}/-${f.deletions}`)
}

run().catch((error) => {
  console.error(`\n❌ ${error.message}`)
  process.exit(1)
})
