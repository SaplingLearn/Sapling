import { NextResponse } from 'next/server';

export const dynamic = 'force-static';

export async function GET() {
  return NextResponse.redirect('/?error=auth_callback_not_supported');
}
