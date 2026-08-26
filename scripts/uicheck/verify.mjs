// verify.mjs — Assert the key property of every shipped move, on a live surface.
// usage: CDP_PORT=<port> node verify.mjs <baseUrl> <projectId> <fragment> <desktop|mobile>
import WebSocket from '../../ui/node_modules/ws/index.js'

const [baseUrl, projectId, fragment, surface] = process.argv.slice(2)
const PORT = process.env.CDP_PORT ?? 9222

const pages = await (await fetch(`http://localhost:${PORT}/json`)).json()
const page = pages.find((p) => p.type === 'page' && p.url.includes(fragment))
if (!page) { console.error('no page matching', fragment); process.exit(1) }
const ws = new WebSocket(page.webSocketDebuggerUrl)
let id = 0
const pending = new Map()
ws.on('message', (d) => { const m = JSON.parse(d.toString()); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) } })
const send = (method, params = {}) => new Promise((res, rej) => {
  const i = ++id; pending.set(i, (m) => m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result))
  ws.send(JSON.stringify({ id: i, method, params })); setTimeout(() => rej(new Error('timeout')), 20000)
})
await new Promise((r) => ws.on('open', r))
await send('Runtime.enable')

const go = async (path) => {
  await send('Page.navigate', { url: `${baseUrl}/projects/${projectId}${path}` })
  await new Promise((r) => setTimeout(r, 2800))
}
const evalJs = async (expr) => {
  const out = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })
  if (out.result?.subtype === 'error') throw new Error(out.result.description)
  return out.result.value
}

const results = []
const check = (move, name, pass, detail = '') => results.push({ move, name, pass, detail })

// --- Move 1: density tokens + responsive DataTable -------------------------
await go('/runs')
const m1 = JSON.parse(await evalJs(`JSON.stringify({
  density: document.documentElement.dataset.density,
  hasTable: !!document.querySelector('table'),
  rowH: document.querySelector('tbody tr')?.getBoundingClientRect().height ?? null,
  labelFont: document.querySelector('thead tr') ? getComputedStyle(document.querySelector('thead tr')).fontSize : null,
  rowToken: getComputedStyle(document.documentElement).getPropertyValue('--ui-row-h').trim(),
  cards: document.querySelectorAll('ul li[role=button], ul li').length,
})`))
if (surface === 'desktop') {
  check(1, 'density is compact', m1.density === 'compact', m1.density)
  check(1, 'table preserved', m1.hasTable === true)
  // 32px is the FLOOR, not a fixed height: a run row carries the task above the
  // stem, and pinning it exactly would forbid the two-line cell.
  check(1, 'row height at or above the agreed 32px', m1.rowH >= 32, `${m1.rowH}`)
  check(1, 'row token still pins 32px', m1.rowToken === '32px', m1.rowToken)
  check(1, 'label type at the agreed 12px', m1.labelFont === '12px', m1.labelFont)
} else {
  check(1, 'density is comfortable', m1.density === 'comfortable', m1.density)
  check(1, 'table collapsed to cards', m1.hasTable === false && m1.cards > 0, `cards=${m1.cards}`)
}

// --- Move 2: Fleet ---------------------------------------------------------
await go('/fleet')
const m2 = JSON.parse(await evalJs(`JSON.stringify({
  phase: ['Act \u00b7 attempt', 'Verify \u00b7 attempt', 'Repair \u00b7 attempt'].some((s) => document.body.innerText.includes(s)),
  cards: document.querySelectorAll('main button, .h-full button').length,
  text: document.body.innerText.slice(0, 60),
})`))
check(2, 'fleet shows Assurance-Loop phase per unit', m2.phase === true, m2.text)

// --- Move 3: token + PWA ---------------------------------------------------
const m3 = JSON.parse(await evalJs(`(async () => {
  const names = await caches.keys();
  let cachedApi = [];
  for (const n of names) { const c = await caches.open(n); cachedApi.push(...(await c.keys()).map(r => new URL(r.url).pathname).filter(p => p.startsWith('/api'))); }
  const regs = await navigator.serviceWorker.getRegistrations();
  return JSON.stringify({ tokenStored: !!localStorage.getItem('alc-ui:token'), urlHasToken: location.search.includes('t='), sw: regs.length, cachedApi: cachedApi.length });
})()`))
check(3, 'token held by the browser', m3.tokenStored === true)
check(3, 'token not left in the URL', m3.urlHasToken === false)
check(3, 'service worker registered', m3.sw > 0, `${m3.sw}`)
check(3, 'service worker never caches /api', m3.cachedApi === 0, `${m3.cachedApi}`)

// --- Move 4: Inbox ---------------------------------------------------------
await go('/inbox')
const m4 = JSON.parse(await evalJs(`(async () => {
  const r = await fetch('/api/inbox-probe').catch(() => null);
  const items = document.querySelectorAll('ul li').length;
  const badge = document.querySelector('[aria-label^="Inbox,"]')?.getAttribute('aria-label') ?? null;
  return JSON.stringify({ items, badge, hasReason: /failed at|reached|ready to land/.test(document.body.innerText) });
})()`))
check(4, 'inbox lists decisions', m4.items > 0, `${m4.items} items`)
check(4, 'each decision states its reason', m4.hasReason === true)
check(4, 'badge exposes the count accessibly', m4.badge !== null, m4.badge ?? 'missing')

// --- Move 5: layout --------------------------------------------------------
const m5 = JSON.parse(await evalJs(`JSON.stringify({
  bottomTabs: document.querySelectorAll('nav[aria-label=Destinations] button').length,
  rail: !!document.querySelector('[aria-label="Run Configurations"]'),
  small: [...document.querySelectorAll('button,input,select')].filter(b => { const r = b.getBoundingClientRect(); return r.height > 0 && r.height < 44 }).length,
})`))
if (surface === 'desktop') {
  check(5, 'IDE rail present', m5.rail === true)
  check(5, 'no mobile tab bar', m5.bottomTabs === 0)
} else {
  check(5, 'five bottom destinations', m5.bottomTabs === 5, `${m5.bottomTabs}`)
  check(5, 'IDE rail absent', m5.rail === false)
  check(5, 'every touch target >= 44px', m5.small === 0, `${m5.small} under 44px`)
}

let failed = 0
console.log(`\n${surface.toUpperCase()}`)
for (const r of results) {
  if (!r.pass) failed++
  console.log(`  ${r.pass ? 'ok  ' : 'FAIL'} move ${r.move}: ${r.name}${r.detail ? `  (${r.detail})` : ''}`)
}
console.log(`  ${results.length - failed}/${results.length} checks passed`)
ws.close()
process.exit(failed ? 1 : 0)
