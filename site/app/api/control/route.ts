const runtimeBase = (process.env.AGENT_API_URL ?? 'http://127.0.0.1:8787').replace(/\/$/, '');
const runtimeToken = process.env.AGENT_API_TOKEN;
const ownerToken = process.env.OWNER_CONTROL_TOKEN;

function authorized(request: Request) {
  const supplied = request.headers.get('Authorization') ?? '';
  return Boolean(ownerToken) && supplied === `Bearer ${ownerToken}`;
}

async function proxy(path: string, init?: RequestInit) {
  const response = await fetch(`${runtimeBase}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(runtimeToken ? { Authorization: `Bearer ${runtimeToken}` } : {}),
    },
    cache: 'no-store',
    signal: AbortSignal.timeout(45_000),
  });
  const payload = await response.json();
  return Response.json(payload, { status: response.status, headers: { 'Cache-Control': 'no-store' } });
}

export async function GET(request: Request) {
  if (!authorized(request)) return Response.json({ error: 'Owner authorization required.' }, { status: 401 });
  return proxy('/api/control');
}

export async function POST(request: Request) {
  if (!authorized(request)) return Response.json({ error: 'Owner authorization required.' }, { status: 401 });
  const body = await request.text();
  if (body.length > 4096) return Response.json({ error: 'Control payload is too large.' }, { status: 413 });
  return proxy('/api/control', { method: 'POST', body });
}
