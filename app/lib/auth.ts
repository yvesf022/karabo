"use client";

import { create } from "zustand";
import * as api from "@/lib/api";

export type User = api.User;

type AuthState = {
  user: User | null;
  loading: boolean;

  hydrate: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

export const useAuth = create<AuthState>((set) => ({
  user: null,
  loading: true,

  // 🔑 AMAZON-LEVEL HYDRATION (ONLY TRUST /me)
  hydrate: async () => {
    try {
      const user = await api.getMe();
      set({ user, loading: false });
    } catch {
      set({ user: null, loading: false });
    }
  },

  // 🔐 LOGIN → identity → redirect
  login: async (email, password) => {
    const res = await api.login(email, password);

    // Fetch verified identity after login
    const user = await api.getMe();
    set({ user });

    if (user.role === "admin") {
      window.location.replace("/admin");
    } else {
      window.location.replace("/account");
    }
  },

  // 🚪 LOGOUT = destroy identity
  logout: async () => {
    try {
      await api.logout();
    } catch {}

    set({ user: null });
  },
}));

/* -------------------------------------------------
   ✅ BACKWARD-COMPATIBLE NAMED EXPORTS
-------------------------------------------------- */

// These fix existing imports like:
// import { login } from "@/lib/auth";

export async function login(email: string, password: string) {
  return useAuth.getState().login(email, password);
}

export async function logout() {
  return useAuth.getState().logout();
}
