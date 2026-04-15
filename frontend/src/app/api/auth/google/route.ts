import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:5000';

export async function GET() {
  return NextResponse.redirect(`${BACKEND_URL}/api/auth/google`);
}
