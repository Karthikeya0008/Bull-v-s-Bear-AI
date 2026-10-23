import { NavLink, Route, Routes } from "react-router-dom";
import IpoList from "./pages/IpoList";
import IpoDetail from "./pages/IpoDetail";
import Backtest from "./pages/Backtest";

export default function App() {
  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded-md px-3 py-1.5 text-sm ${isActive ? "bg-slate-800 text-white" : "text-slate-400 hover:text-white"}`;
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
          <NavLink to="/" className="flex items-center gap-2 font-semibold">
            <span className="text-bull">▲</span>
            <span>Bull vs Bear AI</span>
            <span className="text-bear">▼</span>
          </NavLink>
          <nav className="flex gap-1">
            <NavLink to="/" end className={link}>IPOs</NavLink>
            <NavLink to="/backtest" className={link}>Back-test</NavLink>
          </nav>
          <span className="ml-auto hidden text-xs text-slate-500 md:block">
            Agentic RAG debate over SEBI offer documents · not investment advice
          </span>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Routes>
          <Route path="/" element={<IpoList />} />
          <Route path="/ipo/:ipoId" element={<IpoDetail />} />
          <Route path="/backtest" element={<Backtest />} />
        </Routes>
      </main>
    </div>
  );
}
