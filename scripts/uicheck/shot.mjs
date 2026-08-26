// shot.mjs — Capture a PNG of the current page via CDP.
// usage: CDP_PORT=9333 node shot.mjs <outPath> [urlFragment]
import WebSocket from '../../ui/node_modules/ws/index.js'
import { writeFileSync } from 'node:fs'

const [out, fragment = '8643'] = process.argv.slice(2)
const PORT = process.env.CDP_PORT ?? 9333
const pages = await (await fetch(`http://localhost:${PORT}/json`)).json()
const page = pages.find((p) => p.type === 'page' && p.url.includes(fragment))
if (!page) { console.error('no page'); process.exit(1) }
const ws = new WebSocket(page.webSocketDebuggerUrl)
let id = 0
const pending = new Map()
ws.on('message', (d) => { const m = JSON.parse(d.toString()); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) } })
const send = (method, params = {}) => new Promise((res, rej) => {
  const i = ++id; pending.set(i, (m) => m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result))
  ws.send(JSON.stringify({ id: i, method, params })); setTimeout(() => rej(new Error('timeout')), 20000)
})
await new Promise((r) => ws.on('open', r))
const { data } = await send('Page.captureScreenshot', { format: 'png' })
writeFileSync(out, Buffer.from(data, 'base64'))
console.log('saved', out)
ws.close()
