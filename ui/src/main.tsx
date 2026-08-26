import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { App } from './app/App'
import { adoptTokenFromUrl } from './app/token'
import { registerServiceWorker } from './app/pwa'

// Before the first render: take any ?t=<token> out of the URL and store it, so
// the very first request carries it and the secret never reaches history.
adoptTokenFromUrl()
registerServiceWorker()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
