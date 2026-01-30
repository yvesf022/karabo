// ⚠️ COMPATIBILITY SHIM
// This file exists ONLY to satisfy legacy imports
// Real product data now comes from the backend API

export type Product = {
  id: string;
  title: string;
  price: number;
  img: string;
  category: string;
  rating: number;
};

// Empty fallback — pages that still import this
// should not crash Netlify build
export const products: Product[] = [];
