import { create } from "zustand";

import { accounts as api } from "@/services/api";
import type { Account } from "@/types/api";

interface AccountsState {
  items: Account[];
  loading: boolean;
  error: string | null;
  load: () => Promise<void>;
  reconnect: (id: string) => Promise<void>;
  disconnect: (id: string, purge?: "now" | "30d") => Promise<void>;
}

export const useAccounts = create<AccountsState>((set, get) => ({
  items: [],
  loading: false,
  error: null,

  load: async () => {
    set({ loading: true, error: null });
    try {
      set({ items: await api.list(), loading: false });
    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : "Could not load accounts",
      });
    }
  },

  reconnect: async (id) => {
    // A full-page navigation, not a popup: Google blocks its consent screen
    // in an iframe, and a popup is what a browser blocks instead.
    const { authorize_url } = await api.reconnect(id);
    window.location.assign(authorize_url);
  },

  disconnect: async (id, purge = "30d") => {
    await api.disconnect(id, purge);
    await get().load();
  },
}));

/** The banner is driven by this, not by a dismissal flag. */
export const accountNeedingReconnect = (items: Account[]): Account | undefined =>
  items.find((account) => account.needs_reconnect);
