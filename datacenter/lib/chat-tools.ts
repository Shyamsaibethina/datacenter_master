import type { ChatCompletionTool } from 'openai/resources/chat/completions';
import { getOpenAI } from './openai';
import { apiClient, type SiteCandidate } from './api-client';
import {
  applyConstraints,
  checkDealBreakers,
  compareSites,
  formatCandidatesContext,
  reweightCandidates,
  resolveSitesFromContext,
  type DealBreakerRule,
  type SiteConstraints,
} from './site-analysis';

export interface ChatMapContext {
  mapCandidates?: SiteCandidate[];
  pinnedSites?: SiteCandidate[];
  selectedSite?: SiteCandidate | null;
  searchSummary?: string;
}

export const AVAILABLE_TOOLS: ChatCompletionTool[] = [
  {
    type: 'function',
    function: {
      name: 'geocode_location',
      description:
        'Convert a place name into latitude/longitude. Call FIRST when the user names a place before scoring or searching.',
      parameters: {
        type: 'object',
        properties: {
          city: { type: 'string', description: "Place name, e.g. 'Dallas, TX'" },
        },
        required: ['city'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'find_best_sites',
      description:
        'Find and rank datacenter candidate sites near a location. Returns top sites with scores, subscores, and reasons.',
      parameters: {
        type: 'object',
        properties: {
          lat: { type: 'number' },
          lon: { type: 'number' },
          radius_km: { type: 'number', description: 'Search radius km (default 25, max 60)' },
          top_k: { type: 'number', description: 'How many top sites (default 5)' },
        },
        required: ['lat', 'lon'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'score_site',
      description: 'Score ONE specific lat/lon for datacenter suitability.',
      parameters: {
        type: 'object',
        properties: {
          lat: { type: 'number' },
          lon: { type: 'number' },
        },
        required: ['lat', 'lon'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'get_electricity_price',
      description: 'Industrial electricity pricing by state/city.',
      parameters: {
        type: 'object',
        properties: { city: { type: 'string' } },
        required: ['city'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'get_utility_rates',
      description: 'Detailed utility rates and tariffs for coordinates.',
      parameters: {
        type: 'object',
        properties: { lat: { type: 'number' }, lon: { type: 'number' } },
        required: ['lat', 'lon'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'get_climate',
      description: 'Climate data for datacenter cooling analysis (CDD, temperature, humidity).',
      parameters: {
        type: 'object',
        properties: { lat: { type: 'number' }, lon: { type: 'number' } },
        required: ['lat', 'lon'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'get_water_resources',
      description: 'Water availability for evaporative cooling / operations.',
      parameters: {
        type: 'object',
        properties: { lat: { type: 'number' }, lon: { type: 'number' } },
        required: ['lat', 'lon'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'get_transmission_lines',
      description: 'Nearest transmission lines — voltage, owner, distance.',
      parameters: {
        type: 'object',
        properties: { lat: { type: 'number' }, lon: { type: 'number' } },
        required: ['lat', 'lon'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'get_broadband',
      description: 'Broadband/fiber connectivity near a point.',
      parameters: {
        type: 'object',
        properties: { lat: { type: 'number' }, lon: { type: 'number' } },
        required: ['lat', 'lon'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'compare_sites',
      description:
        'Structured comparison of 2–4 sites. Use site_indices (1-based) to pick from map context, or pass explicit lat/lon pairs.',
      parameters: {
        type: 'object',
        properties: {
          site_indices: {
            type: 'array',
            items: { type: 'number' },
            description: '1-based indices from map candidates / pinned sites',
          },
          coordinates: {
            type: 'array',
            items: {
              type: 'object',
              properties: { lat: { type: 'number' }, lon: { type: 'number' } },
            },
            description: 'Optional explicit coordinates to score and compare',
          },
        },
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'apply_site_constraints',
      description:
        'Filter map candidates by min subscore thresholds. Use when user states requirements like "must have strong transmission".',
      parameters: {
        type: 'object',
        properties: {
          site_indices: { type: 'array', items: { type: 'number' } },
          min_overall_score: { type: 'number', description: '0-1' },
          min_transmission: { type: 'number', description: '0-1' },
          min_broadband: { type: 'number', description: '0-1' },
          min_water: { type: 'number', description: '0-1' },
          min_climate: { type: 'number', description: '0-1' },
          min_transport: { type: 'number', description: '0-1' },
        },
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'check_deal_breakers',
      description:
        'Pass/fail evaluation per site against explicit minimum requirements. Returns explanations for each failure.',
      parameters: {
        type: 'object',
        properties: {
          site_indices: { type: 'array', items: { type: 'number' } },
          rules: {
            type: 'array',
            items: {
              type: 'object',
              properties: {
                domain: {
                  type: 'string',
                  enum: ['overall', 'transmission', 'broadband', 'water', 'climate', 'transport'],
                },
                min_score: { type: 'number', description: '0-1 threshold' },
                label: { type: 'string' },
              },
              required: ['domain', 'min_score', 'label'],
            },
          },
        },
        required: ['rules'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'reweight_sites',
      description:
        'What-if re-ranking: adjust domain weights and re-rank map candidates. Weights should sum to ~1.',
      parameters: {
        type: 'object',
        properties: {
          site_indices: { type: 'array', items: { type: 'number' } },
          weights: {
            type: 'object',
            properties: {
              broadband: { type: 'number' },
              transmission: { type: 'number' },
              climate: { type: 'number' },
              water: { type: 'number' },
              transport: { type: 'number' },
            },
          },
        },
        required: ['weights'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'generate_site_memo',
      description:
        'Generate an IC-style investment memo (markdown) comparing 2–4 candidate sites. Use for executive summaries.',
      parameters: {
        type: 'object',
        properties: {
          site_indices: { type: 'array', items: { type: 'number' } },
          focus: { type: 'string', description: 'Optional focus, e.g. power vs water tradeoffs' },
        },
      },
    },
  },
];

export interface ToolExecutionResult {
  result: unknown;
  mapCandidates?: SiteCandidate[];
  mapCenter?: { lat: number; lon: number };
  memo?: string;
}

function contextPool(ctx: ChatMapContext): SiteCandidate[] {
  const pinned = ctx.pinnedSites ?? [];
  const map = ctx.mapCandidates ?? [];
  // Pinned first, then map (dedupe by coords)
  const seen = new Set<string>();
  const out: SiteCandidate[] = [];
  for (const s of [...pinned, ...map]) {
    const key = `${s.coordinates.lat},${s.coordinates.lon}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(s);
  }
  if (ctx.selectedSite) {
    const key = `${ctx.selectedSite.coordinates.lat},${ctx.selectedSite.coordinates.lon}`;
    if (!seen.has(key)) out.unshift(ctx.selectedSite);
  }
  return out;
}

async function scoreCoordsList(
  coords: { lat: number; lon: number }[]
): Promise<SiteCandidate[]> {
  const scored: SiteCandidate[] = [];
  for (const { lat, lon } of coords) {
    const r = await apiClient.getSiteScore({ lat, lon });
    scored.push(r);
  }
  return scored;
}

async function generateMemo(sites: SiteCandidate[], focus?: string): Promise<string> {
  const payload = sites.map((c, i) => ({
    index: i + 1,
    coordinates: c.coordinates,
    overall: Math.round(c.overall_score * 100),
    subscores: Object.fromEntries(
      Object.entries(c.subscores).map(([k, v]) => [k, Math.round(v * 100)])
    ),
    reasons: c.reasons,
  }));

  const completion = await getOpenAI().chat.completions.create({
    model: 'gpt-4o-mini',
    messages: [
      {
        role: 'system',
        content:
          'You are a datacenter site selection analyst writing an internal IC memo. Output markdown with: ' +
          '## Executive Summary (3-4 sentences), ## Site Comparison (table), ## Risks, ## Recommendation. ' +
          'Be specific using the data provided. No fluff.',
      },
      {
        role: 'user',
        content: `Sites:\n${JSON.stringify(payload, null, 2)}\n\n${focus ? `Focus: ${focus}` : ''}`,
      },
    ],
    max_tokens: 1200,
  });

  return completion.choices[0].message.content ?? '';
}

export async function executeTool(
  name: string,
  args: Record<string, unknown>,
  ctx: ChatMapContext
): Promise<ToolExecutionResult> {
  const pool = contextPool(ctx);
  let mapCandidates: SiteCandidate[] | undefined;
  let mapCenter: { lat: number; lon: number } | undefined;
  let memo: string | undefined;

  try {
    switch (name) {
      case 'geocode_location': {
        const geo = await apiClient.geocode({ city: String(args.city) });
        if (geo.error) {
          return {
            result: {
              error: `Geocoding failed for "${args.city}". Ask user for a more specific name.`,
            },
          };
        }
        if (geo.coordinates?.lat != null) {
          mapCenter = { lat: geo.coordinates.lat, lon: geo.coordinates.lon };
        }
        return { result: geo, mapCenter };
      }

      case 'get_electricity_price':
        return { result: await apiClient.getElectricityPrice({ city: String(args.city) }) };

      case 'get_utility_rates':
        return {
          result: await apiClient.getUtilityRates({
            lat: Number(args.lat),
            lon: Number(args.lon),
          }),
        };

      case 'get_climate':
        return {
          result: await apiClient.getClimateData({
            lat: Number(args.lat),
            lon: Number(args.lon),
          }),
        };

      case 'get_water_resources':
        return {
          result: await apiClient.getWaterResources({
            lat: Number(args.lat),
            lon: Number(args.lon),
          }),
        };

      case 'get_transmission_lines':
        return {
          result: await apiClient.getTransmissionLines({
            lat: Number(args.lat),
            lon: Number(args.lon),
          }),
        };

      case 'get_broadband':
        return {
          result: await apiClient.getBroadbandConnectivity({
            lat: Number(args.lat),
            lon: Number(args.lon),
          }),
        };

      case 'score_site': {
        const r = await apiClient.getSiteScore({ lat: Number(args.lat), lon: Number(args.lon) });
        mapCandidates = [r];
        return { result: r, mapCandidates };
      }

      case 'find_best_sites': {
        const lat = Number(args.lat);
        const lon = Number(args.lon);
        const radiusKm = Math.min(Math.max(Number(args.radius_km ?? 25), 1), 60);
        const dLat = radiusKm / 111;
        const dLon = radiusKm / (111 * Math.cos((lat * Math.PI) / 180));
        const r = await apiClient.findSiteCandidates({
          min_lat: lat - dLat,
          max_lat: lat + dLat,
          min_lon: lon - dLon,
          max_lon: lon + dLon,
          grid_size: 4,
          top_k: Number(args.top_k ?? 5),
          fast: false,
        });
        mapCandidates = r.candidates ?? [];
        mapCenter = { lat, lon };
        return { result: r, mapCandidates, mapCenter };
      }

      case 'compare_sites': {
        let sites = resolveSitesFromContext(
          undefined,
          args.site_indices as number[] | undefined,
          pool
        );
        const coords = args.coordinates as { lat: number; lon: number }[] | undefined;
        if (coords?.length) {
          sites = await scoreCoordsList(coords);
        }
        if (sites.length < 2 && pool.length >= 2) {
          sites = pool.slice(0, Math.min(4, pool.length));
        }
        const comparison = compareSites(sites.slice(0, 4));
        return { result: comparison };
      }

      case 'apply_site_constraints': {
        const sites = resolveSitesFromContext(
          undefined,
          args.site_indices as number[] | undefined,
          pool
        );
        const constraints: SiteConstraints = {
          min_overall_score: args.min_overall_score as number | undefined,
          min_transmission: args.min_transmission as number | undefined,
          min_broadband: args.min_broadband as number | undefined,
          min_water: args.min_water as number | undefined,
          min_climate: args.min_climate as number | undefined,
          min_transport: args.min_transport as number | undefined,
        };
        const { passed, failed } = applyConstraints(sites, constraints);
        mapCandidates = passed;
        return {
          result: {
            constraints,
            passed_count: passed.length,
            failed_count: failed.length,
            passed,
            failed,
          },
          mapCandidates: passed.length ? passed : undefined,
        };
      }

      case 'check_deal_breakers': {
        const sites = resolveSitesFromContext(
          undefined,
          args.site_indices as number[] | undefined,
          pool
        );
        const rules = args.rules as DealBreakerRule[];
        const results = checkDealBreakers(sites, rules);
        return { result: { evaluations: results, all_passed: results.every((r) => r.passed) } };
      }

      case 'reweight_sites': {
        const sites = resolveSitesFromContext(
          undefined,
          args.site_indices as number[] | undefined,
          pool
        );
        const weights = args.weights as Record<string, number>;
        const reweighted = reweightCandidates(sites, weights);
        mapCandidates = reweighted;
        return {
          result: { weights_used: weights, candidates: reweighted },
          mapCandidates: reweighted,
        };
      }

      case 'generate_site_memo': {
        let sites = resolveSitesFromContext(
          undefined,
          args.site_indices as number[] | undefined,
          pool
        );
        if (sites.length < 2) sites = pool.slice(0, Math.min(4, pool.length));
        if (sites.length === 0) {
          return { result: { error: 'No sites in context to memo. Ask user to search or pin sites.' } };
        }
        memo = await generateMemo(sites, args.focus as string | undefined);
        return { result: { memo, sites_used: sites.length }, memo };
      }

      default:
        return { result: { error: `Unknown function: ${name}` } };
    }
  } catch (error) {
    console.error(`Tool ${name} failed:`, error);
    return {
      result: {
        error: `Failed to execute ${name}: ${error instanceof Error ? error.message : 'Unknown error'}`,
      },
    };
  }
}

export function buildSystemPrompt(ctx: ChatMapContext): string {
  const parts = [
    `You are a datacenter planning assistant with map-aware context.`,
    ``,
    `Tools: geocode, find_best_sites, score_site, get_electricity_price, get_utility_rates,`,
    `get_climate, get_water_resources, get_transmission_lines, get_broadband,`,
    `compare_sites, apply_site_constraints, check_deal_breakers, reweight_sites, generate_site_memo.`,
    ``,
    `Rules:`,
    `- NEVER invent coordinates — use geocode_location or map context site indices.`,
    `- "Site 2" refers to the numbered list in map context (1-based).`,
    `- For comparisons use compare_sites with site_indices.`,
    `- For "what if I care more about X" use reweight_sites — map updates automatically.`,
    `- For requirements/deal-breakers use check_deal_breakers or apply_site_constraints.`,
    `- For IC memo / executive summary use generate_site_memo.`,
    `- When user asks about a pinned or selected site, use its coordinates from context.`,
  ];

  if (ctx.searchSummary) parts.push('', ctx.searchSummary);
  if (ctx.selectedSite) {
    parts.push(
      '',
      `Currently selected site: ${ctx.selectedSite.coordinates.lat.toFixed(4)}, ${ctx.selectedSite.coordinates.lon.toFixed(4)} ` +
        `score ${Math.round(ctx.selectedSite.overall_score * 100)}/100`
    );
  }
  if (ctx.pinnedSites?.length) {
    parts.push('', formatCandidatesContext(ctx.pinnedSites, 'Pinned sites'));
  }
  if (ctx.mapCandidates?.length) {
    parts.push('', formatCandidatesContext(ctx.mapCandidates, 'Map search results'));
  }

  return parts.join('\n');
}
