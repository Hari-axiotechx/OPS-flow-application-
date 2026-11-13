import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Header from './Header';
import { VoiceAssistantProvider } from '../voice/VoiceAssistant';

const DASHBOARD_THEMES = {
  skyBlue: {
    name: 'Sky Blue',
    background: '#e8f5ff',
  },
  lavender: {
    name: 'Lavender',
    background: '#f2edff',
  },
  peach: {
    name: 'Peach',
    background: '#fff0e4',
  },
  rose: {
    name: 'Rose',
    background: '#fff0f4',
  },
  black: {
    name: 'Black',
    background: '#111827',
    dark: true,
  },
  white: {
    name: 'White',
    background: '#ffffff',
  },
  sunrise: {
    name: 'Sunrise',
    background: '#fff4d6',
    swatch: 'linear-gradient(135deg, #ffd36e, #ff9a76)',
  },
  aurora: {
    name: 'Aurora',
    background: '#e8f5ff',
    swatch: 'linear-gradient(135deg, #88d9d2, #a899ff, #f8a9c4)',
  },
  birds: {
    name: 'Birds',
    background: '#eaf6ff',
    swatch: 'linear-gradient(135deg, #b9e6ff, #eff9ff)',
  },
};

export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const [theme, setTheme] = useState(() => {
    const savedTheme = localStorage.getItem('opsflow-dashboard-theme');
    if (DASHBOARD_THEMES[savedTheme]) return savedTheme;
    if (savedTheme === 'blue' || savedTheme === 'mint') return 'skyBlue';
    if (savedTheme === 'yellow') return 'sunrise';
    return 'skyBlue';
  });

  function handleThemeChange(newTheme) {
    setTheme(newTheme);
    localStorage.setItem(
      'opsflow-dashboard-theme',
      newTheme
    );
  }

  const currentTheme =
    DASHBOARD_THEMES[theme] ||
    DASHBOARD_THEMES.skyBlue;

  return (
    <VoiceAssistantProvider>
    <div
      className={`flex min-h-screen dashboard-theme-${theme}`}
      style={{
        backgroundColor: currentTheme.background,
      }}
    >
      {/* Sidebar */}
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Main application area */}
      <div
        className="
          flex-1
          flex
          flex-col
          min-w-0
        "
        style={{
          backgroundColor: currentTheme.background,
        }}
      >
        {/* Header */}
        <Header
          onMenuClick={() =>
            setSidebarOpen(true)
          }
          theme={theme}
          onThemeChange={handleThemeChange}
          themes={DASHBOARD_THEMES}
        />

        {/* Page content */}
        <main
          className={`dashboard-content dashboard-theme-${theme} flex-1 p-4 lg:p-8 max-w-[1400px] w-full mx-auto`}
          style={{ backgroundColor: currentTheme.background }}
        >
          <Outlet />
        </main>
      </div>
    </div>
    </VoiceAssistantProvider>
  );
}