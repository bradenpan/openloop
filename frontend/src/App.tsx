import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AppShell } from './components/layout/app-shell';
import Home from './pages/Home';
import Space from './pages/Space';
import Settings from './pages/Settings';
import Agents from './pages/Agents';
import Automations from './pages/Automations';
import Calendar from './pages/Calendar';
import Email from './pages/Email';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Home />} />
          <Route path="/calendar" element={<Calendar />} />
          <Route path="/email" element={<Email />} />
          <Route path="/space/:spaceId" element={<Space />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/automations" element={<Automations />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
