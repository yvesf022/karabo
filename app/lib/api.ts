/* =========================================================
   API CLIENT – PRODUCTION SAFE
========================================================= */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "https://karabo.onrender.com";

/* ======================
   CORE FETCH WRAPPER
====================== */
async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "API request failed");
  }

  return res.json() as Promise<T>;
}

/* ======================
   AUTH
====================== */
export type AuthResponse = {
  access_token: string;
  role: "user" | "admin";
};

export function login(email: string, password: string) {
  return apiFetch<AuthResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function register(payload: {
  email: string;
  password: string;
  full_name?: string;
  phone?: string;
}) {
  return apiFetch("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function logout() {
  return apiFetch("/api/auth/logout", { method: "POST" });
}

/* ======================
   USER
====================== */
export type User = {
  id: string;
  email: string;
  full_name?: string;
  phone?: string;
  role: "user" | "admin";
  created_at?: string;
  avatar_url?: string;
};

export function getMe(): Promise<User> {
  return apiFetch<User>("/api/auth/me");
}

export function updateMe(payload: Partial<User>): Promise<User> {
  return apiFetch<User>("/api/users/me", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

/* REQUIRED BY PROFILE PAGE */
export function uploadAvatar(file: File): Promise<User> {
  const formData = new FormData();
  formData.append("file", file);

  return fetch(`${API_BASE}/api/users/me/avatar`, {
    method: "POST",
    credentials: "include",
    body: formData,
  }).then(res => {
    if (!res.ok) throw new Error("Avatar upload failed");
    return res.json();
  });
}

/* ======================
   PRODUCTS
====================== */
export type Product = {
  id: string;
  name: string;
  price: number;
  image_url?: string;
};

export function fetchProducts(): Promise<Product[]> {
  return apiFetch<Product[]>("/api/products");
}

export function getProductById(id: string): Promise<Product> {
  return apiFetch<Product>(`/api/products/${id}`);
}

/* ======================
   ORDERS
====================== */
export type OrderItem = {
  product_id: string;
  quantity: number;
};

export type Order = {
  id: string;
  total_amount: number;
  created_at: string;
  payment_status?: "pending" | "on_hold" | "paid" | "rejected";
  shipping_status?: string;
  items?: OrderItem[];
};

export function getMyOrders(): Promise<Order[]> {
  return apiFetch<Order[]>("/api/orders/my");
}

/* ✅ FIXED: items is OPTIONAL */
export function createOrder(payload: {
  address_id: string;
  items?: OrderItem[];
}) {
  return apiFetch("/api/orders", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/* ======================
   ADDRESSES
====================== */
export type Address = {
  id: string;
  full_name: string;
  phone: string;
  address_line_1: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  is_default: boolean;
};

export function getMyAddresses(): Promise<Address[]> {
  return apiFetch<Address[]>("/api/users/addresses");
}

export function createAddress(
  payload: Omit<Address, "id" | "is_default">
): Promise<Address> {
  return apiFetch<Address>("/api/users/addresses", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteAddress(addressId: string): Promise<void> {
  return apiFetch<void>(`/api/users/addresses/${addressId}`, {
    method: "DELETE",
  });
}

export function setDefaultAddress(addressId: string): Promise<void> {
  return apiFetch<void>(`/api/users/addresses/${addressId}/default`, {
    method: "PATCH",
  });
}
