/** Top navigation showing the logged-in user and a logout action. */

import { NavLink, useNavigate } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';

export function NavBar(): JSX.Element {
  const { username, logout } = useAuth();
  const navigate = useNavigate();

  function onLogout() {
    logout();
    navigate('/login', { replace: true });
  }

  return (
    <nav className="navbar">
      <div className="navbar-brand">AI Query Analyser</div>
      <div className="navbar-links">
        <NavLink to="/analyzer">Analyzer</NavLink>
        <NavLink to="/connections">Connections</NavLink>
      </div>
      <div className="navbar-user">
        {username && <span className="navbar-username">{username}</span>}
        <button type="button" className="link-button" onClick={onLogout}>
          Log out
        </button>
      </div>
    </nav>
  );
}
