import { Navigate, Route, Routes } from 'react-router-dom';

import { RequireAuth } from './auth/RequireAuth';
import { NavBar } from './components/NavBar';
import { Analyzer } from './pages/Analyzer';
import { ConnectionManager } from './pages/ConnectionManager';
import { ConfirmSignUp } from './pages/auth/ConfirmSignUp';
import { ForgotPassword } from './pages/auth/ForgotPassword';
import { Login } from './pages/auth/Login';
import { ResetPassword } from './pages/auth/ResetPassword';
import { SignUp } from './pages/auth/SignUp';

function AppLayout({ children }: { children: JSX.Element }): JSX.Element {
  return (
    <div className="app-shell">
      <NavBar />
      <main className="app-main">{children}</main>
    </div>
  );
}

export default function App(): JSX.Element {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<SignUp />} />
      <Route path="/confirm" element={<ConfirmSignUp />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />

      <Route
        path="/analyzer"
        element={
          <RequireAuth>
            <AppLayout>
              <Analyzer />
            </AppLayout>
          </RequireAuth>
        }
      />
      <Route
        path="/connections"
        element={
          <RequireAuth>
            <AppLayout>
              <ConnectionManager />
            </AppLayout>
          </RequireAuth>
        }
      />

      <Route path="/" element={<Navigate to="/analyzer" replace />} />
      <Route path="*" element={<Navigate to="/analyzer" replace />} />
    </Routes>
  );
}
