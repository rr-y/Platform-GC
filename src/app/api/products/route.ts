
import { NextResponse } from "next/server";

type Product = { name: string; sku: string; price: number; stock: number; shop: "amul"|"restaurant"|"library" };

const store: Product[] = [
  { name: "Amul Butter 500g", sku: "AM-500B", price: 280, stock: 12, shop: "amul" },
  { name: "Amul Ghee 500g", sku: "AM-501B", price: 280, stock: 12, shop: "amul" }
];



export async function GET() {
  return NextResponse.json(store);
}

export async function POST(req: Request) {
  const data = (await req.json()) as Product;
  if (!data?.name || !data?.sku) return NextResponse.json({ error: "bad input" }, { status: 400 });
  store.unshift(data);
  return NextResponse.json({ ok: true });
}


export async function DELETE(req: Request) {
  const { searchParams } = new URL(req.url);
  const sku = searchParams.get("sku");
  if (!sku) return NextResponse.json({ error: "Missing SKU" }, { status: 400 });

  const index = store.findIndex(p => p.sku === sku);
  if (index === -1) return NextResponse.json({ error: "Not found" }, { status: 404 });

  store.splice(index, 1);
  return NextResponse.json({ ok: true });
}


export async function PATCH(req: Request) {
  const body = await req.json();
  const { sku, ...rest } = body;

  if (!sku) return NextResponse.json({ error: "Missing SKU" }, { status: 400 });

  const index = store.findIndex(p => p.sku === sku);
  if (index === -1) return NextResponse.json({ error: "Not found" }, { status: 404 });

  store[index] = { ...store[index], ...rest };
  return NextResponse.json({ ok: true });
}


