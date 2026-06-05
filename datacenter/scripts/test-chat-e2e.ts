/**
 * E2E smoke test for /api/chat with map context (requires dev server + OPENAI_API_KEY).
 * Run: npx tsx scripts/test-chat-e2e.ts
 */
import { readFileSync } from 'fs';
import { resolve } from 'path';

// Load .env manually for script
try {
  const env = readFileSync(resolve(__dirname, '../.env'), 'utf8');
  for (const line of env.split('\n')) {
    const m = line.match(/^([^#=]+)=(.*)$/);
    if (m) process.env[m[1].trim()] ??= m[2].trim();
  }
} catch {
  /* no .env */
}

const mockSite = (i: number) => ({
  coordinates: { lat: 32.77 + i * 0.02, lon: -96.79 + i * 0.02 },
  overall_score: 0.6 + i * 0.05,
  subscores: { transmission: 0.7 + i * 0.05, broadband: 0.5, climate: 0.6, water: 0.5, transport: 0.5 },
  reasons: [`Mock site ${i}`],
  features_used: {},
});

async function main() {
  const base = process.env.CHAT_TEST_URL ?? 'http://localhost:3000';

  const res = await fetch(`${base}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: 'Compare site 1 and site 2 on transmission vs broadband. Which wins overall?',
      history: [],
      context: {
        mapCandidates: [mockSite(1), mockSite(2), mockSite(3)],
        searchSummary: 'Test search near Dallas',
      },
    }),
  });

  if (!res.ok) {
    console.error('HTTP', res.status, await res.text());
    process.exit(1);
  }

  const data = await res.json();
  if (data.error) {
    console.error('API error:', data.error);
    process.exit(1);
  }

  if (!data.response || data.response.length < 20) {
    console.error('Empty or short response:', data);
    process.exit(1);
  }

  console.log('OK: chat e2e response length', data.response.length);
  console.log('Preview:', data.response.slice(0, 200), '...');
  if (data.toolMemory?.length) {
    console.log('Tools used:', data.toolMemory.map((t: { tool: string }) => t.tool).join(', '));
  }
  console.log('\nChat e2e passed.');
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
