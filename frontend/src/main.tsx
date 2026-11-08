import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "@/App";
import { applyTheme, useThemeStore } from "@/stores/theme";
import "@/styles/index.css";

// index.html already applied the stored theme before first paint. This keeps
// the attribute and the store in agreement from the first render.
applyTheme(useThemeStore.getState().preference);

const container = document.getElementById("root");
if (!container) throw new Error("#root is missing from index.html");

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
