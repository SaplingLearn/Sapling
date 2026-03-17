import fs from 'fs';
import path from 'path';

const SRC = path.resolve(__dirname, '../../src');

function readSrc(rel: string) {
  return fs.readFileSync(path.join(SRC, rel), 'utf8');
}

describe('Navbar auth guard', () => {
  const src = readSrc('components/Navbar.tsx');

  test('reads userReady from useUser', () => {
    expect(src).toMatch(/useUser\(\)/);
    expect(src).toMatch(/userReady/);
  });

  test('gates signin redirect on userReady', () => {
    // Redirect must wait until localStorage hydration has completed.
    expect(src).toMatch(/if\s*\(\s*userReady\s*&&\s*!isAuthenticated/);
  });
});

describe('Learn page prefill wiring', () => {
  const src = readSrc('app/learn/page.tsx');

  test('passes prefillInput prop to ChatPanel', () => {
    expect(src).toMatch(/<ChatPanel[\s\S]*prefillInput=/);
  });
});
