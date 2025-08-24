
import { NextResponse } from "next/server";

type Product = { name: string; sku: string; price: number; stock: number; shop: "amul"|"restaurant"|"library" };

const store: Product[] = [
  { name: "Amul Butter 500g", sku: "AM-500B", price: 280, stock: 12, shop: "amul" },
  { name: "Amul Butter 500g", sku: "AM-500B", price: 280, stock: 12, shop: "amul" },
  { name: "Amul Butter 500g", sku: "AM-500B", price: 280, stock: 12, shop: "amul" },
  { name: "Amul Butter 500g", sku: "AM-500B", price: 280, stock: 12, shop: "amul" },
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