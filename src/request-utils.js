export function getBearerToken(req) {
  const header = req.headers.authorization || req.headers.Authorization
  if (typeof header === 'string' && header.startsWith('Bearer ')) {
    return header.slice(7).trim()
  }

  const directHeader = req.headers['x-zai-token']
  if (typeof directHeader === 'string' && directHeader.trim()) {
    return directHeader.trim()
  }

  return ''
}

export async function readJsonBody(req) {
  if (req.body && typeof req.body === 'object') {
    return req.body
  }

  const chunks = []
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk))
  }

  if (chunks.length === 0) {
    return {}
  }

  const raw = Buffer.concat(chunks).toString('utf8')
  return raw ? JSON.parse(raw) : {}
}
