import { NextRequest, NextResponse } from 'next/server';
import { getOpenAI } from '../../../lib/openai';
import type { SiteCandidate } from '../../../lib/api-client';

export async function POST(request: NextRequest) {
  try {
    const { sites, focus } = (await request.json()) as {
      sites?: SiteCandidate[];
      focus?: string;
    };

    if (!sites?.length) {
      return NextResponse.json({ error: 'At least one site required' }, { status: 400 });
    }

    const payload = sites.slice(0, 4).map((c, i) => ({
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
            'Write an IC-style datacenter site selection memo in markdown: Executive Summary, Site Comparison table, Risks, Recommendation. Be concise and data-driven.',
        },
        {
          role: 'user',
          content: `Sites:\n${JSON.stringify(payload, null, 2)}\n${focus ? `\nFocus: ${focus}` : ''}`,
        },
      ],
      max_tokens: 1200,
    });

    return NextResponse.json({ memo: completion.choices[0].message.content ?? '' });
  } catch (error) {
    console.error('generate-memo error:', error);
    return NextResponse.json({ error: 'Failed to generate memo' }, { status: 500 });
  }
}
