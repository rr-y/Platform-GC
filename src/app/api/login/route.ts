// app/api/login/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const users = {
  admin: { password: 'admin123', role: 'admin' },
  staff: { password: 'staff123', role: 'staff' }
};

export async function POST(req: NextRequest) {
  const { username, password } = await req.json();

  const user = users[username as keyof typeof users];
  if (!user || user.password !== password) {
    return new NextResponse('Unauthorized', { status: 401 });
  }

  // Set cookie for role
  cookies().set('role', user.role, {
    httpOnly: true,
    path: '/',
    maxAge: 60 * 60 * 6 // 6 hours
  });

  return new NextResponse(user.role);
}
