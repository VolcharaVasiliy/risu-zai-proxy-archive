import http from 'node:http'
import chatCompletionsHandler from './api/v1/chat/completions.js'
import modelsHandler from './api/v1/models.js'

const port = Number(process.env.PORT || '3000')

const server = http.createServer(async (req, res) => {
  try {
    if (req.url === '/health') {
      res.statusCode = 200
      res.setHeader('Content-Type', 'application/json; charset=utf-8')
      res.end(JSON.stringify({ ok: true }))
      return
    }

    if (req.url === '/v1/models' && req.method === 'GET') {
      await modelsHandler(req, res)
      return
    }

    if (req.url === '/v1/chat/completions') {
      await chatCompletionsHandler(req, res)
      return
    }

    res.statusCode = 404
    res.setHeader('Content-Type', 'application/json; charset=utf-8')
    res.end(JSON.stringify({ error: { message: 'Not found' } }))
  } catch (error) {
    res.statusCode = 500
    res.setHeader('Content-Type', 'application/json; charset=utf-8')
    res.end(JSON.stringify({ error: { message: error instanceof Error ? error.message : String(error) } }))
  }
})

server.listen(port, () => {
  console.log(`Risu Z.ai proxy listening on http://127.0.0.1:${port}`)
})
