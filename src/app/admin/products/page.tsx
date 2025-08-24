'use client';

import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";

const ProductSchema = z.object({
  name: z.string().min(2),
  sku: z.string().min(1),
  price: z.coerce.number().min(0),
  stock: z.coerce.number().int().min(0),
  shop: z.enum(["amul","restaurant","library"]),
});
type Product = z.infer<typeof ProductSchema>;

export default function ProductsAdmin() {
  const [rows, setRows] = useState<Product[]>([
    { name: "Amul Butter 500g", sku: "AM-500B", price: 280, stock: 12, shop: "amul" },
    { name: "Veg Thali", sku: "RST-THALI", price: 180, stock: 9999, shop: "restaurant" },
  ]);

  const { register, handleSubmit, reset, formState:{errors} } = useForm<Product>({
    resolver: zodResolver(ProductSchema),
    defaultValues: { shop: "amul" as const }
  });

  const onSubmit = (data: Product) => {
    setRows(prev => [data, ...prev]);
    reset({ name:"", sku:"", price:0, stock:0, shop:"amul" });
  };

  return (
    <main className="mx-auto max-w-6xl p-4">
      <h1 className="text-xl font-semibold mb-4">Products</h1>

      {/* Add form */}
      <form onSubmit={handleSubmit(onSubmit)} className="grid grid-cols-1 md:grid-cols-6 gap-3 bg-white p-4 rounded-xl border mb-6">
        <input className="md:col-span-2 input" placeholder="Name" {...register("name")} />
        <input className="input" placeholder="SKU" {...register("sku")} />
        <input className="input" type="number" step="0.01" placeholder="Price" {...register("price")} />
        <input className="input" type="number" placeholder="Stock" {...register("stock")} />
        <select className="input" {...register("shop")}>
          <option value="amul">Amul</option>
          <option value="restaurant">Restaurant</option>
          <option value="library">Library</option>
        </select>
        <button className="btn md:col-span-6">Add</button>

        {/* errors */}
        <div className="md:col-span-6 text-sm text-red-600">
          {Object.values(errors).length > 0 && "Please check the form fields"}
        </div>
      </form>

      {/* Table */}
      <div className="overflow-x-auto bg-white rounded-xl border">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-100">
            <tr>
              <th className="th">Name</th>
              <th className="th">SKU</th>
              <th className="th">Shop</th>
              <th className="th text-right">Price (₹)</th>
              <th className="th text-right">Stock</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p, i) => (
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

/* tiny css helpers via tailwind */
declare global {
  namespace JSX { interface IntrinsicElements { } }
}
