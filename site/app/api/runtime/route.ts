const runtimeBase = (process.env.AGENT_API_URL ?? 'http://127.0.0.1:8787').replace(/\/$/, '');
const runtimeToken = process.env.AGENT_API_TOKEN;

async function runtimeRequest(path: string, init?: RequestInit, timeoutMs = 10_000) {
  const response = await fetch(`${runtimeBase}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(runtimeToken ? { Authorization: `Bearer ${runtimeToken}` } : {}),
      ...(init?.headers ?? {}),
    },
    cache: 'no-store',
    signal: AbortSignal.timeout(timeoutMs),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload?.error || `Python Agent returned ${response.status}`);
  return payload;
}

export async function GET() {
  try {
    const dashboard = await runtimeRequest('/api/dashboard', undefined, 45_000);
    if (dashboard?.settings?.mode !== 'alpaca') {
      return Response.json({
        error: 'ALPACA_NOT_CONFIGURED',
        detail: 'Python Agent is reachable but BROKER_MODE is not alpaca. Demo data is intentionally hidden.',
        connected: false,
      }, { status: 503, headers: { 'Cache-Control': 'no-store' } });
    }
    if (dashboard?.account?.error) {
      return Response.json({
        error: 'ALPACA_ACCOUNT_UNAVAILABLE',
        detail: String(dashboard.account.error).slice(0, 300),
        connected: false,
      }, { status: 503, headers: { 'Cache-Control': 'no-store' } });
    }
    return Response.json({ ...dashboard, connected: true, fetched_at: new Date().toISOString() }, { headers: { 'Cache-Control': 'no-store' } });
  } catch {
    return Response.json({
      error: 'PYTHON_AGENT_DISCONNECTED',
      detail: 'Python Agent is not reachable at the configured AGENT_API_URL.',
      connected: false,
    }, { status: 503, headers: { 'Cache-Control': 'no-store' } });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json() as { symbol?: string };
    const symbol = String(body.symbol ?? '').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 8);
    if (!symbol) return Response.json({ error: 'A symbol is required.' }, { status: 400 });
    const dashboard = await runtimeRequest('/api/dashboard');
    if (dashboard?.settings?.mode !== 'alpaca') return Response.json({ error: 'BROKER_MODE must be alpaca. Demo cycles are not exposed as live data.' }, { status: 503 });
    const report = await runtimeRequest('/api/cycle', { method: 'POST', body: JSON.stringify({ symbol }) });
    return Response.json(report, { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : 'Agent cycle failed' }, { status: 503 });
  }
}
