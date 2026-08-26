// cdp.mjs — evaluate an expression in a page on the connected Android Chrome.
// usage: node cdp.mjs "<js expression>" [urlFragment]
import WebSocket from '../../ui/node_modules/ws/index.js'

const expression = process.argv[2]
const urlFragment = process.argv[3] ?? 'localhost:8642'

const pages = await (await fetch(`http://localhost:${process.env.CDP_PORT ?? 9222}/json`)).json()
const page = pages.find((p) => p.type === 'page' && p.url.includes(urlFragment))
if (!page) {
  console.error('no page matching', urlFragment)
  process.exit(1)
}

const ws = new WebSocket(page.webSocketDebuggerUrl)
const done = new Promise((resolve, reject) => {
  ws.on('open', () => {
    ws.send(JSON.stringify({
      id: 1,
      method: 'Runtime.evaluate',
      params: { expression, returnByValue: true, awaitPromise: true },
    }))
  })
  ws.on('message', (data) => {
    const msg = JSON.parse(data.toString())
    if (msg.id !== 1) return
    if (msg.result?.exceptionDetails) {
      reject(new Error(JSON.stringify(msg.result.exceptionDetails.exception?.description ?? msg.result.exceptionDetails)))
    } else {
      resolve(msg.result?.result?.value)
    }
    ws.close()
  })
  ws.on('error', reject)
  setTimeout(() => reject(new Error('timeout')), 15000)
})

try {
  const value = await done
  console.log(typeof value === 'string' ? value : JSON.stringify(value, null, 2))
} catch (err) {
  console.error('ERROR:', err.message)
  process.exit(1)
}
