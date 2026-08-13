/**
 * main.jsx
 * --------
 * Application entry point.
 * Mounts React into #root with all global providers in correct order:
 *   ThemeProvider      — selected color theme (applies before auth so the
 *                        login screen itself picks up the chosen theme)
 *   AuthProvider       — JWT user state
 *   TenantProvider     — tenant metadata
 *   PermissionProvider — feature-flag permissions
 *   ToastContainer     — toast notifications (react-toastify)
 *   App                — router and route tree
 */

import { StrictMode }       from "react";
import { createRoot }       from "react-dom/client";
import { ToastContainer }   from "react-toastify";
import "react-toastify/dist/ReactToastify.css";

import { AuthProvider }       from "./context/AuthContext";
import { TenantProvider }     from "./context/TenantContext";
import { PermissionProvider } from "./context/PermissionContext";
import { ThemeProvider }      from "./context/ThemeContext";

import App from "./App";

import "./styles/variables.css";
import "./styles/global.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <ThemeProvider>
      <AuthProvider>
        <TenantProvider>
          <PermissionProvider>
            <App />
            <ToastContainer
              position="top-right"
              autoClose={4000}
              hideProgressBar={false}
              newestOnTop
              closeOnClick
              pauseOnHover
              theme="light"
            />
          </PermissionProvider>
        </TenantProvider>
      </AuthProvider>
    </ThemeProvider>
  </StrictMode>
);
