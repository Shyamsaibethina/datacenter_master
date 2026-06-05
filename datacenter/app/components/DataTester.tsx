'use client';

import { useState } from 'react';
import { 
  apiClient, 
  type GeocodingResult,
  type ElectricityPriceResponse,
  type UtilityRatesResponse,
  type TransmissionLinesResponse,
  type ClimateDataResponse,
  type WaterResourcesResponse,
  type WindTurbinesResponse,
  type BroadbandResponse,
  type TransportationResponse,
  type HighwayAccessResponse,
  type RailConnectivityResponse
} from '../../lib/api-client';

interface ApiTool {
  id: string;
  name: string;
  description: string;
  category: 'electricity' | 'weather' | 'water' | 'wind' | 'transportation' | 'broadband';
  requiresCoordinates: boolean;
}

const AVAILABLE_TOOLS: ApiTool[] = [
  // Electricity Tools
  {
    id: 'get-electricity-price',
    name: 'Electricity Pricing',
    description: 'Get industrial electricity pricing for datacenter operations',
    category: 'electricity',
    requiresCoordinates: false,
  },
  {
    id: 'get-utility-rates',
    name: 'Utility Rates',
    description: 'Get detailed utility rates and tariffs',
    category: 'electricity',
    requiresCoordinates: true,
  },
  {
    id: 'get-transmission-lines',
    name: 'Transmission Lines',
    description: 'Get electric power transmission lines near location',
    category: 'electricity',
    requiresCoordinates: true,
  },
  
  // Weather Tools
  {
    id: 'analyze-datacenter-climate',
    name: 'Climate Analysis',
    description: 'Comprehensive climate analysis for datacenter planning',
    category: 'weather',
    requiresCoordinates: true,
  },
  
  // Water Tools
  {
    id: 'analyze-water-resources',
    name: 'Water Resources',
    description: 'Comprehensive water resource analysis',
    category: 'water',
    requiresCoordinates: true,
  },
  
  // Wind Tools
  {
    id: 'get-wind-turbines-by-state',
    name: 'Wind Turbines by State',
    description: 'Wind turbine data by state',
    category: 'wind',
    requiresCoordinates: false,
  },
  {
    id: 'get-wind-turbines-near-location',
    name: 'Nearby Wind Turbines',
    description: 'Wind turbines near specific coordinates',
    category: 'wind',
    requiresCoordinates: true,
  },
  
  // Transportation Tools
  {
    id: 'analyze-transportation-logistics',
    name: 'Transportation Analysis',
    description: 'Comprehensive transportation and logistics analysis',
    category: 'transportation',
    requiresCoordinates: true,
  },
  {
    id: 'analyze-highway-access',
    name: 'Highway Access',
    description: 'Highway access and interstate connectivity',
    category: 'transportation',
    requiresCoordinates: true,
  },
  {
    id: 'analyze-rail-connectivity',
    name: 'Rail Connectivity',
    description: 'Rail infrastructure and freight access',
    category: 'transportation',
    requiresCoordinates: true,
  },
  
  // Broadband Tools
  {
    id: 'analyze-broadband-connectivity',
    name: 'Broadband Analysis',
    description: 'Comprehensive broadband ISP analysis',
    category: 'broadband',
    requiresCoordinates: true,
  },
];

const CATEGORY_COLORS = {
  electricity: 'border-yellow-300 bg-yellow-50 text-yellow-900',
  weather: 'border-blue-300 bg-blue-50 text-blue-900',
  water: 'border-cyan-300 bg-cyan-50 text-cyan-900',
  wind: 'border-green-300 bg-green-50 text-green-900',
  transportation: 'border-purple-300 bg-purple-50 text-purple-900',
  broadband: 'border-orange-300 bg-orange-50 text-orange-900',
};

// Union type for all possible API responses
type ApiResponse = 
  | ElectricityPriceResponse
  | UtilityRatesResponse
  | TransmissionLinesResponse
  | ClimateDataResponse
  | WaterResourcesResponse
  | WindTurbinesResponse
  | BroadbandResponse
  | TransportationResponse
  | HighwayAccessResponse
  | RailConnectivityResponse;

export default function DataTester() {
  const [city, setCity] = useState('');
  const [selectedTool, setSelectedTool] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);
  const [data, setData] = useState<ApiResponse | null>(null);
  const [error, setError] = useState<string>('');
  const [coordinates, setCoordinates] = useState<{lat: number, lon: number} | null>(null);
  const [geocodingResult, setGeocodingResult] = useState<GeocodingResult | null>(null);
  const [lastGeocodedCity, setLastGeocodedCity] = useState<string>('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!city.trim() || !selectedTool || isLoading) return;

    setIsLoading(true);
    setError('');
    setData(null);

    try {
      const tool = AVAILABLE_TOOLS.find(t => t.id === selectedTool);
      if (!tool) {
        throw new Error('Invalid tool selected');
      }

      // Get coordinates if needed
      let coords = coordinates;
      let geocodeData: GeocodingResult | null = geocodingResult;
      
      // Geocode if coordinates are needed AND (no coords OR city changed)
      if (tool.requiresCoordinates && (!coords || lastGeocodedCity !== city.trim())) {
        geocodeData = await apiClient.geocode({ city: city.trim() });
        setGeocodingResult(geocodeData);
        coords = { 
          lat: geocodeData.coordinates.lat, 
          lon: geocodeData.coordinates.lon 
        };
        setCoordinates(coords);
        setLastGeocodedCity(city.trim());
      }

      // Call the appropriate API endpoint using the type-safe client
      let result: ApiResponse;
      
      switch (selectedTool) {
        case 'get-electricity-price':
          result = await apiClient.getElectricityPrice({ city: city.trim() });
          break;
          
        case 'get-utility-rates':
          if (!coords) throw new Error('Coordinates required');
          result = await apiClient.getUtilityRates({ lat: coords.lat, lon: coords.lon });
          break;
          
        case 'get-transmission-lines':
          if (!coords) throw new Error('Coordinates required');
          result = await apiClient.getTransmissionLines({ lat: coords.lat, lon: coords.lon });
          break;
          
        case 'analyze-datacenter-climate':
          if (!coords) throw new Error('Coordinates required');
          result = await apiClient.getClimateData({ lat: coords.lat, lon: coords.lon });
          break;
          
        case 'analyze-water-resources':
          if (!coords) throw new Error('Coordinates required');
          result = await apiClient.getWaterResources({ lat: coords.lat, lon: coords.lon });
          break;
          
        case 'get-wind-turbines-by-state':
          result = await apiClient.getWindTurbinesByState({ city: city.trim() });
          break;
          
        case 'get-wind-turbines-near-location':
          if (!coords) throw new Error('Coordinates required');
          result = await apiClient.getWindTurbinesNearLocation({ lat: coords.lat, lon: coords.lon });
          break;
          
        case 'analyze-broadband-connectivity':
          if (!coords) throw new Error('Coordinates required');
          result = await apiClient.getBroadbandConnectivity({ lat: coords.lat, lon: coords.lon });
          break;
          
        case 'analyze-transportation-logistics':
          if (!coords) throw new Error('Coordinates required');
          result = await apiClient.getTransportationLogistics({ lat: coords.lat, lon: coords.lon });
          break;
          
        case 'analyze-highway-access':
          if (!coords) throw new Error('Coordinates required');
          result = await apiClient.getHighwayAccess({ lat: coords.lat, lon: coords.lon });
          break;
          
        case 'analyze-rail-connectivity':
          if (!coords) throw new Error('Coordinates required');
          result = await apiClient.getRailConnectivity({ lat: coords.lat, lon: coords.lon });
          break;
          
        default:
          throw new Error(`Unknown tool: ${selectedTool}`);
      }

      setData(result);

    } catch (error) {
      console.error('Data fetch error:', error);
      setError(error instanceof Error ? error.message : 'An unexpected error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  const selectedToolObj = AVAILABLE_TOOLS.find(t => t.id === selectedTool);

  // Group tools by category
  const toolsByCategory = AVAILABLE_TOOLS.reduce((acc, tool) => {
    if (!acc[tool.category]) acc[tool.category] = [];
    acc[tool.category].push(tool);
    return acc;
  }, {} as Record<string, ApiTool[]>);

  return (
    <div className="max-w-7xl mx-auto min-h-screen bg-white">
      {/* Header */}
      <div className="border-b border-gray-200 p-6">
        <h1 className="text-3xl font-bold text-gray-900">API Data Tester</h1>
        <p className="text-gray-600 mt-2">Test datacenter APIs with raw data output</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 p-6">
        {/* Input Form */}
        <div className="lg:col-span-1">
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* City Input */}
            <div>
              <label htmlFor="city" className="block text-sm font-medium text-gray-700 mb-2">
                City Name
              </label>
              <input
                type="text"
                id="city"
                value={city}
                onChange={(e) => setCity(e.target.value)}
                placeholder="e.g., San Francisco, CA"
                disabled={isLoading}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed text-black"
              />
            </div>

            {/* API Selection */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-3">
                Select API
              </label>
              <div className="space-y-4 max-h-96 overflow-y-auto">
                {Object.entries(toolsByCategory).map(([category, tools]) => (
                  <div key={category} className="space-y-2">
                    <h3 className="text-sm font-semibold text-gray-800 capitalize border-b border-gray-200 pb-1">
                      {category}
                    </h3>
                    {tools.map((tool) => (
                      <label
                        key={tool.id}
                        className={`flex items-start p-3 border rounded-lg cursor-pointer hover:bg-gray-50 transition-colors ${
                          selectedTool === tool.id 
                            ? `${CATEGORY_COLORS[tool.category]} border-2` 
                            : 'border-gray-200'
                        }`}
                      >
                        <input
                          type="radio"
                          name="tool"
                          value={tool.id}
                          checked={selectedTool === tool.id}
                          onChange={(e) => setSelectedTool(e.target.value)}
                          disabled={isLoading}
                          className="mt-1 mr-3 text-blue-600 focus:ring-blue-500"
                        />
                        <div className="flex-1">
                          <div className="text-sm font-medium text-gray-900">
                            {tool.name}
                          </div>
                          <div className="text-xs text-gray-600 mt-1">
                            {tool.description}
                          </div>
                          {tool.requiresCoordinates && (
                            <div className="text-xs text-blue-600 mt-1">
                              📍 Requires coordinates
                            </div>
                          )}
                        </div>
                      </label>
                    ))}
                  </div>
                ))}
              </div>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={!city.trim() || !selectedTool || isLoading}
              className="w-full px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors font-medium"
            >
              {isLoading ? (
                <div className="flex items-center justify-center space-x-2">
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  <span>Fetching Data...</span>
                </div>
              ) : (
                'Get Raw Data'
              )}
            </button>
          </form>
        </div>

        {/* Results */}
        <div className="lg:col-span-2">
          {/* Geocoding Result Display */}
          {geocodingResult && (
            <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
              <p className="text-sm text-blue-800">
                📍 <strong>{geocodingResult.display_name || city}</strong>
              </p>
              <p className="text-xs text-blue-600 mt-1">
                Coordinates: {geocodingResult.coordinates.lat.toFixed(4)}, {geocodingResult.coordinates.lon.toFixed(4)} 
                | Source: {geocodingResult.source}
              </p>
            </div>
          )}

          {/* Error Display */}
          {error && (
            <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg">
              <div className="flex items-center">
                <div className="text-red-400 mr-3">
                  <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                  </svg>
                </div>
                <div>
                  <h3 className="text-sm font-medium text-red-800">Error</h3>
                  <p className="text-sm text-red-700 mt-1">{error}</p>
                </div>
              </div>
            </div>
          )}

          {/* Data Display */}
          {data && (
            <div className="bg-white border border-gray-200 rounded-lg shadow-sm">
              <div className="p-4 border-b border-gray-200 bg-gray-50">
                <h2 className="text-lg font-semibold text-gray-900">
                  Structured API Response
                </h2>
                <p className="text-sm text-gray-600 mt-1">
                  {selectedToolObj?.name} - {city} - {data.timestamp ? new Date(data.timestamp).toLocaleString() : 'No timestamp'}
                </p>
                <div className="flex items-center mt-2 space-x-4">
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                    data.success ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                  }`}>
                    {data.success ? '✅ Success' : '❌ Error'}
                  </span>
                  <span className="text-xs text-gray-500">Source: {data.source}</span>
                </div>
              </div>
              
              {/* Error Display */}
              {data.error && (
                <div className="p-4 bg-red-50 border-b border-red-200">
                  <p className="text-sm text-red-800">
                    <strong>API Error:</strong> {data.error}
                  </p>
                </div>
              )}
              
              {/* Structured Data Preview */}
              <div className="p-4">
                <div className="mb-4">
                  <h3 className="text-md font-medium text-gray-900 mb-2">Data Summary</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                    {/* Show different summaries based on data type */}
                    {'latest_price' in data && (
                      <div>
                        <span className="font-medium text-gray-700">Latest Price:</span>
                        <span className="ml-2">{data.latest_price?.price} cents/kWh</span>
                      </div>
                    )}
                    {'count' in data && (
                      <div>
                        <span className="font-medium text-gray-700">Count:</span>
                        <span className="ml-2">{data.count}</span>
                      </div>
                    )}
                    {'total_capacity_mw' in data && (
                      <div>
                        <span className="font-medium text-gray-700">Total Capacity:</span>
                        <span className="ml-2">{data.total_capacity_mw} MW</span>
                      </div>
                    )}
                    {'census_blocks' in data && (
                      <div>
                        <span className="font-medium text-gray-700">Census Blocks:</span>
                        <span className="ml-2">{data.census_blocks.length}</span>
                      </div>
                    )}
                    {'total_sites' in data && (
                      <div>
                        <span className="font-medium text-gray-700">Total Sites:</span>
                        <span className="ml-2">{data.total_sites}</span>
                      </div>
                    )}
                    {'total_features' in data && (
                      <div>
                        <span className="font-medium text-gray-700">Total Features:</span>
                        <span className="ml-2">{data.total_features}</span>
                      </div>
                    )}
                  </div>
                </div>
                
                <div className="border-t border-gray-200 pt-4">
                  <h3 className="text-md font-medium text-gray-900 mb-2">Full Response Data</h3>
                  <pre className="bg-gray-900 text-green-400 p-4 rounded-lg overflow-auto text-sm font-mono whitespace-pre-wrap max-h-96">
                    {JSON.stringify(data, null, 2)}
                  </pre>
                </div>
              </div>
            </div>
          )}

          {/* Empty State */}
          {!data && !error && !isLoading && (
            <div className="text-center text-gray-500 mt-12">
              <div className="text-6xl mb-4">🔧</div>
              <h3 className="text-lg font-medium text-gray-900 mb-2">Ready to Test</h3>
              <p>Enter a city name and select an API to see raw data output</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
