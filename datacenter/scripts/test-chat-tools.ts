/**
 * Integration tests for chat tool execution (no OpenAI).
 * Run: npx tsx scripts/test-chat-tools.ts
 */
import { executeTool } from '../lib/chat-tools';
import type { SiteCandidate } from '../lib/api-client';

function assert(cond: unknown, msg: string) {
  if (!cond) {
    console.error('FAIL:', msg);
    process.exit(1);
  }
  console.log('OK:', msg);
}

const mockSite = (i: number, t: number, b: number): SiteCandidate => ({
  coordinates: { lat: 32.7 + i * 0.01, lon: -96.8 + i * 0.01 },
  overall_score: (t + b) / 2,
  subscores: { transmission: t, broadband: b, climate: 0.6, water: 0.5, transport: 0.5 },
  reasons: [`Site ${i} mock`],
  features_used: {},
});

const ctx = {
  mapCandidates: [mockSite(1, 0.9, 0.4), mockSite(2, 0.5, 0.85), mockSite(3, 0.3, 0.3)],
  pinnedSites: [],
};

(async () => {
  const cmp = await executeTool('compare_sites', { site_indices: [1, 2] }, ctx);
  assert((cmp.result as { sites_compared: number }).sites_compared === 2, 'compare_sites tool');

  const reweight = await executeTool(
    'reweight_sites',
    { weights: { transmission: 0.5, broadband: 0.1, climate: 0.1, water: 0.15, transport: 0.15 } },
    ctx
  );
  assert(reweight.mapCandidates?.[0].subscores.transmission === 0.9, 'reweight_sites ranks transmission-first');

  const constraints = await executeTool(
    'apply_site_constraints',
    { min_transmission: 0.6 },
    ctx
  );
  assert(
    (constraints.result as { passed_count: number }).passed_count === 1,
    'apply_site_constraints filters map'
  );

  const deal = await executeTool(
    'check_deal_breakers',
    {
      rules: [{ domain: 'broadband', min_score: 0.7, label: 'Min fiber' }],
    },
    ctx
  );
  assert(
    (deal.result as { evaluations: { passed: boolean }[] }).evaluations.filter((e) => e.passed).length === 1,
    'check_deal_breakers tool'
  );

  // Live backend call (skip if API down)
  try {
    const climate = await executeTool('get_climate', { lat: 32.7767, lon: -96.797 }, {});
    const r = climate.result as Record<string, unknown>;
    assert(!r.error, 'get_climate hits backend');
  } catch (e) {
    console.warn('SKIP: backend not reachable for get_climate');
  }

  console.log('\nAll chat tool tests passed.');
})();
