export const dynamic = 'force-static';

export async function GET() {
  return new Response('Static export build: use the frontend Google sign-in button instead.', {
    status: 410,
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
    },
  });
}
