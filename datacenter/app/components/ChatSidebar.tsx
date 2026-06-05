'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import MarkdownContent from './MarkdownContent';
import type { SiteCandidate } from '../../lib/api-client';

export interface ChatMapContext {
  mapCandidates?: SiteCandidate[];
  pinnedSites?: SiteCandidate[];
  selectedSite?: SiteCandidate | null;
  searchSummary?: string;
}

interface ChatSidebarProps {
  isOpen: boolean;
  onClose: () => void;
  mapContext?: ChatMapContext;
  initialPrompt?: string;
  onSitesFound?: (candidates: SiteCandidate[]) => void;
  onMapMove?: (center: { lat: number; lon: number }) => void;
  pinnedSites?: SiteCandidate[];
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
  memo?: string;
}

export default function ChatSidebar({
  isOpen,
  onClose,
  mapContext,
  initialPrompt,
  onSitesFound,
  onMapMove,
  pinnedSites = [],
}: ChatSidebarProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [lastMemo, setLastMemo] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const seededRef = useRef(false);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  useEffect(() => {
    if (isOpen && initialPrompt && !seededRef.current) {
      setInput(initialPrompt);
      seededRef.current = true;
    }
    if (!isOpen) seededRef.current = false;
  }, [isOpen, initialPrompt]);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || isLoading) return;

      const userMessage: Message = { role: 'user', content: text.trim() };
      setMessages((prev) => [...prev, userMessage]);
      setInput('');
      setIsLoading(true);

      try {
        const history = messages.map((m) => ({ role: m.role, content: m.content }));

        const response = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: text.trim(),
            history,
            context: {
              mapCandidates: mapContext?.mapCandidates?.slice(0, 12),
              pinnedSites: mapContext?.pinnedSites?.slice(0, 4),
              selectedSite: mapContext?.selectedSite ?? null,
              searchSummary: mapContext?.searchSummary,
            },
          }),
        });

        const raw = await response.text();
        let data: { error?: string; response?: string; memo?: string; candidates?: SiteCandidate[]; center?: { lat: number; lon: number } } = {};
        try {
          data = raw ? JSON.parse(raw) : {};
        } catch {
          throw new Error(raw?.slice(0, 200) || `Chat failed (${response.status})`);
        }

        if (!response.ok) {
          throw new Error(data.error || `Chat failed (${response.status})`);
        }
        if (data.error) throw new Error(data.error);

        const assistantMessage: Message = {
          role: 'assistant',
          content: data.response || 'No response received',
          memo: data.memo,
        };
        setMessages((prev) => [...prev, assistantMessage]);

        if (data.memo) setLastMemo(data.memo);
        if (data.candidates && onSitesFound) onSitesFound(data.candidates);
        if (data.center && onMapMove) onMapMove(data.center);
      } catch (error) {
        console.error('Chat error:', error);
        const msg = error instanceof Error ? error.message : 'Unknown error';
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content:
              msg.includes('Missing OPENAI_API_KEY')
                ? 'Chat is unavailable: OPENAI_API_KEY is not set in datacenter/.env'
                : msg.includes('Chat failed (500)') || msg === 'Internal Server Error'
                  ? 'Chat server error — try restarting `npm run dev` (stale .next cache). Delete `.next` and restart if it persists.'
                  : `Sorry, chat failed: ${msg}`,
          },
        ]);
      } finally {
        setIsLoading(false);
      }
    },
    [isLoading, messages, mapContext, onSitesFound, onMapMove]
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendMessage(input);
  };

  const generateMemo = async () => {
    const sites = pinnedSites.length >= 2 ? pinnedSites : mapContext?.mapCandidates?.slice(0, 4) ?? [];
    if (sites.length < 2) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: 'Pin at least 2 sites on the map (or run a search) before generating a memo.',
        },
      ]);
      return;
    }
    setIsLoading(true);
    try {
      const res = await fetch('/api/generate-memo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sites: sites.slice(0, 4) }),
      });
      const data = await res.json();
      if (data.memo) {
        setLastMemo(data.memo);
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: 'Generated IC memo:', memo: data.memo },
        ]);
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Failed to generate memo.' },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const downloadMemo = () => {
    if (!lastMemo) return;
    const blob = new Blob([lastMemo], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'site-selection-memo.md';
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!isOpen) return null;

  const contextHint = mapContext?.mapCandidates?.length
    ? `${mapContext.mapCandidates.length} sites on map`
    : null;

  return (
    <div className="fixed right-0 top-0 h-full w-96 bg-white border-l border-gray-200 shadow-xl z-50 flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-gray-200 bg-gray-50">
        <div>
          <h3 className="font-semibold text-gray-900">Site Assistant</h3>
          <p className="text-xs text-gray-500 mt-1">
            {contextHint ? `${contextHint} · ask about site numbers` : 'Ask questions — results sync to map'}
          </p>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1 rounded-md hover:bg-gray-200">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {(pinnedSites.length > 0 || mapContext?.selectedSite) && (
        <div className="px-4 py-2 border-b bg-blue-50 text-xs space-y-1">
          {mapContext?.selectedSite && (
            <p className="text-blue-800">
              Selected: {mapContext.selectedSite.coordinates.lat.toFixed(4)},{' '}
              {mapContext.selectedSite.coordinates.lon.toFixed(4)} (
              {Math.round(mapContext.selectedSite.overall_score * 100)}/100)
            </p>
          )}
          {pinnedSites.length > 0 && (
            <p className="text-blue-700">{pinnedSites.length} pinned for compare/memo</p>
          )}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-gray-500 py-8">
            <div className="text-4xl mb-4">🗺️</div>
            <p className="text-sm">Draw a box or ask for sites near a city.</p>
            <p className="text-xs mt-2 text-gray-400">
              Try: &quot;Compare site 1 and 3 on power vs water&quot; or &quot;What if I prioritize fiber?&quot;
            </p>
          </div>
        )}

        {messages.map((message, index) => (
          <div key={index} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] px-4 py-3 rounded-lg ${
                message.role === 'user' ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-900 border'
              }`}
            >
              {message.role === 'assistant' ? (
                <div className="space-y-1">
                  {message.memo && message.content !== message.memo && (
                    <p className="text-xs text-gray-500 mb-2">{message.content}</p>
                  )}
                  <MarkdownContent content={message.memo ?? message.content} />
                </div>
              ) : (
                <MarkdownContent content={message.content} invert />
              )}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 border max-w-sm px-4 py-3 rounded-lg">
              <span className="text-xs text-gray-500">Analyzing…</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="border-t border-gray-200 p-4 bg-gray-50 space-y-2">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={generateMemo}
            disabled={isLoading}
            className="flex-1 px-2 py-1.5 text-xs bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            IC memo
          </button>
          {lastMemo && (
            <button
              type="button"
              onClick={downloadMemo}
              className="px-2 py-1.5 text-xs border border-gray-300 rounded hover:bg-gray-100"
            >
              Download .md
            </button>
          )}
        </div>
        <form onSubmit={handleSubmit} className="space-y-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Compare top sites, check deal-breakers, reweight priorities…"
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm text-black resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={3}
            disabled={isLoading}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e);
              }
            }}
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="w-full px-4 py-2 bg-blue-500 text-white rounded-md text-sm hover:bg-blue-600 disabled:opacity-50"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
