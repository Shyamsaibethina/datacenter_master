import { NextRequest, NextResponse } from 'next/server';
import { getOpenAI } from '../../../lib/openai';

// Generates a short, on-demand narrative explaining why a candidate site scored
// the way it did. Called lazily when the user clicks a marker (not for every
// candidate up front), so it stays cheap.
export async function POST(request: NextRequest) {
  try {
    const site = await request.json();

    if (!site || typeof site.overall_score !== 'number') {
      return NextResponse.json({ error: 'Invalid site payload' }, { status: 400 });
    }

    const pct = Math.round(site.overall_score * 100);
    const subscores = Object.entries(site.subscores ?? {})
      .map(([k, v]) => `${k}: ${Math.round((v as number) * 100)}/100`)
      .join(', ');
    const reasons = Array.isArray(site.reasons) ? site.reasons.join('; ') : '';
    const coords = site.coordinates
      ? `${site.coordinates.lat?.toFixed?.(4)}, ${site.coordinates.lon?.toFixed?.(4)}`
      : 'unknown';

    const completion = await getOpenAI().chat.completions.create({
      model: 'gpt-4o-mini',
      messages: [
        {
          role: 'system',
          content:
            'You are a datacenter siting expert. In 2-3 sentences, explain plainly why a candidate location is or is not a good datacenter site, based on the provided scores and factors. Be specific and balanced (mention the strongest factor and the biggest risk). No preamble, no bullet points.',
        },
        {
          role: 'user',
          content: `Site at ${coords} scored ${pct}/100 overall. Subscores: ${subscores}. Factors: ${reasons}.`,
        },
      ],
      max_tokens: 180,
    });

    return NextResponse.json({ explanation: completion.choices[0].message.content });
  } catch (error) {
    console.error('explain-site error:', error);
    return NextResponse.json({ error: 'Failed to generate explanation' }, { status: 500 });
  }
}
