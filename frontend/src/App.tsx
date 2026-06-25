import { useState } from 'react'
import { HashRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import Layout from './Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Proxy from './pages/Proxy'
import Domains from './pages/Domains'
import Settings from './pages/Settings'
import Core from './pages/Core'
import Configs from './pages/Configs'

function PrivateRoute() {
  const token = localStorage.getItem('token')
  if (!token) return <Navigate to="/" replace />
  return <Outlet />
}

function AuthenticatedApp() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route element={<PrivateRoute />}>
          <Route element={<Layout />}>
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="proxy" element={<Proxy />} />
            <Route path="domains" element={<Domains />} />
            <Route path="core" element={<Core />} />
            <Route path="configs" element={<Configs />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </HashRouter>
  )
}

export default function App() {
  const [hasToken, setHasToken] = useState(() => !!localStorage.getItem('token'))

  if (!hasToken) {
    return <Login onSuccess={() => setHasToken(true)} />
  }
  return <AuthenticatedApp />
}
