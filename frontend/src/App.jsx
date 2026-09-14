import React from 'react'
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import AlertAnalysis from './pages/AlertAnalysis'
import HistoryBrowser from './pages/HistoryBrowser'
import ReplayViewer from './pages/ReplayViewer'

function Navigation() {
  const location = useLocation()
  
  const isActive = (path) => {
    return location.pathname === path ? 'active' : ''
  }

  return (
    <header className="header">
      <h1>🔧 运维诊断系统</h1>
      <nav className="nav">
        <Link to="/" className={isActive('/')}>告警分析</Link>
        <Link to="/history" className={isActive('/history')}>历史浏览</Link>
        <Link to="/replay" className={isActive('/replay')}>逐帧回放</Link>
      </nav>
    </header>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <Navigation />
        <main className="main">
          <Routes>
            <Route path="/" element={<AlertAnalysis />} />
            <Route path="/history" element={<HistoryBrowser />} />
            <Route path="/replay/:threadId" element={<ReplayViewer />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
