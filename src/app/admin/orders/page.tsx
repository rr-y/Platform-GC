'use client';
import { useEffect, useState } from "react";

type OrderItem = { sku: string; name: string; quantity: number; price: number };
type Order = {
  id: string;
  createdAt: string;
  total: number;
  items: OrderItem[];
};

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);

  useEffect(() => {
    fetch("/api/orders")
      .then(res => res.json())
      .then(setOrders);
  }, []);

  return (
    <main className="max-w-5xl mx-auto p-4 space-y-6">
      <h1 className="text-xl font-semibold">📋 All Orders</h1>

      {orders.length === 0 ? (
        <p className="text-gray-500">No orders yet</p>
      ) : (
        <div className="space-y-4">
          {orders.map(order => (
            <div key={order.id} className="bg-white p-4 rounded-xl shadow-sm border">
              <div className="flex justify-between items-center mb-2">
                <div className="text-sm text-gray-500">{new Date(order.createdAt).toLocaleString()}</div>
                <div className="text-base font-bold">₹{order.total.toFixed(2)}</div>
              </div>
              <table className="table w-full text-sm">
                <thead>
                  <tr>
                    <th className="th">Name</th>
                    <th className="th text-right">Qty</th>
                    <th className="th text-right">Price</th>
                    <th className="th text-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {order.items.map((item, i) => (
                    <tr key={i}>
                      <td className="td">{item.name}</td>
                      <td className="td text-right">{item.quantity}</td>
                      <td className="td text-right">₹{item.price.toFixed(2)}</td>
                      <td className="td text-right">₹{(item.price * item.quantity).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
