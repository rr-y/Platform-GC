'use client';
import { useEffect, useState } from "react";
import toast from "react-hot-toast";


type Product = { name: string; sku: string; price: number; stock: number; shop: string };
type CartItem = Product & { quantity: number };

export default function POSPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [cart, setCart] = useState<CartItem[]>([]);

  useEffect(() => {
    fetch("/api/products")
      .then((res) => res.json())
      .then(setProducts);
  }, []);

  const addToCart = (p: Product) => {
    setCart(prev => {
      const existing = prev.find(item => item.sku === p.sku);
      if (existing) {
        return prev.map(item =>
          item.sku === p.sku ? { ...item, quantity: item.quantity + 1 } : item
        );
      } else {
        return [...prev, { ...p, quantity: 1 }];
      }
    });
  };

  const removeFromCart = (sku: string) => {
    setCart(prev => prev.filter(item => item.sku !== sku));
  };

  const updateQty = (sku: string, qty: number) => {
    setCart(prev => prev.map(item =>
      item.sku === sku ? { ...item, quantity: qty } : item
    ));
  };

  const total = cart.reduce((sum, item) => sum + item.price * item.quantity, 0);
  const [isLoading, setIsLoading] = useState(false);

  const submitOrder = async () => {
  if (!cart.length) return;

  setIsLoading(true); // start loading

  const items = cart.map(({ name, sku, price, quantity }) => ({
    name, sku, price, quantity
  }));

  const res = await fetch("/api/orders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(items)
  });

  if (res.ok) {
    toast.success("✅ Bill submitted!");
    setCart([]);
  } else {
    toast.error("❌ Failed to submit bill");
  }

  setIsLoading(false); // stop loading
};



  return (
    <main className="max-w-6xl mx-auto p-4 space-y-6">
      <h1 className="text-xl font-semibold">🧾 Geeta Complex POS</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Product List */}
        <div className="space-y-3">
          <h2 className="font-semibold">Products</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {products.map(p => (
              <div key={p.sku} className="border rounded-xl p-3 bg-white shadow-sm">
                <h3 className="font-medium">{p.name}</h3>
                <div className="text-sm text-gray-500">{p.sku} · {p.shop}</div>
                <div className="text-right text-base font-bold mt-2">₹{p.price.toFixed(2)}</div>
                <button onClick={() => addToCart(p)} className="btn mt-2 w-full">Add</button>
              </div>
            ))}
          </div>
        </div>

        {/* Cart View */}
        <div className="space-y-3">
          <h2 className="font-semibold">Cart</h2>
          {cart.length === 0 ? (
            <p className="text-gray-500">No items in cart</p>
          ) : (
            <table className="table min-w-full text-sm bg-white rounded-xl">
              <thead>
                <tr>
                  <th className="th">Name</th>
                  <th className="th text-right">Qty</th>
                  <th className="th text-right">Price</th>
                  <th className="th text-right">Total</th>
                  <th className="th"></th>
                </tr>
              </thead>
              <tbody>
                {cart.map((item) => (
                  <tr key={item.sku} className="border-t">
                    <td className="td">{item.name}</td>
                    <td className="td text-right">
                      <input
                        type="number"
                        min={1}
                        className="input w-16 text-right"
                        value={item.quantity}
                        onChange={(e) => updateQty(item.sku, +e.target.value)}
                      />
                    </td>
                    <td className="td text-right">₹{item.price.toFixed(2)}</td>
                    <td className="td text-right">₹{(item.price * item.quantity).toFixed(2)}</td>
                    <td className="td text-right">
                      <button onClick={() => removeFromCart(item.sku)} className="text-red-600 hover:underline text-xs">Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t font-semibold">
                  <td className="td text-right" colSpan={3}>Total</td>
                  <td className="td text-right">₹{total.toFixed(2)}</td>
                  <td></td>
                </tr>
              </tfoot>
            </table>
          )}

            <button
                disabled={!cart.length || isLoading}
                onClick={submitOrder}
                className="btn w-full h-12 text-base"
                >
                {isLoading ? "Submitting..." : "Submit Bill"}
            </button>
        </div>
      </div>
    </main>
  );
}
