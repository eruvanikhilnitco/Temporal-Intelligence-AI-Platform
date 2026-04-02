import { useState } from "react";
import Landing from "./pages/Landing";
import SignUp from "./pages/SignUp";
import Login from "./pages/Login";
import ForgotPassword from "./pages/ForgotPassword";
import Dashboard from "./pages/Dashboard";
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

  const navigate: NavigateFn = (target, opts) => {
    if (opts?.email) setLoginEmail(opts.email);
    setPage(target);
  };

  // Guard: dashboard requires token
  if (page === "dashboard" && !localStorage.getItem("accessToken")) {
    return <Login navigate={navigate} defaultEmail="" />;
  }

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
}
