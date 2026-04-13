import crypto from 'node:crypto'
import https from 'node:https'

const ZAI_API_BASE = 'https://chat.z.ai'
const X_FE_VERSION = 'prod-fe-1.0.241'
const USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36'

const MODEL_MAPPING = {
  'glm-5': 'glm-5',
  'GLM-5': 'glm-5',
  'glm-5.1': 'GLM-5.1',
  'GLM-5.1': 'GLM-5.1',
  'glm-5-turbo': 'GLM-5-Turbo',
  'GLM-5-Turbo': 'GLM-5-Turbo',
  'glm-4.7': 'glm-4.7',
  'GLM-4.7': 'glm-4.7',
  'glm-4.6v': 'glm-4.6v',
  'GLM-4.6V': 'glm-4.6v',
  'glm-4.6': 'glm-4.6',
  'GLM-4.6': 'glm-4.6',
  'glm-4.5v': 'glm-4.5v',
  'GLM-4.5V': 'glm-4.5v',
  'glm-4.5-air': 'glm-4.5-air',
  'GLM-4.5-Air': 'glm-4.5-air'
}

export const SUPPORTED_MODELS = [
  'GLM-5-Turbo',
  'glm-5',
  'glm-5.1',
  'glm-4.7',
  'glm-4.6v',
  'glm-4.6',
  'glm-4.5v',
  'glm-4.5-air'
]

function uuid(withSeparators = true) {
  const value = crypto.randomUUID()
  return withSeparators ? value : value.replace(/-/g, '')
}

function decodeJwtPayload(token) {
  const parts = token.split('.')
  if (parts.length < 2) {
    return {}
  }

  const payload = parts[1]
  const normalized = payload.replace(/-/g, '+').replace(/_/g, '/')
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
  return JSON.parse(Buffer.from(padded, 'base64').toString('utf8'))
}

export function extractUserId(token) {
  try {
    const payload = decodeJwtPayload(token)
    return payload.id || payload.user_id || payload.uid || payload.sub || 'guest'
  } catch {
    return 'guest'
  }
}

function getLatestUserText(messages) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message.role !== 'user') {
      continue
    }

    if (typeof message.content === 'string') {
      return message.content
    }

    if (Array.isArray(message.content)) {
      return message.content
        .filter((part) => part?.type === 'text' && typeof part.text === 'string')
        .map((part) => part.text)
        .join('\n')
    }

    return ''
  }

  return ''
}

export function normalizeMessages(inputMessages) {
  const messages = Array.isArray(inputMessages) ? inputMessages : []
  let systemText = ''
  const result = []

  for (const message of messages) {
    if (!message || typeof message !== 'object') {
      continue
    }

    if (message.role === 'system') {
      if (typeof message.content === 'string' && message.content.trim()) {
        systemText += `${systemText ? '\n\n' : ''}${message.content}`
      }
      continue
    }

    result.push({
      role: message.role,
      content: message.content
    })
  }

  if (systemText) {
    const firstUserIndex = result.findIndex((message) => message.role === 'user')
    if (firstUserIndex >= 0) {
      const original = result[firstUserIndex].content
      const text = typeof original === 'string'
        ? original
        : Array.isArray(original)
          ? original.filter((part) => part?.type === 'text').map((part) => part.text).join('\n')
          : ''

      result[firstUserIndex] = {
        ...result[firstUserIndex],
        content: `${systemText}\n\nUser: ${text}`
      }
    }
  }

  return result
}

function mapModel(model) {
  return MODEL_MAPPING[model] || MODEL_MAPPING[String(model).toLowerCase()] || model || 'glm-5'
}

function generateSignature(messageText, requestId, timestampMs, userId) {
  const secret = 'key-@@@@)))()((9))-xxxx&&&%%%%%'
  const metadata = `requestId,${requestId},timestamp,${timestampMs},user_id,${userId}`
  const messageBase64 = Buffer.from(messageText, 'utf8').toString('base64')
  const canonicalString = `${metadata}|${messageBase64}|${String(timestampMs)}`
  const windowIndex = Math.floor(timestampMs / (5 * 60 * 1000))
  const derivedKeyHex = crypto.createHmac('sha256', secret).update(String(windowIndex)).digest('hex')
  return crypto.createHmac('sha256', derivedKeyHex).update(canonicalString).digest('hex')
}

function buildHeaders(token, refererPath, signature) {
  const headers = {
    Accept: '*/*',
    'Accept-Encoding': signature ? 'identity' : 'gzip, deflate, br',
    'Accept-Language': 'zh-CN',
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
    Cookie: `token=${token}`,
    Origin: ZAI_API_BASE,
    Referer: `${ZAI_API_BASE}${refererPath}`,
    'User-Agent': USER_AGENT,
    'X-FE-Version': X_FE_VERSION,
    'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin'
  }

  if (signature) {
    headers['X-Signature'] = signature
    headers.Priority = 'u=1, i'
  }

  return headers
}

async function readResponseText(response) {
  try {
    return await response.text()
  } catch {
    return ''
  }
}

function httpsRequest(url, { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const target = new URL(url)
    const request = https.request(
      {
        protocol: target.protocol,
        hostname: target.hostname,
        port: target.port || 443,
        path: `${target.pathname}${target.search}`,
        method,
        headers
      },
      (response) => {
        resolve(response)
      }
    )

    request.on('error', reject)

    if (body) {
      request.write(body)
    }

    request.end()
  })
}

function collectNodeResponseText(response) {
  return new Promise((resolve, reject) => {
    const chunks = []
    response.on('data', (chunk) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)))
    response.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
    response.on('error', reject)
  })
}

export async function createChat({ token, model, firstMessageContent }) {
  const timestampSeconds = Math.floor(Date.now() / 1000)
  const messageId = uuid()
  const requestBody = {
    chat: {
      id: '',
      title: 'New Chat',
      models: [model],
      params: {},
      history: {
        messages: firstMessageContent
          ? {
              [messageId]: {
                id: messageId,
                parentId: null,
                childrenIds: [],
                role: 'user',
                content: firstMessageContent,
                timestamp: timestampSeconds,
                models: [model]
              }
            }
          : {},
        currentId: firstMessageContent ? messageId : ''
      },
      tags: [],
      flags: [],
      features: [
        {
          type: 'tool_selector',
          server: 'tool_selector_h',
          status: 'hidden'
        }
      ],
      mcp_servers: [],
      enable_thinking: false,
      auto_web_search: false,
      message_version: 1,
      extra: {},
      timestamp: Date.now()
    }
  }
  const response = await httpsRequest(`${ZAI_API_BASE}/api/v1/chats/new`, {
    method: 'POST',
    headers: buildHeaders(token, '/', null),
    body: JSON.stringify(requestBody)
  })

  if (response.statusCode !== 200 && response.statusCode !== 201) {
    const errorText = await collectNodeResponseText(response)
    throw new Error(`Z.ai createChat failed: HTTP ${response.statusCode} ${errorText}`)
  }

  const data = JSON.parse(await collectNodeResponseText(response))
  return { chatId: data.id, messageId }
}

function buildFeatureFlags(request) {
  const sourceModel = String(request.model || '')
  const lowered = sourceModel.toLowerCase()
  const enableThinking = Boolean(request.reasoning_effort) || lowered.includes('think') || lowered.includes('r1')
  const enableWebSearch = Boolean(request.web_search) || lowered.includes('search')

  return {
    image_generation: false,
    web_search: false,
    auto_web_search: enableWebSearch,
    preview_mode: true,
    flags: [],
    vlm_tools_enable: false,
    vlm_web_search_enable: false,
    vlm_website_mode: false,
    enable_thinking: enableThinking
  }
}

function buildQueryParams({ token, chatId, requestId, timestampMs, userId }) {
  const now = new Date()
  const params = new URLSearchParams({
    timestamp: String(timestampMs),
    requestId,
    user_id: userId,
    version: '0.0.1',
    platform: 'web',
    token,
    user_agent: USER_AGENT,
    language: 'zh-CN',
    languages: 'zh-CN,zh',
    timezone: 'Asia/Shanghai',
    cookie_enabled: 'true',
    screen_width: '1512',
    screen_height: '982',
    screen_resolution: '1512x982',
    viewport_height: '945',
    viewport_width: '923',
    viewport_size: '923x945',
    color_depth: '30',
    pixel_ratio: '2',
    current_url: `${ZAI_API_BASE}/c/${chatId}`,
    pathname: `/c/${chatId}`,
    search: '',
    hash: '',
    host: 'chat.z.ai',
    hostname: 'chat.z.ai',
    protocol: 'https:',
    referrer: '',
    title: 'Z.ai - Free AI Chatbot & Agent powered by GLM-5 & GLM-4.7',
    timezone_offset: '-480',
    local_time: now.toISOString(),
    utc_time: now.toUTCString(),
    is_mobile: 'false',
    is_touch: 'false',
    max_touch_points: '0',
    browser_name: 'Chrome',
    os_name: 'Windows',
    signature_timestamp: String(timestampMs)
  })

  return params.toString()
}

export async function startChatCompletion({ token, request }) {
  const normalizedMessages = normalizeMessages(request.messages)
  const mappedModel = mapModel(request.model)
  const signaturePrompt = getLatestUserText(normalizedMessages)
  const { chatId, messageId } = await createChat({
    token,
    model: mappedModel,
    firstMessageContent: signaturePrompt
  })

  const requestId = uuid()
  const timestampMs = Date.now()
  const userId = extractUserId(token)
  const signature = generateSignature(signaturePrompt, requestId, timestampMs, userId)

  const requestBody = {
    stream: request.stream !== false,
    model: mappedModel,
    messages: normalizedMessages,
    signature_prompt: signaturePrompt,
    params: {},
    extra: {},
    features: buildFeatureFlags(request),
    variables: {
      '{{USER_NAME}}': 'User',
      '{{USER_LOCATION}}': 'Unknown',
      '{{CURRENT_DATETIME}}': new Date().toISOString().replace('T', ' ').slice(0, 19),
      '{{CURRENT_DATE}}': new Date().toISOString().slice(0, 10),
      '{{CURRENT_TIME}}': new Date().toISOString().slice(11, 19),
      '{{CURRENT_WEEKDAY}}': ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][new Date().getDay()],
      '{{CURRENT_TIMEZONE}}': 'UTC',
      '{{USER_LANGUAGE}}': 'en-US'
    },
    chat_id: chatId,
    id: requestId,
    current_user_message_id: messageId,
    current_user_message_parent_id: null,
    background_tasks: {
      title_generation: true,
      tags_generation: true
    }
  }

  const query = buildQueryParams({
    token,
    chatId,
    requestId,
    timestampMs,
    userId
  })

  const response = await httpsRequest(`${ZAI_API_BASE}/api/v2/chat/completions?${query}`, {
    method: 'POST',
    headers: buildHeaders(token, `/c/${chatId}`, signature),
    body: JSON.stringify(requestBody)
  })

  if (response.statusCode !== 200) {
    const errorText = await collectNodeResponseText(response)
    throw new Error(`Z.ai chatCompletion failed: HTTP ${response.statusCode} ${errorText}`)
  }

  return {
    response,
    chatId,
    model: mappedModel
  }
}
