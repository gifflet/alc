// sweep.mjs — Walk every route, collecting console errors and layout overflow.
// usage: CDP_PORT=9333 node sweep.mjs <baseUrl> <projectId> [urlFragment]
import WebSocket from '../../ui/node_modules/ws/index.js'

const [baseUrl, projectId, fragment = 'localhost'] = process.argv.slice(2)
const PORT = process.env.CDP_PORT ?? 9222

const ROUTES = [
  '', 'fleet', 'queue', 'runs', 'loops', 'conduct', 'team',
  'metrics', 'compare', 'checks', 'run-configs', 'inbox', 'config/manifest',
  'review/alc%2Frun-a1b2c3d4',
]

const pages = await (await fetch(`http://localhost:${PORT}/json`)).json()
const page = pages.find((p) => p.type === 'page' && p.url.includes(fragment))
if (!page) { console.error('no page matching', fragment); process.exit(1) }

const ws = new WebSocket(page.webSocketDebuggerUrl)
let id = 0
const pending = new Map()
let logs = []

ws.on('message', (data) => {
  const msg = JSON.parse(data.toString())
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id) }
  if (msg.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(msg.params.type)) {
    logs.push(`${msg.params.type}: ${msg.params.args.map(a => a.value ?? a.description ?? a.type).join(' ')}`.slice(0, 200))
  }
  if (msg.method === 'Runtime.exceptionThrown') {
    logs.push(`exception: ${(msg.params.exceptionDetails.exception?.description ?? '').slice(0, 200)}`)
  }
})

const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const msgId = ++id
    pending.set(msgId, (m) => (m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result)))
    ws.send(JSON.stringify({ id: msgId, method, params }))
    setTimeout(() => reject(new Error(`timeout ${method}`)), 20000)
  })

await new Promise((r) => ws.on('open', r))
await send('Runtime.enable')
await send('Page.enable')

const PROBE = `(() => {
  // The original rule (scrollWidth > clientWidth on an overflow:visible box)
  // caught every real break in the pre-change baseline, and exactly one false
  // positive: Monaco's cursor layer, which has clientWidth 0 and scrollWidth 2.
  //
  // So the fix is minimal and surgical — skip boxes with NO content box at all.
  // Anything broader (e.g. "ignore whatever an overflow ancestor contains")
  // silences the baseline's real breaks too, which was verified and rejected.
  const leaks = (el) =>
    el.clientWidth > 0 &&
    el.scrollWidth > el.clientWidth + 1 &&
    getComputedStyle(el).overflowX === 'visible';
  return JSON.stringify({
    rendered: document.body.innerText.trim().length,
    pageScrollW: document.scrollingElement.scrollWidth,
    innerW: window.innerWidth,
    overflowing: [...document.querySelectorAll('body *')].filter(leaks)
      .map((e) => e.tagName + '.' + String(e.className || '').slice(0, 40)).slice(0, 4),
    density: document.documentElement.dataset.density,
  });
})()`

const results = []
for (const route of ROUTES) {
  logs = []
  const url = `${baseUrl}/projects/${projectId}${route ? '/' + route : ''}`
  await send('Page.navigate', { url })
  await new Promise((r) => setTimeout(r, 2600))
  let probe = {}
  try {
    const out = await send('Runtime.evaluate', { expression: PROBE, returnByValue: true })
    probe = JSON.parse(out.result.value)
  } catch (err) { probe = { error: err.message } }
  results.push({ route: route || '(dashboard)', ...probe, logs: [...new Set(logs)] })
}

let bad = 0
for (const r of results) {
  const overflow = r.pageScrollW > r.innerW
  const issues = []
  if (overflow) issues.push(`PAGE OVERFLOW ${r.pageScrollW}>${r.innerW}`)
  if (r.overflowing?.length) issues.push(`inner overflow: ${r.overflowing.join(', ')}`)
  if (!r.rendered) issues.push('EMPTY RENDER')
  if (r.logs?.length) issues.push(...r.logs)
  if (r.error) issues.push(`probe error: ${r.error}`)
  if (issues.length) bad++
  console.log(`${issues.length ? 'FAIL' : ' ok '}  ${(r.route).padEnd(16)} ${issues.join(' | ') || `(density=${r.density})`}`)
}
console.log(`\n${results.length - bad}/${results.length} routes clean`)
ws.close()
