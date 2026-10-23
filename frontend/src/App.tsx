import { NavLink, Route, Routes } from "react-router-dom";
import IpoList from "./pages/IpoList";
import IpoDetail from "./pages/IpoDetail";
import Backtest from "./pages/Backtest";
import DataExplorer from "./pages/DataExplorer";

export default function App() {
  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded-md px-3 py-1.5 text-sm font-medium transition ${
      isActive ? "bg-brand-light text-brand" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
    }`;
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-8 px-4 py-3 sm:px-6">
          <NavLink to="/" className="flex items-center gap-3">
            <span className="flex h-9 w-9 flex-col items-center justify-center rounded-lg bg-brand text-[10px] leading-none text-white shadow-card">
              <span className="text-emerald-300">▲</span>
              <span className="text-rose-300">▼</span>
            </span>
            <span className="leading-tight">
              <span className="block text-[15px] font-semibold text-slate-900">Bull vs Bear AI</span>
              <span className="block text-[11px] font-medium text-slate-500">IPO Intelligence · India</span>
            </span>
          </NavLink>
          <nav className="flex gap-1">
            <NavLink to="/" end className={link}>IPO Pipeline</NavLink>
            <NavLink to="/backtest" className={link}>Back-test</NavLink>
          </nav>
          <span className="ml-auto hidden items-center gap-2 text-xs text-slate-500 md:flex">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            Agentic RAG over SEBI offer documents
          </span>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6">
        <Routes>
          <Route path="/" element={<IpoList />} />
          <Route path="/ipo/:ipoId" element={<IpoDetail />} />
          <Route path="/ipo/:ipoId/data" element={<DataExplorer />} />
          <Route path="/backtest" element={<Backtest />} />
        </Routes>
      </main>
      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-4 text-xs text-slate-500 sm:px-6">
          <span>Data: SEBI public filings, NSE issue data, Yahoo Finance. Figures computed from restated financials.</span>
          <span className="font-medium text-slate-600">Not investment advice.</span>
        </div>
      </footer>
    </div>
  );
}
