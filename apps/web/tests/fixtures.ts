import { test as base, expect, type BrowserContext } from '@playwright/test';
const allowedPorts = new Set(['24173', '24174', '24180']);

// The optional remote browser runs on an internal container network. Forward only
// assigned local application surfaces; the browser receives no host mounts or
// unrestricted network proxy. This fixture is never loaded by the application.
export async function attachLocalSurfaces(context: BrowserContext) {
  if (!process.env.CLOSEGRAPH_BROWSER_WS_ENDPOINT) return;
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !allowedPorts.has(url.port) || url.username || url.password) {
      await route.abort('blockedbyclient');
      return;
    }
    try {
      const headers = await request.allHeaders();
      delete headers.host;
      delete headers['content-length'];
      const response = await fetch(url.href, {
        method: request.method(),
        headers,
        body: ['GET', 'HEAD'].includes(request.method()) ? undefined : request.postDataBuffer(),
        redirect: 'manual',
        signal: AbortSignal.timeout(45000),
      });
      const body = Buffer.from(await response.arrayBuffer());
      const resultHeaders = Object.fromEntries(response.headers.entries());
      delete resultHeaders['transfer-encoding'];
      delete resultHeaders['content-encoding'];
      delete resultHeaders['content-length'];
      await route.fulfill({ status: response.status, headers: resultHeaders, body });
    } catch {
      await route.abort('failed');
    }
  });
}
export const test = base.extend({
  context: async ({ context }, use) => {
    await attachLocalSurfaces(context);
    await use(context);
  },
});
export { expect };
