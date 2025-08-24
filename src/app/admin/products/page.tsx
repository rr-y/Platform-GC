'use client';
import { useEffect, useState } from "react";


type Product = { name: string; sku: string; price: number; stock: number; shop: "amul"|"restaurant"|"library" };



export default function ProductsAdmin() {
  const [rows, setRows] = useState<Product[]>([]);
  const [form, setForm] = useState<Product>({ name:"", sku:"", price:0, stock:0, shop:"amul" });
  const [editIndex, setEditIndex] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<Partial<Product>>({});

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

  async function deleteProduct(sku: string) {
    setRows(prev => prev.filter(p => p.sku !== sku)); // optimistic
    await fetch(`/api/products?sku=${sku}`, { method: "DELETE" });
  }

  function startEdit(index: number, row: Product) {
    setEditIndex(index);
    setEditForm({ ...row });
  }
  function cancelEdit() {
    setEditIndex(null);
    setEditForm({});
  }
  async function saveEdit() {
    if (!editForm.sku) return;
    const res = await fetch("/api/products", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(editForm)
    });
    if (res.ok) {
      setRows(prev => prev.map((p,i) => i === editIndex ? { ...p, ...editForm } as Product : p));
      cancelEdit();
    }
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
            <th className="th">Name</th><th className="th">SKU
            </th><th className="th">Shop</th>
            <th className="th text-right">Price (₹)</th>
            <th className="th text-right">Stock</th>
            <th className="th text-right">Actions</th>
          </tr></thead>
          <tbody>
            {rows.map((p,i)=>(
              <tr key={i}>
                {editIndex === i ? (
                  <>
                    <td className="td"><input className="input" value={editForm.name} onChange={e=>setEditForm(f=>({...f, name:e.target.value}))} /></td>
                    <td className="td"><input className="input" value={editForm.sku} disabled /></td>
                    <td className="td"><select className="input" value={editForm.shop} onChange={e=>setEditForm(f=>({...f, shop:e.target.value as Product["shop"]}))}>
                      <option value="amul">Amul</option>
                      <option value="restaurant">Restaurant</option>
                      <option value="library">Library</option>
                    </select></td>
                    <td className="td text-right"><input type="number" className="input" value={editForm.price} onChange={e=>setEditForm(f=>({...f, price:+e.target.value}))} /></td>
                    <td className="td text-right"><input type="number" className="input" value={editForm.stock} onChange={e=>setEditForm(f=>({...f, stock:+e.target.value}))} /></td>
                    <td className="td text-right space-x-2">
                      <button onClick={saveEdit} className="text-green-600 hover:underline text-xs">Save</button>
                      <button onClick={cancelEdit} className="text-gray-500 hover:underline text-xs">Cancel</button>
                    </td>
                  </>
                ) : (
                  <>
                    <td className="td">{p.name}</td>
                    <td className="td">{p.sku}</td>
                    <td className="td capitalize">{p.shop}</td>
                    <td className="td text-right">{p.price.toFixed(2)}</td>
                    <td className="td text-right">{p.stock}</td>
                    <td className="td text-right space-x-2">
                      <button onClick={() => startEdit(i, p)} className="text-blue-600 hover:underline text-xs">Edit</button>
                      <button onClick={() => deleteProduct(p.sku)} className="text-red-600 hover:underline text-xs">Delete</button>
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
