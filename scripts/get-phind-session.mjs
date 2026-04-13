#!/usr/bin/env node
/**
 * Extract Phind cookies from live Edge session using CDP
 * Usage: node scripts/get-phind-session.mjs
 */
import CDP from 'chrome-remote-interface'
import { spawn } from 'child_process'
import { writeFileSync, mkdirSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const projectRoot = join(__dirname, '..')

const EDGE_PATHS = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  process.env.LOCALAPPDATA + '\\Microsoft\\Edge\\Application\\msedge.exe'
]

const CDP_PORT = 9222
const PROFILE_PATH = join(projectRoot, 'auth', 'phind-edge-profile')

async function findEdge() {
  const fs = await import('fs')
  for (const path of EDGE_PATHS) {
    if (fs.existsSync(path)) {
      return path
    }
  }
  throw new Error('Edge not found')
}

async function launchEdgeWithCDP() {
  const edgePath = await findEdge()
  
  console.log('Launching Edge with CDP...')
  const edge = spawn(edgePath, [
    `--user-data-dir=${PROFILE_PATH}`,
    `--remote-debugging-port=${CDP_PORT}`,
    '--no-first-run',
    '--no-default-browser-check',
    'https://www.phind.com'
  ], {
    detached: true,
    stdio: 'ignore'
  })
  
  edge.unref()
  
  // Wait for CDP to be ready
  await new Promise(resolve => setTimeout(resolve, 3000))
  
  return edge
}

async function extractCookies() {
  let client
  
  try {
    console.log('Connecting to CDP...')
    client = await CDP({ port: CDP_PORT })
    
    const { Network } = client
    await Network.enable()
    
    console.log('Extracting cookies...')
    const { cookies } = await Network.getAllCookies()
    
    // Filter Phind cookies
    const phindCookies = cookies.filter(c => 
      c.domain.includes('phind.com') || c.domain.includes('.phind.com') || c.domain.includes('phindai.org')
    )
    
    if (phindCookies.length === 0) {
      console.log('Warning: No Phind cookies found!')
      console.log('Make sure you logged in to phind.com')
      console.log('')
      console.log('All cookies:')
      cookies.forEach(c => {
        console.log(`  - ${c.name} (domain: ${c.domain})`)
      })
      return null
    }
    
    console.log(`Found ${phindCookies.length} Phind cookies:`)
    phindCookies.forEach(c => {
      console.log(`  - ${c.name} (domain: ${c.domain})`)
    })
    
    // Build cookie header
    const cookieHeader = phindCookies
      .map(c => `${c.name}=${c.value}`)
      .join('; ')
    
    return {
      cookie: cookieHeader,
      cookies: phindCookies
    }
    
  } finally {
    if (client) {
      await client.close()
    }
  }
}

async function main() {
  try {
    // Launch Edge with CDP
    const edge = await launchEdgeWithCDP()
    
    console.log('')
    console.log('Browser launched. Please:')
    console.log('1. Log in to phind.com if not already logged in')
    console.log('2. Press Enter when ready to extract cookies')
    console.log('')
    
    // Wait for user input
    await new Promise(resolve => {
      process.stdin.once('data', resolve)
    })
    
    // Extract cookies
    const credentials = await extractCookies()
    
    if (!credentials) {
      console.log('Failed to extract cookies')
      process.exit(1)
    }
    
    // Save to file
    const outputPath = join(projectRoot, 'auth', 'phind-creds.json')
    mkdirSync(dirname(outputPath), { recursive: true })
    writeFileSync(outputPath, JSON.stringify(credentials, null, 2))
    
    console.log('')
    console.log(`✓ Credentials saved to: ${outputPath}`)
    console.log('')
    console.log('Cookie header preview:')
    console.log(`  ${credentials.cookie.substring(0, 100)}...`)
    console.log('')
    console.log('You can now close the browser and use Phind provider')
    
    process.exit(0)
    
  } catch (error) {
    console.error('Error:', error.message)
    process.exit(1)
  }
}

main()
