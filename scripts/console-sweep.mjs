/**
 * Console-error sweep across every signed-in route (testathon hardening).
 *
 * The rubric awards a point per "runtime error in the console", so this walks
 * the app the way a tester would — sign in, visit each route, record anything
 * the console or an unhandled rejection produces. Run against the dev stack:
 *
 *   node e2e-console-sweep.mjs
 */
import { chromium } from 'playwright';

const FRONTEND = process.env.SWEEP_FRONTEND || 'http://localhost:3000';
const BACKEND = process.env.SWEEP_BACKEND || 'http://127.0.0.1:5000';
const USER = process.env.SWEEP_USER || 'rich-user-active';

const ROUTES = [
  '/dashboard', '/learn', '/quiz', '/study', '/tree', '/flashcards',
  '/library', '/calendar', '/social', '/settings', '/achievements',
  '/gradebook', '/course-planner', '/notetaker', `/profile/${USER}`,
];

// Noise that is not a product defect: dev-server plumbing and the HMR socket.
const IGNORE = [
  /Download the React DevTools/i,
  /\[Fast Refresh\]/i,
  /webpack-hmr|_next\/static\/chunks\/.*hot-update/i,
  /Warning: ReactDOM.render is no longer supported/i,
];

const findings = [];

function record(route, kind, text) {
  if (!text) return;
  if (IGNORE.some((re) => re.test(text))) return;
  findings.push({ route, kind, text: text.slice(0, 300) });
}

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });

// Sign in the way the app does: mint a session against the local backend and
// hand the cookie to the browser.
const res = await fetch(`${BACKEND}/api/auth/test-login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ user_id: USER }),
});
const setCookie = res.headers.getSetCookie?.() ?? [];
const token = setCookie
  .find((c) => c.startsWith('sapling_session='))
  ?.split(';')[0]
  .split('=')[1];
if (!token) {
  console.error('could not mint a session — is the backend up on', BACKEND, '?');
  process.exit(2);
}
await ctx.addCookies([
  { name: 'sapling_session', value: token, domain: 'localhost', path: '/' },
]);

const page = await ctx.newPage();
let current = '(startup)';
page.on('console', (m) => {
  if (m.type() === 'error' || m.type() === 'warning') record(current, m.type(), m.text());
});
page.on('pageerror', (e) => record(current, 'pageerror', String(e)));
page.on('requestfailed', (r) => {
  const f = r.failure();
  if (f && !/ERR_ABORTED/.test(f.errorText)) {
    record(current, 'requestfailed', `${r.method()} ${r.url()} — ${f.errorText}`);
  }
});
page.on('response', (r) => {
  if (r.status() >= 500) record(current, 'http5xx', `${r.status()} ${r.request().method()} ${r.url()}`);
});

for (const route of ROUTES) {
  current = route;
  process.stdout.write(`visiting ${route} ... `);
  try {
    await page.goto(FRONTEND + route, { waitUntil: 'networkidle', timeout: 45000 });
    await page.waitForTimeout(2500);
    const title = await page.title();
    const bodyLen = (await page.locator('body').innerText().catch(() => '')).length;
    // A near-empty body behind an error boundary is the "blank screen" the
    // rubric scores at 5 points.
    if (bodyLen < 40) record(route, 'blank-page', `body text is ${bodyLen} chars (title=${title})`);
    console.log(`ok (body ${bodyLen} chars)`);
  } catch (e) {
    console.log('NAV FAILED');
    record(route, 'navigation', String(e).slice(0, 200));
  }
}

await browser.close();

console.log('\n' + '='.repeat(66));
if (!findings.length) {
  console.log('No console errors, 5xx responses or blank pages across', ROUTES.length, 'routes.');
} else {
  const byRoute = {};
  for (const f of findings) (byRoute[f.route] ||= []).push(f);
  console.log(`${findings.length} finding(s) across ${Object.keys(byRoute).length} route(s):\n`);
  for (const [route, items] of Object.entries(byRoute)) {
    console.log(`--- ${route} ---`);
    const seen = new Set();
    for (const i of items) {
      const key = i.kind + i.text.slice(0, 120);
      if (seen.has(key)) continue;
      seen.add(key);
      console.log(`  [${i.kind}] ${i.text}`);
    }
  }
}
