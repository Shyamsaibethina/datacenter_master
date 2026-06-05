'use client';

export default function DataViewer() {
  return (
    <div className="max-w-4xl mx-auto min-h-screen bg-white flex items-center justify-center">
      <div className="text-center">
        <div className="text-6xl mb-6">🤖</div>
        <h1 className="text-3xl font-bold text-gray-900 mb-4">AI-Powered Analysis</h1>
        <p className="text-lg text-gray-600 mb-6">
          The DataViewer has been upgraded! Use the <strong>Chat Interface</strong> for intelligent, 
          AI-powered datacenter site analysis.
        </p>
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6 text-left max-w-md mx-auto">
          <h3 className="font-semibold text-blue-900 mb-2">New Features:</h3>
          <ul className="text-sm text-blue-800 space-y-1">
            <li>• Natural language queries</li>
            <li>• Intelligent function calling</li>
            <li>• Comprehensive site analysis</li>
            <li>• Type-safe API responses</li>
            <li>• Real-time data integration</li>
          </ul>
        </div>
        <p className="text-sm text-gray-500 mt-6">
          Try asking: "Analyze Austin, TX for a datacenter location"
        </p>
      </div>
    </div>
  );
}