import type { SiteCandidate, SiteSubscores, SuitabilityWeights } from './api-client';
import { overallFromWeights } from './api-client';

export const DEFAULT_WEIGHTS: SuitabilityWeights = {
  broadband: 0.2,
  transmission: 0.3,
  climate: 0.15,
  water: 0.15,
  transport: 0.2,
};

export interface SiteConstraints {
  min_overall_score?: number;
  min_transmission?: number;
  min_broadband?: number;
  min_water?: number;
  min_climate?: number;
  min_transport?: number;
}

export interface DealBreakerRule {
  domain: keyof SiteSubscores | 'overall';
  min_score: number;
  label: string;
}

export interface DealBreakerResult {
  site_index: number;
  coordinates: { lat: number; lon: number };
  overall_score: number;
  passed: boolean;
  failures: string[];
  passes: string[];
}

export interface SiteComparisonRow {
  site_index: number;
  coordinates: { lat: number; lon: number };
  overall_score: number;
  subscores: SiteSubscores;
  strengths: string[];
  weaknesses: string[];
  reasons: string[];
}

export interface SiteComparisonResult {
  sites_compared: number;
  winner_index: number | null;
  rows: SiteComparisonRow[];
  summary: string;
}

export function siteLabel(c: SiteCandidate, index: number): string {
  const pct = Math.round(c.overall_score * 100);
  const { lat, lon } = c.coordinates;
  return `Site ${index + 1} (${lat.toFixed(4)}, ${lon.toFixed(4)}) — ${pct}/100`;
}

export function resolveSitesFromContext(
  sites: SiteCandidate[] | undefined,
  siteIndices: number[] | undefined,
  contextCandidates: SiteCandidate[] | undefined
): SiteCandidate[] {
  const pool = contextCandidates ?? sites ?? [];
  if (siteIndices?.length) {
    return siteIndices
      .map((i) => pool[i - 1])
      .filter((s): s is SiteCandidate => s != null);
  }
  if (sites?.length) return sites;
  return pool.slice(0, 4);
}

export function reweightCandidates(
  candidates: SiteCandidate[],
  weights: Partial<SuitabilityWeights>
): SiteCandidate[] {
  const merged: SuitabilityWeights = { ...DEFAULT_WEIGHTS, ...weights };
  return candidates
    .map((c) => ({
      ...c,
      overall_score: overallFromWeights(c.subscores, merged),
    }))
    .sort((a, b) => b.overall_score - a.overall_score);
}

export function applyConstraints(
  candidates: SiteCandidate[],
  constraints: SiteConstraints
): { passed: SiteCandidate[]; failed: SiteCandidate[] } {
  const passed: SiteCandidate[] = [];
  const failed: SiteCandidate[] = [];

  for (const c of candidates) {
    const fails: string[] = [];
    if (constraints.min_overall_score != null && c.overall_score < constraints.min_overall_score) {
      fails.push(`overall ${Math.round(c.overall_score * 100)} < ${Math.round(constraints.min_overall_score * 100)}`);
    }
    const subKeys: (keyof SiteSubscores)[] = ['transmission', 'broadband', 'water', 'climate', 'transport'];
    for (const k of subKeys) {
      const minKey = `min_${k}` as keyof SiteConstraints;
      const min = constraints[minKey] as number | undefined;
      if (min != null && c.subscores[k] < min) {
        fails.push(`${k} ${Math.round(c.subscores[k] * 100)} < ${Math.round(min * 100)}`);
      }
    }
    if (fails.length) failed.push({ ...c, reasons: [...c.reasons, `Filtered: ${fails.join('; ')}`] });
    else passed.push(c);
  }
  return { passed, failed };
}

export function checkDealBreakers(
  candidates: SiteCandidate[],
  rules: DealBreakerRule[]
): DealBreakerResult[] {
  return candidates.map((c, idx) => {
    const failures: string[] = [];
    const passes: string[] = [];
    for (const rule of rules) {
      const score =
        rule.domain === 'overall' ? c.overall_score : c.subscores[rule.domain as keyof SiteSubscores];
      if (score >= rule.min_score) {
        passes.push(`${rule.label}: ${Math.round(score * 100)}/100 (min ${Math.round(rule.min_score * 100)})`);
      } else {
        failures.push(`${rule.label}: ${Math.round(score * 100)}/100 below min ${Math.round(rule.min_score * 100)}`);
      }
    }
    return {
      site_index: idx + 1,
      coordinates: c.coordinates,
      overall_score: c.overall_score,
      passed: failures.length === 0,
      failures,
      passes,
    };
  });
}

function topStrengths(c: SiteCandidate): string[] {
  return Object.entries(c.subscores)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 2)
    .map(([k, v]) => `${k} ${Math.round(v * 100)}/100`);
}

function topWeaknesses(c: SiteCandidate): string[] {
  return Object.entries(c.subscores)
    .sort(([, a], [, b]) => a - b)
    .slice(0, 2)
    .map(([k, v]) => `${k} ${Math.round(v * 100)}/100`);
}

export function compareSites(sites: SiteCandidate[]): SiteComparisonResult {
  if (sites.length === 0) {
    return { sites_compared: 0, winner_index: null, rows: [], summary: 'No sites to compare.' };
  }

  const rows: SiteComparisonRow[] = sites.map((c, i) => ({
    site_index: i + 1,
    coordinates: c.coordinates,
    overall_score: c.overall_score,
    subscores: c.subscores,
    strengths: topStrengths(c),
    weaknesses: topWeaknesses(c),
    reasons: c.reasons.slice(0, 4),
  }));

  const sorted = [...rows].sort((a, b) => b.overall_score - a.overall_score);
  const winner = sorted[0];

  const domainWinners = (Object.keys(DEFAULT_WEIGHTS) as (keyof SiteSubscores)[]).map((domain) => {
    const best = rows.reduce((a, b) => (a.subscores[domain] >= b.subscores[domain] ? a : b));
    return `${domain}: Site ${best.site_index}`;
  });

  const summary =
    `Compared ${sites.length} sites. Highest overall: Site ${winner.site_index} ` +
    `(${Math.round(winner.overall_score * 100)}/100). Domain leaders — ${domainWinners.join(', ')}.`;

  return {
    sites_compared: sites.length,
    winner_index: winner.site_index,
    rows,
    summary,
  };
}

export function formatCandidatesContext(candidates: SiteCandidate[], label = 'Map candidates'): string {
  if (!candidates.length) return '';
  const lines = candidates.slice(0, 12).map((c, i) => {
    const subs = Object.entries(c.subscores)
      .map(([k, v]) => `${k}:${Math.round(v * 100)}`)
      .join(', ');
    return (
      `${i + 1}. ${c.coordinates.lat.toFixed(4)}, ${c.coordinates.lon.toFixed(4)} — ` +
      `overall ${Math.round(c.overall_score * 100)}/100 (${subs})`
    );
  });
  return `${label} (${candidates.length} total, showing top ${lines.length}):\n${lines.join('\n')}`;
}

export function parseWeightAdjustments(text: string): Partial<SuitabilityWeights> | null {
  const lower = text.toLowerCase();
  const weights: Partial<SuitabilityWeights> = {};
  const boosts: Partial<Record<keyof SiteSubscores, number>> = {};

  const domainAliases: Record<string, keyof SiteSubscores> = {
    power: 'transmission',
    grid: 'transmission',
    transmission: 'transmission',
    fiber: 'broadband',
    broadband: 'broadband',
    connectivity: 'broadband',
    climate: 'climate',
    cooling: 'climate',
    water: 'water',
    transport: 'transport',
    logistics: 'transport',
  };

  for (const [alias, domain] of Object.entries(domainAliases)) {
    if (lower.includes(`more ${alias}`) || lower.includes(`prioritize ${alias}`) || lower.includes(`care more about ${alias}`)) {
      boosts[domain] = (boosts[domain] ?? 0) + 0.15;
    }
    if (lower.includes(`less ${alias}`) || lower.includes(`deprioritize ${alias}`)) {
      boosts[domain] = (boosts[domain] ?? 0) - 0.1;
    }
  }

  if (Object.keys(boosts).length === 0) return null;

  const base = { ...DEFAULT_WEIGHTS };
  for (const [k, delta] of Object.entries(boosts) as [keyof SiteSubscores, number][]) {
    base[k] = Math.max(0.05, base[k] + delta);
  }
  const sum = Object.values(base).reduce((a, b) => a + b, 0);
  for (const k of Object.keys(base) as (keyof SiteSubscores)[]) {
    weights[k] = base[k] / sum;
  }
  return weights;
}
