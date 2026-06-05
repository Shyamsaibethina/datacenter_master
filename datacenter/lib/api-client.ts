import type { paths } from '../types/api-schema';

type ApiPaths = paths;

// Extract response types from OpenAPI schema
export type GeocodingResult = ApiPaths['/geocode']['post']['responses']['200']['content']['application/json'];
export type ElectricityPriceResponse = ApiPaths['/api/electricity-price']['post']['responses']['200']['content']['application/json'];
export type UtilityRatesResponse = ApiPaths['/api/utility-rates']['post']['responses']['200']['content']['application/json'];
export type TransmissionLinesResponse = ApiPaths['/api/transmission-lines']['post']['responses']['200']['content']['application/json'];
export type ClimateDataResponse = ApiPaths['/api/datacenter-climate']['post']['responses']['200']['content']['application/json'];
export type WaterResourcesResponse = ApiPaths['/api/water-resources']['post']['responses']['200']['content']['application/json'];
export type WindTurbinesResponse = ApiPaths['/api/wind-turbines-by-state']['post']['responses']['200']['content']['application/json'];
export type BroadbandResponse = ApiPaths['/api/broadband-connectivity']['post']['responses']['200']['content']['application/json'];
export type TransportationResponse = ApiPaths['/api/transportation-logistics']['post']['responses']['200']['content']['application/json'];
export type HighwayAccessResponse = ApiPaths['/api/highway-access']['post']['responses']['200']['content']['application/json'];
export type RailConnectivityResponse = ApiPaths['/api/rail-connectivity']['post']['responses']['200']['content']['application/json'];

// Request types
export type CityRequest = ApiPaths['/api/electricity-price']['post']['requestBody']['content']['application/json'];
export type CoordinatesRequest = ApiPaths['/api/utility-rates']['post']['requestBody']['content']['application/json'];

// Base API client configuration. Override with NEXT_PUBLIC_API_URL for deploys;
// defaults to the local FastAPI server.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ── Site scoring / candidate types (hand-written; the generated api-schema is
// stale and predates these endpoints). ────────────────────────────────────────
export interface SiteSubscores {
  broadband: number;
  transmission: number;
  climate: number;
  water: number;
  transport: number;
}

export interface SiteScoreResponse {
  coordinates: { lat: number; lon: number };
  overall_score: number;
  subscores: SiteSubscores;
  reasons: string[];
  features_used: Record<string, number | null>;
  weights_used?: Record<string, number>;
}

export type SiteCandidate = Omit<SiteScoreResponse, 'weights_used'>;

export interface SiteCandidatesResponse {
  bbox: { min_lat: number; min_lon: number; max_lat: number; max_lon: number };
  grid_size: number;
  // Lattice spacing in degrees — used to draw each cell as a filled square.
  cell_dlat: number;
  cell_dlon: number;
  num_scored: number;
  num_requested: number;
  candidates: SiteCandidate[];
  // Every scored grid cell (subscores are weight-independent, enabling live
  // client-side re-weighting without another backend call).
  cells: SiteCandidate[];
}

// Domain weights for the weighted-overlay suitability model.
export type SuitabilityWeights = SiteSubscores;

// Recompute a cell's overall score from its (weight-independent) subscores and
// a user-supplied weight vector. Mirrors the backend compute_score(): the
// result is normalized by the sum of weights actually present, so any subset of
// weights still yields a 0-1 score.
export function overallFromWeights(
  subscores: SiteSubscores,
  weights: SuitabilityWeights
): number {
  let weightedSum = 0;
  let weightTotal = 0;
  (Object.keys(subscores) as (keyof SiteSubscores)[]).forEach((k) => {
    const w = weights[k];
    if (w == null) return;
    weightedSum += subscores[k] * w;
    weightTotal += w;
  });
  if (weightTotal <= 0) return 0;
  return weightedSum / weightTotal;
}

export interface SiteScoreRequest {
  lat: number;
  lon: number;
  weights?: Record<string, number>;
}

export interface SiteCandidatesRequest {
  min_lat: number;
  min_lon: number;
  max_lat: number;
  max_lon: number;
  grid_size?: number;
  top_k?: number;
  weights?: Record<string, number>;
  /** Local DuckDB only (power + fiber). Default true — fast rectangle draw. */
  fast?: boolean;
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    });

    if (!response.ok) {
      throw new Error(`API request failed: ${response.status} ${response.statusText}`);
    }

    return response.json();
  }

  // Geocoding
  async geocode(request: CityRequest): Promise<GeocodingResult> {
    return this.request<GeocodingResult>('/geocode', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  // Electricity & Energy
  async getElectricityPrice(request: CityRequest): Promise<ElectricityPriceResponse> {
    return this.request<ElectricityPriceResponse>('/api/electricity-price', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  async getUtilityRates(request: CoordinatesRequest): Promise<UtilityRatesResponse> {
    return this.request<UtilityRatesResponse>('/api/utility-rates', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  async getTransmissionLines(request: CoordinatesRequest): Promise<TransmissionLinesResponse> {
    return this.request<TransmissionLinesResponse>('/api/transmission-lines', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  // Weather & Climate
  async getClimateData(request: CoordinatesRequest): Promise<ClimateDataResponse> {
    return this.request<ClimateDataResponse>('/api/datacenter-climate', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  // Water Resources
  async getWaterResources(request: CoordinatesRequest): Promise<WaterResourcesResponse> {
    return this.request<WaterResourcesResponse>('/api/water-resources', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  // Wind Energy
  async getWindTurbinesByState(request: CityRequest): Promise<WindTurbinesResponse> {
    return this.request<WindTurbinesResponse>('/api/wind-turbines-by-state', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  async getWindTurbinesNearLocation(request: CoordinatesRequest): Promise<WindTurbinesResponse> {
    return this.request<WindTurbinesResponse>('/api/wind-turbines-near-location', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  // Broadband & Connectivity
  async getBroadbandConnectivity(request: CoordinatesRequest): Promise<BroadbandResponse> {
    return this.request<BroadbandResponse>('/api/broadband-connectivity', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  // Transportation & Logistics
  async getTransportationLogistics(request: CoordinatesRequest): Promise<TransportationResponse> {
    return this.request<TransportationResponse>('/api/transportation-logistics', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  async getHighwayAccess(request: CoordinatesRequest): Promise<HighwayAccessResponse> {
    return this.request<HighwayAccessResponse>('/api/highway-access', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  async getRailConnectivity(request: CoordinatesRequest): Promise<RailConnectivityResponse> {
    return this.request<RailConnectivityResponse>('/api/rail-connectivity', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  // Site suitability scoring
  async getSiteScore(request: SiteScoreRequest): Promise<SiteScoreResponse> {
    return this.request<SiteScoreResponse>('/api/site-score', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  // Region search: sample + rank candidate sites within a bbox
  async findSiteCandidates(request: SiteCandidatesRequest): Promise<SiteCandidatesResponse> {
    return this.request<SiteCandidatesResponse>('/api/site-candidates', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  // ── Map overlays (one-time full US datasets) ───────────────────────────────

  async getTransmissionOverlayAll(): Promise<GeoJSON.FeatureCollection> {
    return this.request<GeoJSON.FeatureCollection>('/transmission/all', { method: 'GET' });
  }

  async getWaterOverlayAll(): Promise<GeoJSON.FeatureCollection> {
    return this.request<GeoJSON.FeatureCollection>('/water/all', { method: 'GET' });
  }
}

export const apiClient = new ApiClient();