import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:5000';

export const dynamic = 'force-static';

export async function GET() {
  return NextResponse.redirect(`${BACKEND_URL}/api/auth/google`);
}
