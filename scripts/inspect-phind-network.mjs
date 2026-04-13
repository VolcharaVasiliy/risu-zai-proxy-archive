#!/usr/bin/env node
/**
 * Inspect Phind network requests to find real API endpoints
 */

import { spawn } from 'child_process';
import { createInterface } from 'readline';
import CDP from 'chrome-remote-interface';

const EDGE_PATH = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const USER_DATA_DIR = './auth/phind-edge-profile';
const CDP_PORT = 9223;

console.log('Launching Edge with CDP and network monitoring...\n');

// Launch Edge
const edge = spawn(EDGE_PATH, [
  `--remote-debugging-port=${CDP_PORT}`,
  `--user-data-dir=${USER_DATA_DIR}`,
  '--no-first-run',
  '--no-default-browser-check',
  'https://phindai.org/phind-chat/'
]);

// Wait for browser to start
await new Promise(resolve => setTimeout(resolve, 3000));

console.log('Browser launched. Please:');
console.log('1. Send a test message in the chat');
console.log('2. Press Enter when you see the response\n');

// Wait for user
const rl = createInterface({ input: process.stdin, output: process.stdout });
await new Promise(resolve => rl.question('Press Enter to capture network requests...', resolve));
rl.close();

console.log('\nConnecting to CDP...');

try {
  const client = await CDP({ port: CDP_PORT });
  const { Network, Page } = client;

  // Enable network monitoring
  await Network.enable();
  await Page.enable();

  console.log('Monitoring network requests for 10 seconds...\n');
  
  const apiRequests = [];
  
  // Listen for requests
  Network.requestWillBeSent((params) => {
    const url = params.request.url;
    const method = params.request.method;
    
    // Filter for API requests
    if (url.includes('api') || url.includes('infer') || url.includes('agent') || url.includes('chat')) {
      if (method === 'POST' || method === 'GET') {
        console.log(`\n📡 ${method} ${url}`);
        console.log(`   Headers:`, JSON.stringify(params.request.headers, null, 2));
        if (params.request.postData) {
          console.log(`   Body:`, params.request.postData.substring(0, 200));
        }
        
        apiRequests.push({
          method,
          url,
          headers: params.request.headers,
          postData: params.request.postData
        });
      }
    }
  });

  // Wait for requests
  await new Promise(resolve => setTimeout(resolve, 10000));

  console.log('\n' + '='.repeat(60));
  console.log('CAPTURED API REQUESTS:');
  console.log('='.repeat(60));
  
  if (apiRequests.length === 0) {
    console.log('No API requests captured. Try sending a message in the chat.');
  } else {
    apiRequests.forEach((req, i) => {
      console.log(`\n${i + 1}. ${req.method} ${req.url}`);
    });
  }

  await client.close();
  
} catch (err) {
  console.error('CDP Error:', err.message);
}

edge.kill();
console.log('\nBrowser closed.');
