// emulate.mjs — Measure a route under emulated device metrics + touch.
// usage: CDP_PORT=9333 node emulate.mjs <url> <width> <height> <touch:0|1> <label>
import WebSocket from '../../ui/node_modules/ws/index.js'

const [url, w, h, touch, label] = process.argv.slice(2)
const PORT = process.env.CDP_PORT ?? 9333
const pages = await (await fetch(`http://localhost:${PORT}/json`)).json()
const page = pages.find((p) => p.type === 'page' && p.url.includes('8643'))
if (!page) { console.error('no page'); process.exit(1) }

const ws = new WebSocket(page.webSocketDebuggerUrl)
let id = 0
const pending = new Map()
ws.on('message', (d) => { const m = JSON.parse(d.toString()); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) } })
const send = (method, params = {}) => new Promise((res, rej) => {
  const i = ++id; pending.set(i, (m) => m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result))
  ws.send(JSON.stringify({ id: i, method, params })); setTimeout(() => rej(new Error('timeout ' + method)), 15000)
})
await new Promise((r) => ws.on('open', r))
await send('Runtime.enable')
await send('Page.enable')
await send('Emulation.setDeviceMetricsOverride', {
  width: Number(w), height: Number(h), deviceScaleFactor: 2, mobile: touch === '1',
})
await send('Emulation.setTouchEmulationEnabled', { enabled: touch === '1', maxTouchPoints: 1 })
await send('Page.navigate', { url })
await new Promise((r) => setTimeout(r, 3200))

const probe = `JSON.stringify({
  vw: innerWidth,
  coarse: matchMedia('(pointer: coarse)').matches,
  density: document.documentElement.dataset.density,
  layout: document.querySelector('nav[aria-label=Destinations]') ? 'mobile' : 'ide',
  railW: Math.round(document.querySelector('nav')?.getBoundingClientRect().width ?? 0),
  toolW: Math.round([...document.querySelectorAll('div')].find(e => e.textContent.startsWith('PROJECT'))?.getBoundingClientRect().width ?? 0),
  contentW: Math.round(document.querySelector('main, .flex-1')?.getBoundingClientRect().width ?? 0),
  rowH: Math.round(document.querySelector('tbody tr')?.getBoundingClientRect().height ?? 0),
  cardCols: (() => { const g = document.querySelector('.grid'); if (!g) return 0; return getComputedStyle(g).gridTemplateColumns.split(' ').length })(),
  pageScrollW: document.scrollingElement.scrollWidth,
})`
const out = await send('Runtime.evaluate', { expression: probe, returnByValue: true })
const r = JSON.parse(out.result.value)
const usable = Math.round((r.contentW / r.vw) * 100)
console.log(`${label.padEnd(22)} ${r.vw}px coarse=${String(r.coarse).padEnd(5)} density=${(r.density||'-').padEnd(11)} layout=${r.layout.padEnd(6)} rail=${r.railW} tool=${r.toolW} content=${r.contentW} (${usable}% da tela) cols=${r.cardCols} overflow=${r.pageScrollW > r.vw}`)

if (process.env.PROBE) {
  const extra = await send('Runtime.evaluate', { expression: process.env.PROBE, returnByValue: true })
  console.log('  probe:', extra.result.value)
}

if (process.env.SHOT) {
  const { data } = await send('Page.captureScreenshot', { format: 'png' })
  const { writeFileSync } = await import('node:fs')
  writeFileSync(process.env.SHOT, Buffer.from(data, 'base64'))
  console.log('  screenshot:', process.env.SHOT)
}

await send('Emulation.clearDeviceMetricsOverride')
await send('Emulation.setTouchEmulationEnabled', { enabled: false })
ws.close()
