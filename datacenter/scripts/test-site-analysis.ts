/**
 * Pure-function tests for tier 3 site analysis helpers.
 * Run: npm run test:analysis
 */
import {
  compareSites,
  reweightCandidates,
  applyConstraints,
  checkDealBreakers,
  resolveSitesFromContext,
  parseWeightAdjustments,
  DEFAULT_WEIGHTS,
} from '../lib/site-analysis';

function assert(cond: unknown, msg: string) {
  if (!cond) {
    console.error('FAIL:', msg);
    process.exit(1);
  }
  console.log('OK:', msg);
}

const site = (
  lat: number,
  lon: number,
  subs: { transmission: number; broadband: number; climate: number; water: number; transport: number },
  score: number
) => ({
  coordinates: { lat, lon },
  overall_score: score,
  subscores: subs,
  reasons: ['test reason'],
  features_used: {} as Record<string, number | null>,
});

const s1 = site(40.0, -83.0, { transmission: 0.9, broadband: 0.5, climate: 0.6, water: 0.4, transport: 0.5 }, 0.65);
const s2 = site(40.1, -83.1, { transmission: 0.5, broadband: 0.9, climate: 0.6, water: 0.7, transport: 0.5 }, 0.62);
const s3 = site(40.2, -83.2, { transmission: 0.3, broadband: 0.3, climate: 0.8, water: 0.9, transport: 0.6 }, 0.55);

const cmp = compareSites([s1, s2, s3]);
assert(cmp.sites_compared === 3, 'compareSites count');
assert(cmp.winner_index === 1, 'compareSites winner is site 1');
assert(cmp.rows.length === 3, 'compareSites rows');

const pool = [s1, s2, s3];
const resolved = resolveSitesFromContext(undefined, [2, 3], pool);
assert(resolved.length === 2 && resolved[0] === s2, 'resolveSitesFromContext indices');

const reweighted = reweightCandidates(pool, {
  transmission: 0.5,
  broadband: 0.1,
  climate: 0.1,
  water: 0.1,
  transport: 0.2,
});
assert(reweighted[0].coordinates.lat === 40.0, 'reweight boosts transmission-heavy site');

const { passed, failed } = applyConstraints(pool, { min_transmission: 0.6 });
assert(passed.length === 1 && failed.length === 2, 'applyConstraints filters');

const evals = checkDealBreakers(pool, [
  { domain: 'transmission', min_score: 0.85, label: 'Strong grid access' },
]);
assert(evals.filter((e) => e.passed).length === 1, 'checkDealBreakers pass/fail');
assert(evals[0].passed && !evals[1].passed, 'only site 1 passes transmission threshold');

const w = parseWeightAdjustments('What if I care more about power than fiber?');
assert(w && w.transmission! > DEFAULT_WEIGHTS.transmission, 'parseWeightAdjustments boosts transmission');

console.log('\nAll site-analysis tests passed.');
