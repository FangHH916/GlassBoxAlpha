const runtimeBase = (process.env.AGENT_API_URL ?? 'http://127.0.0.1:8787').replace(/\/$/, '');

function outputText(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object') return null;
  const response = payload as { output_text?: unknown; output?: unknown };
  if (typeof response.output_text === 'string') return response.output_text;
  if (!Array.isArray(response.output)) return null;
  for (const item of response.output) {
    if (!item || typeof item !== 'object') continue;
    const content = (item as { content?: unknown }).content;
    if (!Array.isArray(content)) continue;
    for (const part of content) {
      if (part && typeof part === 'object' && typeof (part as { text?: unknown }).text === 'string') return (part as { text: string }).text;
    }
  }
  return null;
}

export async function POST(request: Request) {
  let question = '';
  try {
    const body = await request.json() as { question?: string };
    question = String(body.question ?? '').trim().slice(0, 500);
  } catch {
    return Response.json({ error: 'Invalid JSON body.' }, { status: 400 });
  }
  if (!question) return Response.json({ error: 'Question is required.' }, { status: 400 });

  const apiKey = process.env.DEEPSEEK_API_KEY;
  if (!apiKey) return Response.json({ error: 'DeepSeek is not configured. No fallback response was generated.' }, { status: 503 });

  try {
    const dashboardResponse = await fetch(`${runtimeBase}/api/dashboard`, { cache: 'no-store', signal: AbortSignal.timeout(8_000) });
    if (!dashboardResponse.ok) throw new Error('Python Agent is unavailable.');
    const dashboard = await dashboardResponse.json() as { settings?: { mode?: string; ai_provider?: string; ai_model?: string }; recent?: unknown[] };
    if (dashboard.settings?.mode !== 'alpaca') throw new Error('Python Agent is not connected to Alpaca.');
    if (dashboard.settings?.ai_provider !== 'DeepSeek') throw new Error('Python Agent is not running with DeepSeek enabled.');
    const latest = dashboard.recent?.[0];
    if (!latest) throw new Error('Run the Agent at least once before asking about a decision.');

    const model = process.env.AI_MODEL ?? dashboard.settings.ai_model ?? 'deepseek-v4-flash';
    const response = await fetch('https://api.deepseek.com/responses', {
      method: 'POST',
      headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model,
        store: false,
        max_output_tokens: 260,
        instructions: 'You are GlassBox Analyst. Answer only from the supplied real Python Agent audit record. Be concise. Never invent prices, account values, orders, fills, or evidence. Never give investment advice. State when the evidence cannot answer. You have no order tool and cannot modify the candidate.',
        input: `Latest immutable Agent audit record:\n${JSON.stringify(latest)}\n\nUser question: ${question}`,
      }),
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) throw new Error(`DeepSeek returned ${response.status}.`);
    const answer = outputText(await response.json());
    if (!answer) throw new Error('DeepSeek returned no answer.');
    return Response.json({ answer: answer.slice(0, 1500), model, grounded_run: (latest as { run_id?: string }).run_id });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : 'Agent chat failed.' }, { status: 503 });
  }
}
