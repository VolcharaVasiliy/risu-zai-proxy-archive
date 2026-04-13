import { SUPPORTED_MODELS } from './zai-client.js'

function json(res, status, payload) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(payload))
}

export function sendError(res, status, message) {
  json(res, status, {
    error: {
      message,
      type: 'invalid_request_error'
    }
  })
}

export function sendModels(res) {
  json(res, 200, {
    object: 'list',
    data: SUPPORTED_MODELS.map((id) => ({
      id,
      object: 'model',
      created: 0,
      owned_by: 'z.ai'
    }))
  })
}

function createChunk({ id, model, created, delta, finishReason = null }) {
  return {
    id,
    object: 'chat.completion.chunk',
    created,
    model,
    choices: [
      {
        index: 0,
        delta,
        finish_reason: finishReason
      }
    ]
  }
}

function getIterableBody(response) {
  return response?.body ?? response
}

export async function streamSseToOpenAi({ response, res, model, chatId }) {
  const created = Math.floor(Date.now() / 1000)
  const decoder = new TextDecoder()
  let buffer = ''
  let sentRole = false
  const iterableBody = getIterableBody(response)

  res.statusCode = 200
  res.setHeader('Content-Type', 'text/event-stream; charset=utf-8')
  res.setHeader('Cache-Control', 'no-cache, no-transform')
  res.setHeader('Connection', 'keep-alive')

  for await (const chunk of iterableBody) {
    buffer += decoder.decode(chunk, { stream: true })

    while (true) {
      const boundary = buffer.indexOf('\n\n')
      if (boundary < 0) {
        break
      }

      const rawEvent = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)

      const lines = rawEvent
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())

      for (const line of lines) {
        if (!line || line === '[DONE]') {
          continue
        }

        let event
        try {
          event = JSON.parse(line)
        } catch {
          continue
        }

        if (event.type !== 'chat:completion' || !event.data) {
          continue
        }

        const payload = event.data

        if (payload.phase === 'thinking' && payload.delta_content) {
          if (!sentRole) {
            res.write(`data: ${JSON.stringify(createChunk({ id: chatId, model, created, delta: { role: 'assistant', reasoning_content: '' } }))}\n\n`)
            sentRole = true
          }
          res.write(`data: ${JSON.stringify(createChunk({ id: chatId, model, created, delta: { reasoning_content: payload.delta_content } }))}\n\n`)
          continue
        }

        if (payload.phase === 'answer' && payload.delta_content) {
          if (!sentRole) {
            res.write(`data: ${JSON.stringify(createChunk({ id: chatId, model, created, delta: { role: 'assistant', content: '' } }))}\n\n`)
            sentRole = true
          }
          res.write(`data: ${JSON.stringify(createChunk({ id: chatId, model, created, delta: { content: payload.delta_content } }))}\n\n`)
          continue
        }

        if (payload.phase === 'done' && payload.done) {
          res.write(`data: ${JSON.stringify(createChunk({ id: chatId, model, created, delta: {}, finishReason: 'stop' }))}\n\n`)
          res.end('data: [DONE]\n\n')
          return
        }

        if (payload.error || event.error) {
          const message = payload.error?.detail || JSON.stringify(payload.error || event.error)
          if (!sentRole) {
            res.write(`data: ${JSON.stringify(createChunk({ id: chatId, model, created, delta: { role: 'assistant', content: '' } }))}\n\n`)
          }
          res.write(`data: ${JSON.stringify(createChunk({ id: chatId, model, created, delta: { content: `\nError: ${message}` }, finishReason: 'stop' }))}\n\n`)
          res.end('data: [DONE]\n\n')
          return
        }
      }
    }
  }

  res.write(`data: ${JSON.stringify(createChunk({ id: chatId, model, created, delta: {}, finishReason: 'stop' }))}\n\n`)
  res.end('data: [DONE]\n\n')
}

export async function collectNonStreamResponse({ response, model, chatId }) {
  const created = Math.floor(Date.now() / 1000)
  const decoder = new TextDecoder()
  let buffer = ''
  let content = ''
  let reasoningContent = ''
  const iterableBody = getIterableBody(response)

  for await (const chunk of iterableBody) {
    buffer += decoder.decode(chunk, { stream: true })

    while (true) {
      const boundary = buffer.indexOf('\n\n')
      if (boundary < 0) {
        break
      }

      const rawEvent = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)

      const lines = rawEvent
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())

      for (const line of lines) {
        if (!line || line === '[DONE]') {
          continue
        }

        let event
        try {
          event = JSON.parse(line)
        } catch {
          continue
        }

        if (event.type !== 'chat:completion' || !event.data) {
          continue
        }

        const payload = event.data
        if (payload.phase === 'thinking' && payload.delta_content) {
          reasoningContent += payload.delta_content
        } else if (payload.phase === 'answer' && payload.delta_content) {
          content += payload.delta_content
        }
      }
    }
  }

  return {
    id: chatId,
    object: 'chat.completion',
    created,
    model,
    choices: [
      {
        index: 0,
        message: {
          role: 'assistant',
          content,
          ...(reasoningContent ? { reasoning_content: reasoningContent } : {})
        },
        finish_reason: 'stop'
      }
    ],
    usage: {
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0
    }
  }
}
