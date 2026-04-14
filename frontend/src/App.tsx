import { useState, useEffect } from "react";
import Landing from "./pages/Landing";
import SignUp from "./pages/SignUp";
import Login from "./pages/Login";
import ForgotPassword from "./pages/ForgotPassword";
import Dashboard from "./pages/Dashboard";
// Import client.ts to register global 401 interceptor
import "./api/client";
import "./index.css";

export type Page =
  | "landing"
  | "signup"
  | "signup-user"
  | "signup-admin"
  | "login"
  | "forgot-password"
  | "dashboard";

export type NavigateFn = (page: Page, opts?: { email?: string }) => void;

export default function App() {
  const hasToken = !!localStorage.getItem("accessToken");
  const [page, setPage] = useState<Page>(hasToken ? "dashboard" : "landing");
  const [loginEmail, setLoginEmail] = useState("");
  const [sessionExpiredMsg, setSessionExpiredMsg] = useState(false);

  const navigate: NavigateFn = (target, opts) => {
    if (opts?.email) setLoginEmail(opts.email);
    setPage(target);
  };

  // Listen for session expiry from the global 401 interceptor
  useEffect(() => {
    const handler = () => {
      setSessionExpiredMsg(true);
      setPage("login");
      setTimeout(() => setSessionExpiredMsg(false), 5000);
    };
    window.addEventListener("session-expired", handler);
    return () => window.removeEventListener("session-expired", handler);
  }, []);

  // Guard: dashboard requires a valid token in localStorage
  if (page === "dashboard" && !localStorage.getItem("accessToken")) {
    return <Login navigate={navigate} defaultEmail="" />;
  }

  return (
    <>
      {sessionExpiredMsg && (
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, zIndex: 9999,
          background: "#ef4444", color: "#fff", textAlign: "center",
          padding: "10px 16px", fontSize: 14, fontWeight: 600,
        }}>
          Your session expired. Please log in again.
        </div>
      )}
      {(() => {
        switch (page) {
          case "landing":         return <Landing navigate={navigate} />;
          case "signup":          return <SignUp navigate={navigate} role="user" />;
          case "signup-user":     return <SignUp navigate={navigate} role="user" />;
          case "signup-admin":    return <SignUp navigate={navigate} role="admin" />;
          case "login":           return <Login navigate={navigate} defaultEmail={loginEmail} />;
          case "forgot-password": return <ForgotPassword navigate={navigate} />;
          case "dashboard":       return <Dashboard navigate={navigate} />;
          default:                return <Landing navigate={navigate} />;
        }
      })()}
    </>
  );
}
