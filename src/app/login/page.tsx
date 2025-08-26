'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import toast from 'react-hot-toast';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const router = useRouter();

  const handleLogin = async () => {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });

    if (res.ok) {
      toast.success('Logged in');
      const role = await res.text();
      router.push(role === 'admin' ? '/admin/orders' : '/pos');
    } else {
      toast.error('Invalid credentials');
    }
  };

  return (
    <div className="max-w-sm mx-auto mt-20 p-4 border shadow rounded">
      <h2 className="text-xl font-bold mb-4">Login</h2>
      <input
        className="input input-bordered w-full mb-2"
        type="text"
        placeholder="Username"
        value={username}
        onChange={e => setUsername(e.target.value)}
      />
      <input
        className="input input-bordered w-full mb-4"
        type="password"
        placeholder="Password"
        value={password}
        onChange={e => setPassword(e.target.value)}
      />
      <button onClick={handleLogin} className="btn btn-primary w-full">
        Login
      </button>
    </div>
  );
}
