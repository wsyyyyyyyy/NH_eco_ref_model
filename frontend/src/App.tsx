import { BrowserRouter as Router, Routes, Route, Link, useLocation, useNavigate } from 'react-router-dom';
import { useState, useEffect } from 'react';
import GlobalDashboard from './pages/GlobalDashboard';
import BranchDashboard from './pages/BranchDashboard';
import BorrowerDetail from './pages/BorrowerDetail';
import ModelMonitoring from './pages/ModelMonitoring';
import MacroSimulation from './pages/MacroSimulation';
import LoginPage from './pages/LoginPage';
import { API_BASE_URL } from './config';
import { Globe, Building2, Activity, Sliders, LogOut } from 'lucide-react';

const menus = [
  { path: '/global', label: '글로벌 뱅크 뷰', icon: <Globe size={20} /> },
  { path: '/branch', label: '가상 지점 대시보드', icon: <Building2 size={20} /> },
  { path: '/monitoring', label: '모델 모니터링', icon: <Activity size={20} /> },
  { path: '/simulation', label: '매크로 시뮬레이션', icon: <Sliders size={20} /> },
];

const formatMonth = (ym: string) => {
  if (!ym || ym.length !== 6) return ym;
  return `${ym.substring(0, 4)}년 ${Number(ym.substring(4, 6))}월`;
};

function AppLayout() {
  const location = useLocation();
  const currentMenu = menus.find(m => m.path === location.pathname)?.label || 'Dashboard';
  const [baseDate, setBaseDate] = useState('202402');
  const [availableMonths, setAvailableMonths] = useState<string[]>([
    '202406', '202405', '202404', '202403', '202402', '202401',
    '202312', '202311', '202310', '202309', '202308', '202307', '202306', '202305', '202304', '202303', '202302', '202301',
    '202212', '202206', '202112'
  ]);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/dashboard/months`)
      .then(res => res.json())
      .then(data => {
        if (data.months && data.months.length > 0) {
          setAvailableMonths(data.months);
        }
      })
      .catch(err => console.error('Failed to load months:', err));
  }, []);

  return (
    <div style={{display: 'flex', width: '100vw', height: '100vh', backgroundColor: 'var(--bg-main)', overflow: 'hidden'}}>
      {/* Sidebar (250px) */}
      <div style={{width: '250px', backgroundColor: 'white', borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', flexShrink: 0}}>
        {/* Logo */}
        <div style={{padding: '24px', borderBottom: '1px solid var(--border)'}}>
          <div style={{display: 'flex', alignItems: 'center', gap: '10px'}}>
            <img src="/logo.jpg" alt="logo" style={{width: '36px', height: '36px', borderRadius: '8px', objectFit: 'contain'}} />
            <h1 className="font-bold" style={{fontSize: '20px', letterSpacing: '-0.5px', margin: 0, color: 'var(--text-main)'}}>
              <span style={{color: 'var(--primary)'}}>ECO</span> Ref Model
            </h1>
          </div>
          <p className="font-medium" style={{marginTop: '8px', fontSize: '13px', color: 'var(--text-muted)'}}>AI 조기경보 가상지점 포털</p>
        </div>

        {/* Menu */}
        <nav style={{flex: 1, padding: '24px 16px', display: 'flex', flexDirection: 'column', gap: '8px', overflowY: 'auto'}}>
          {menus.map(menu => (
            <Link key={menu.path} to={menu.path} style={{textDecoration: 'none'}}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: '12px', padding: '12px 16px',
                borderRadius: '8px',
                backgroundColor: location.pathname.startsWith(menu.path) ? 'rgba(37, 99, 235, 0.1)' : 'transparent',
                color: location.pathname.startsWith(menu.path) ? 'var(--primary)' : 'var(--text-main)',
                fontWeight: location.pathname.startsWith(menu.path) ? 700 : 500,
                transition: 'all 0.2s',
              }}>
                {menu.icon}
                <span style={{fontSize: '15px'}}>{menu.label}</span>
              </div>
            </Link>
          ))}
        </nav>

        {/* Team Credits & Logout */}
        <div style={{padding: '16px', borderTop: '1px solid var(--border)'}}>
          <div style={{padding: '12px', background: 'var(--bg-main)', borderRadius: '8px', marginBottom: '12px', fontSize: '11.5px', color: 'var(--text-muted)', lineHeight: '1.6', border: '1px solid var(--border)'}}>
            <div style={{fontWeight: 700, color: 'var(--text-main)', marginBottom: '3px'}}>👑 팀장: 이재현 <span style={{fontSize: '10.5px', color: 'var(--primary)'}}>(기업은행)</span></div>
            <div style={{fontWeight: 600}}>👥 팀원: 강병민<span style={{fontSize: '10px'}}>(부산)</span>·유인경<span style={{fontSize: '10px'}}>(농협)</span>·위세영<span style={{fontSize: '10px'}}>(농협)</span></div>
          </div>
          <Link to="/" style={{textDecoration: 'none'}}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: '12px', padding: '12px 16px',
              borderRadius: '8px', color: 'var(--danger)', fontWeight: 600, transition: 'all 0.2s'
            }}>
              <LogOut size={20} />
              <span>로그아웃</span>
            </div>
          </Link>
        </div>
      </div>

      {/* Right Area (Header + Main + Footer) */}
      <div style={{flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0}}>
        
        {/* Header Bar */}
        <header style={{height: '64px', backgroundColor: 'white', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 32px', flexShrink: 0}}>
          <div className="font-bold" style={{fontSize: '20px', color: 'var(--text-main)'}}>
            {currentMenu}
          </div>
          <div style={{display: 'flex', alignItems: 'center', gap: '24px'}}>
            
            {/* Base Date Selector */}
            <div style={{display: 'flex', alignItems: 'center', gap: '8px', paddingRight: '16px', borderRight: '1px solid var(--border)'}}>
              <span className="font-semibold" style={{fontSize: '14px', color: 'var(--text-muted)'}}>기준일</span>
              <select 
                value={baseDate}
                onChange={(e) => setBaseDate(e.target.value)}
                style={{
                  padding: '8px 12px', borderRadius: '8px', border: '1px solid var(--border)',
                  outline: 'none', background: 'var(--bg-main)', fontWeight: 600, fontSize: '14px',
                  color: 'var(--primary)', cursor: 'pointer', maxHeight: '300px'
                }}
              >
                {availableMonths.map(ym => (
                  <option key={ym} value={ym}>{formatMonth(ym)}</option>
                ))}
              </select>
            </div>

            <span className="badge badge-safe">시스템 정상 작동중</span>
            <div style={{display: 'flex', alignItems: 'center', gap: '12px'}}>
              <div style={{width: '36px', height: '36px', borderRadius: '18px', backgroundColor: 'var(--primary)', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold', fontSize: '16px'}}>
                R
              </div>
              <div className="flex-col" style={{gap: '2px'}}>
                <span className="font-bold" style={{fontSize: '14px', lineHeight: 1}}>Risk Manager</span>
                <span className="font-medium" style={{fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1}}>관리자 계정</span>
              </div>
            </div>
          </div>
        </header>

        {/* Main Content Area */}
        <main className="main-content" style={{flex: 1, padding: '32px', overflowY: 'auto', overflowX: 'hidden'}}>
          <Routes>
            <Route path="/global" element={<GlobalDashboard baseYm={baseDate} />} />
            <Route path="/branch" element={<BranchDashboard baseYm={baseDate} />} />
            <Route path="/borrower/:id" element={<BorrowerDetail baseYm={baseDate} />} />
            <Route path="/monitoring" element={<ModelMonitoring />} />
            <Route path="/simulation" element={<MacroSimulation />} />
          </Routes>
        </main>

        {/* Footer Status Bar */}
        <footer style={{height: '40px', backgroundColor: 'white', borderTop: '1px solid var(--border)', display: 'flex', alignItems: 'center', padding: '0 32px', flexShrink: 0}}>
          <span className="font-medium" style={{fontSize: '13px', color: 'var(--text-muted)'}}>
            ⚡ SME 4.0 ERM Portal v2.0 | 👑 팀장: 이재현(기업은행) | 👥 팀원: 강병민(부산)·유인경(농협)·위세영(농협)
          </span>
        </footer>
        
      </div>
    </div>
  );
}

function AppRoutes() {
  const navigate = useNavigate();
  return (
    <Routes>
      <Route path="/" element={<LoginPage onLogin={() => navigate('/global')} />} />
      <Route path="*" element={<AppLayout />} />
    </Routes>
  );
}

export default function App() {
  return (
    <Router>
      <AppRoutes />
    </Router>
  );
}
