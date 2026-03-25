#!/usr/bin/env node
/**
 * VeriTax — Reclaim zkFetch Bridge
 *
 * Migrated from VeriTask proof_generator.
 * Fetches a URL using Reclaim Protocol's zkFetch and outputs zkProof JSON.
 * Used by AuditorClaw to prove ScannerClaw data came from real OKX API.
 *
 * Usage:
 *   node zkfetch_bridge.js <url> [--app-id <id>] [--app-secret <secret>]
 *       [--method <GET|POST>] [--headers-json <json>] [--body-file <path>]
 *
 * Output (JSON to stdout):
 *   { type: "reclaim_zkfetch", proof: {...}, response_body: "..." }
 *   or on failure:
 *   { type: "sha256_mock", hash: "<sha256>", note: "fallback: <reason>" }
 */

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');
const { URL } = require('url');

function loadDotenvFromWorkspace() {
    const envPath = path.resolve(__dirname, '..', '..', '.env');
    if (!fs.existsSync(envPath)) {
        return;
    }

    const content = fs.readFileSync(envPath, 'utf8');
    for (const rawLine of content.split(/\r?\n/)) {
        const line = rawLine.trim();
        if (!line || line.startsWith('#') || !line.includes('=')) {
            continue;
        }
        const idx = line.indexOf('=');
        const key = line.slice(0, idx).trim();
        const value = line.slice(idx + 1).trim();
        if (!(key in process.env)) {
            process.env[key] = value;
        }
    }
}

/**
 * Proxy-aware HTTP GET/POST using https-proxy-agent.
 * Node.js 24 native fetch() does local DNS even with HTTP_PROXY set,
 * which fails when GFW blocks the target domain's DNS.
 * This function routes through the HTTP proxy so the proxy handles DNS.
 */
function proxyFetch(targetUrl, options = {}) {
    return new Promise((resolve, reject) => {
        const parsed = new URL(targetUrl);
        const proxyUrl = process.env.HTTPS_PROXY || process.env.HTTP_PROXY
            || process.env.https_proxy || process.env.http_proxy;

        let agent = undefined;
        if (proxyUrl) {
            try {
                const { HttpsProxyAgent } = require('https-proxy-agent');
                agent = new HttpsProxyAgent(proxyUrl);
            } catch (_) {
                // https-proxy-agent not available, try direct
            }
        }

        const reqOptions = {
            hostname: parsed.hostname,
            port: parsed.port || (parsed.protocol === 'https:' ? 443 : 80),
            path: parsed.pathname + parsed.search,
            method: options.method || 'GET',
            headers: options.headers || {},
        };
        if (agent) reqOptions.agent = agent;

        const mod = parsed.protocol === 'https:' ? https : http;
        const req = mod.request(reqOptions, (res) => {
            const chunks = [];
            res.on('data', (chunk) => chunks.push(chunk));
            res.on('end', () => {
                const body = Buffer.concat(chunks).toString('utf8');
                resolve({ status: res.statusCode, text: () => Promise.resolve(body) });
            });
        });
        req.on('error', reject);
        if (options.body) req.write(options.body);
        req.end();
    });
}

async function main() {
    loadDotenvFromWorkspace();

    const args = process.argv.slice(2);
    if (args.length < 1) {
        console.error('Usage: node zkfetch_bridge.js <url> [--app-id <id>] [--app-secret <secret>]');
        process.exit(1);
    }

    const url = args[0];
    let appId = process.env.RECLAIM_APP_ID || '';
    let appSecret = process.env.RECLAIM_APP_SECRET || '';
    let method = 'GET';
    let headers = { accept: 'application/json, text/plain, */*' };
    let body = undefined;

    for (let i = 1; i < args.length; i++) {
        if (args[i] === '--app-id' && args[i + 1]) { appId = args[++i]; }
        if (args[i] === '--app-secret' && args[i + 1]) { appSecret = args[++i]; }
        if (args[i] === '--method' && args[i + 1]) { method = String(args[++i]).toUpperCase(); }
        if (args[i] === '--headers-json' && args[i + 1]) {
            headers = {
                ...headers,
                ...JSON.parse(args[++i]),
            };
        }
        if (args[i] === '--body-file' && args[i + 1]) {
            body = fs.readFileSync(args[++i], 'utf8');
        }
    }

    try {
        console.error('[zkFetch] step=1 checking_credentials');
        if (!appId || !appSecret) {
            throw new Error('RECLAIM_APP_ID or RECLAIM_APP_SECRET not configured');
        }

        console.error('[zkFetch] step=2 loading_module');
        let ReclaimClient;
        try {
            ({ ReclaimClient } = require('@reclaimprotocol/zk-fetch'));
        } catch (_e1) {
            try {
                ({ ReclaimClient } = require('/app/node_modules/@reclaimprotocol/zk-fetch'));
            } catch (_e2) {
                throw new Error('zk-fetch module not found. Run: npm install');
            }
        }

        console.error('[zkFetch] step=3 module_loaded, creating_client');
        const client = new ReclaimClient(appId, appSecret);

        console.error('[zkFetch] step=4 starting_zkfetch url=' + url);
        const requestOptions = { method, headers };
        if (body !== undefined) {
            requestOptions.body = body;
        }

        // Wrap zkFetch with a timeout to allow fallback if Reclaim is unreachable
        const ZKFETCH_TIMEOUT_MS = 120_000; // 120s
        const zkResponse = await Promise.race([
            client.zkFetch(url, requestOptions),
            new Promise((_, reject) =>
                setTimeout(() => reject(new Error(`zkFetch timed out after ${ZKFETCH_TIMEOUT_MS / 1000}s`)), ZKFETCH_TIMEOUT_MS)
            ),
        ]);

        const result = {
            type: 'reclaim_zkfetch',
            proof: {
                claimData: zkResponse.claimData,
                identifier: zkResponse.identifier,
                signatures: zkResponse.signatures,
                witnesses: zkResponse.witnesses,
            },
            request: {
                url,
                method,
                headers,
            },
            response_body: zkResponse.extractedParameterValues?.data
                || zkResponse.extractedParameterValues?.body
                || JSON.stringify(zkResponse.extractedParameterValues || {}),
        };

        console.error('[zkFetch] step=5 zkfetch_complete');
        process.stdout.write(JSON.stringify(result));
        process.exit(0);
    } catch (err) {
        console.error('[zkFetch] ERROR: ' + err.message);
        try {
            const fetchOptions = { method, headers };
            if (body !== undefined) {
                fetchOptions.body = body;
            }
            const resp = await proxyFetch(url, fetchOptions);
            const responseBody = await resp.text();
            const hash = crypto.createHash('sha256').update(responseBody).digest('hex');
            process.stdout.write(JSON.stringify({
                type: 'sha256_mock',
                hash,
                request: {
                    url,
                    method,
                    headers,
                },
                response_body: responseBody,
                note: `fallback: ${err.message}`,
            }));
            process.exit(0);
        } catch (fetchErr) {
            process.stdout.write(JSON.stringify({
                type: 'sha256_mock',
                hash: '',
                request: {
                    url,
                    method,
                    headers,
                },
                response_body: '',
                note: `fallback: zkFetch (${err.message}), fetch (${fetchErr.message})`,
            }));
            process.exit(0);
        }
    }
}

main().catch((err) => {
    console.error('[zkFetch] FATAL: ' + err.message);
    process.exit(1);
});
