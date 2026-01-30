/* =========================================================
   SHARED TYPES
========================================================= */

export type User = {
  id: string;
  email: string;
  full_name?: string;
  phone?: string;
  role: "user" | "admin";
  created_at?: string;
  avatar_url?: string;
};

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

export type Product = {
  id: string;
  name: string;
  price: number;
  image_url?: string;

  /* ✅ OPTIONAL — used by wishlist & cart UI */
  stock?: number;
};

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
