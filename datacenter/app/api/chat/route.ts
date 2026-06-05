import { NextRequest, NextResponse } from 'next/server';
import OpenAI from 'openai';
import { getOpenAI } from '../../../lib/openai';
import {
  AVAILABLE_TOOLS,
  buildSystemPrompt,
  executeTool,
  type ChatMapContext,
} from '../../../lib/chat-tools';
import type { SiteCandidate } from '../../../lib/api-client';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const message = body.message as string | undefined;
    const history = (body.history ?? []) as ChatMessage[];
    const context = (body.context ?? {}) as ChatMapContext;

    if (!message || typeof message !== 'string') {
      return NextResponse.json({ error: 'Message is required' }, { status: 400 });
    }

    const messages: OpenAI.Chat.Completions.ChatCompletionMessageParam[] = [
      { role: 'system', content: buildSystemPrompt(context) },
      ...history.map((m) => ({ role: m.role, content: m.content })),
      { role: 'user', content: message },
    ];

    const MAX_TOOL_ROUNDS = 8;
    let mapCandidates: SiteCandidate[] | null = null;
    let mapCenter: { lat: number; lon: number } | null = null;
    let memo: string | null = null;
    const toolMemory: { tool: string; summary: string }[] = [];

    for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
      const completion = await getOpenAI().chat.completions.create({
        model: 'gpt-4o-mini',
        messages,
        tools: AVAILABLE_TOOLS,
        tool_choice: 'auto',
      });

      const responseMessage = completion.choices[0].message;
      messages.push(responseMessage);

      const toolCalls = responseMessage.tool_calls ?? [];
      if (toolCalls.length === 0) {
        return NextResponse.json({
          response: responseMessage.content,
          ...(mapCandidates && { candidates: mapCandidates }),
          ...(mapCenter && { center: mapCenter }),
          ...(memo && { memo }),
          toolMemory,
        });
      }

      for (const toolCall of toolCalls) {
        if (toolCall.type !== 'function') continue;
        const functionName = toolCall.function.name;
        let functionArgs: Record<string, unknown> = {};
        try {
          functionArgs = JSON.parse(toolCall.function.arguments || '{}');
        } catch {
          functionArgs = {};
        }

        const { result, mapCandidates: mc, mapCenter: center, memo: m } = await executeTool(
          functionName,
          functionArgs,
          context
        );

        if (mc) mapCandidates = mc;
        if (center) mapCenter = center;
        if (m) memo = m;

        toolMemory.push({
          tool: functionName,
          summary: JSON.stringify(result).slice(0, 500),
        });
        if (toolMemory.length > 10) toolMemory.shift();

        messages.push({
          tool_call_id: toolCall.id,
          role: 'tool',
          content: JSON.stringify(result),
        });
      }
    }

    const finalCompletion = await getOpenAI().chat.completions.create({
      model: 'gpt-4o-mini',
      messages,
    });

    return NextResponse.json({
      response: finalCompletion.choices[0].message.content,
      ...(mapCandidates && { candidates: mapCandidates }),
      ...(mapCenter && { center: mapCenter }),
      ...(memo && { memo }),
      toolMemory,
    });
  } catch (error) {
    console.error('Chat API error:', error);
    const message =
      error instanceof Error ? error.message : 'Internal server error';
    const status =
      message.includes('Missing OPENAI_API_KEY') ? 503 : 500;
    return NextResponse.json({ error: message }, { status });
  }
}
