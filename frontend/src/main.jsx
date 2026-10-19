/** main.jsx */

import { StrictMode }       from "react";
import { createRoot }       from "react-dom/client";
import { ToastContainer }   from "react-toastify";
import "react-toastify/dist/ReactToastify.css";

import { AuthProvider }       from "./context/AuthContext";
import { HospitalProvider }     from "./context/HospitalContext";
import { PermissionProvider } from "./context/PermissionContext";
import { ThemeProvider }      from "./context/ThemeContext";

import App from "./App";

import "./styles/variables.css";
import "./styles/global.css";
import "./styles/intake-workspace.css";
import "./styles/front-desk-command-centre.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <ThemeProvider>
      <AuthProvider>
        <HospitalProvider>
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
        </HospitalProvider>
      </AuthProvider>
    </ThemeProvider>
  </StrictMode>
);
