// Serves the POSIX installer as text/plain.
//
// It cannot live in public/: Next's static handler infers application/x-sh from
// the extension and wins over next.config headers (verified). A browser then
// DOWNLOADS the script rather than showing it, which kills the whole point of
// letting someone read it before piping it into their shell.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

export const dynamic = 'force-static'

export function GET() {
  const body = readFileSync(join(process.cwd(), 'scripts-dist', 'install.sh'), 'utf8')
  return new Response(body, {
    headers: {
      'content-type': 'text/plain; charset=utf-8',
      'cache-control': 'public, max-age=0, must-revalidate',
    },
  })
}
