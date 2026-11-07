import React from "react";
import { createRoot } from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "./public.css";
import PublicApp from "./PublicApp.jsx";
createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <PublicApp />
  </React.StrictMode>,
);
