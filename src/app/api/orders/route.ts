import { NextResponse } from "next/server";

type OrderItem = { name: string; sku: string; quantity: number; price: number };
type Order = {
  id: string;
  items: OrderItem[];
  total: number;
  createdAt: string;
};

const orders: Order[] = [];

export async function GET() {
  return NextResponse.json(orders);
}

export async function POST(req: Request) {
  const data = await req.json();
  if (!Array.isArray(data) || data.length === 0) {
    return NextResponse.json({ error: "Invalid order" }, { status: 400 });
  }

  const total = data.reduce((sum: number, item: OrderItem) => sum + item.price * item.quantity, 0);

  const newOrder: Order = {
    id: crypto.randomUUID(),
    items: data,
    total,
    createdAt: new Date().toISOString(),
  };

  orders.unshift(newOrder);
  return NextResponse.json({ ok: true });
}
