import fs from 'node:fs'
import path from 'node:path'

const requiredFiles = [
  'package.json',
  'vercel.json',
  'local-server.js',
  'api/index.py',
  'py/arcee_proxy.py',
  'py/grok_proxy.py',
  'py/gemini_web_proxy.py',
  'py/http_helpers.py',
  'py/credentials_bootstrap.py',
  'py/inflection_proxy.py',
  'py/mimo_proxy.py',
  'py/openai_web_proxy.py',
  'py/phind_proxy.py',
  'py/pi_local_proxy.py',
  'py/responses_api.py',
  'py/provider_registry.py',
  'py/server.py',
  'py/uncloseai_proxy.py',
  'py/zai_proxy.py',
  'README.md',
  'REDEPLOY.md',
  'requirements.txt',
  'scripts/get-arcee-creds.py',
  'scripts/get-qwen-creds.py',
  'scripts/get-grok-creds.py',
  'scripts/get-gemini-web-creds.py',
  'scripts/get-openai-web-creds.py',
  'scripts/get-openai-web-session.mjs',
  'scripts/launch-gemini-auth.ps1',
  'scripts/launch-openai-auth.ps1',
  'scripts/launch-grok-auth.ps1',
  'scripts/launch-pi-auth.ps1',
  'scripts/pi-browser-bridge.mjs'
]

for (const file of requiredFiles) {
  const fullPath = path.join(process.cwd(), file)
  if (!fs.existsSync(fullPath)) {
    throw new Error(`Missing required file: ${file}`)
  }
}

console.log('check: ok')
