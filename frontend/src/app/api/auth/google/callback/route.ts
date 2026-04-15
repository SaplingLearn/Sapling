export const dynamic = 'force-static';

export async function GET() {
  return new Response('Static export build: Google auth callback is handled by the backend redirect.', {
    status: 410,
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
    },
  });
}
