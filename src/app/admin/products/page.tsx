'use client';
import { useEffect, useState } from "react";

type Product = { name: string; sku: string; price: number; stock: number; shop: "amul"|"restaurant"|"library" };

export default function ProductsAdmin() {
  const [rows, setRows] = useState<Product[]>([]);
  const [form, setForm] = useState<Product>({ name:"", sku:"", price:0, stock:0, shop:"amul" });

  // load once
  useEffect(() => {
    (async () => {
      const res = await fetch("/api/products", { cache: "no-store" });
      setRows(await res.json());
    })();
  }, []);

  async function addProduct(e: React.FormEvent) {
    e.preventDefault();
    // optimistic update (feels instant)
    setRows(prev => [form, ...prev]);
    await fetch("/api/products", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
    setForm({ name:"", sku:"", price:0, stock:0, shop:"amul" });
  }

  return (
    <main className="max-w-5xl mx-auto p-4 space-y-4">
      <h1 className="text-xl font-semibold">Products (API-backed)</h1>

      <form onSubmit={addProduct} className="grid gap-3 md:grid-cols-6 bg-white p-4 rounded-xl border">
        <input className="input md:col-span-2" placeholder="Name" value={form.name} onChange={e=>setForm({...form, name:e.target.value})}/>
        <input className="input" placeholder="SKU" value={form.sku} onChange={e=>setForm({...form, sku:e.target.value})}/>
        <input className="input" type="number" step="0.01" placeholder="Price" value={form.price} onChange={e=>setForm({...form, price:+e.target.value})}/>
        <input className="input" type="number" placeholder="Stock" value={form.stock} onChange={e=>setForm({...form, stock:+e.target.value})}/>
        <select className="input" value={form.shop} onChange={e=>setForm({...form, shop:e.target.value as Product["shop"]})}>
          <option value="amul">Amul</option>
          <option value="restaurant">Restaurant</option>
          <option value="library">Library</option>
        </select>
        <button className="btn md:col-span-6">Add</button>
      </form>

      <div className="bg-white rounded-xl border overflow-x-auto">
        <table className="table min-w-full text-sm">
          <thead><tr>
            <th className="th">Name</th><th className="th">SKU</th><th className="th">Shop</th>
            <th className="th text-right">Price (₹)</th><th className="th text-right">Stock</th>
          </tr></thead>
          <tbody>
            {rows.map((p,i)=>(
              <tr key={i} className="border-t">
                <td className="td">{p.name}</td>
                <td className="td">{p.sku}</td>
                <td className="td capitalize">{p.shop}</td>
                <td className="td text-right">{p.price.toFixed(2)}</td>
                <td className="td text-right">{p.stock}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
