import { useState } from 'react';
import { API_BASE_URL } from '../config';

export default function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [empId, setEmpId] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    fetch(`${API_BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ emp_id: empId, password }),
    })
      .then(async res => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail || '로그인에 실패했습니다.');
        }
        onLogin();
      })
      .catch(err => setError(err.message || '로그인에 실패했습니다.'))
      .finally(() => setLoading(false));
  };

  return (
    <div style={{
      width: '100vw', height: '100vh', 
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg-main)',
      position: 'relative',
      overflow: 'hidden'
    }}>
      {/* Decorative background blur */}
      <div style={{
        position: 'absolute', top: '10%', left: '20%', width: '400px', height: '400px',
        background: 'rgba(37, 99, 235, 0.1)', filter: 'blur(100px)', borderRadius: '50%'
      }} />
      <div style={{
        position: 'absolute', bottom: '10%', right: '20%', width: '300px', height: '300px',
        background: 'rgba(236, 72, 153, 0.1)', filter: 'blur(80px)', borderRadius: '50%'
      }} />

      <div className="glass-panel" style={{
        width: '400px', padding: '40px', display: 'flex', flexDirection: 'column', alignItems: 'center',
        zIndex: 10, background: 'rgba(255,255,255,0.9)'
      }}>
        {/* Logo */}
        <div style={{marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '12px'}}>
          <img src="/logo.jpg" alt="logo" style={{width: '40px', height: '40px', borderRadius: '12px', objectFit: 'contain'}} />
          <h1 style={{margin: 0, fontSize: '24px', letterSpacing: '-0.5px'}}>
            <span style={{color: 'var(--primary)'}}>ECO</span> Ref Model
          </h1>
        </div>
        
        <p style={{color: 'var(--text-muted)', marginBottom: '8px', textAlign: 'center'}}>
          AI 조기경보 가상지점 포털에<br/>오신 것을 환영합니다.
        </p>
        <p style={{color: 'var(--text-muted)', fontSize: '12px', marginBottom: '24px', textAlign: 'center'}}>
          테스트 계정: admin / admin1234
        </p>

        <form onSubmit={handleLogin} style={{width: '100%', display: 'flex', flexDirection: 'column', gap: '16px'}}>
          <div className="flex-col" style={{gap: '8px'}}>
            <label style={{fontSize: '14px', fontWeight: 600}}>사번 (행번)</label>
            <input 
              type="text" 
              value={empId}
              onChange={e => setEmpId(e.target.value)}
              placeholder="예: 20240101"
              required
              style={{
                width: '100%', padding: '12px 16px', borderRadius: '8px', 
                border: '1px solid var(--border)', background: 'white',
                outline: 'none', transition: 'border-color 0.2s', boxSizing: 'border-box'
              }}
            />
          </div>
          
          <div className="flex-col" style={{gap: '8px'}}>
            <label style={{fontSize: '14px', fontWeight: 600}}>비밀번호</label>
            <input 
              type="password" 
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              required
              style={{
                width: '100%', padding: '12px 16px', borderRadius: '8px', 
                border: '1px solid var(--border)', background: 'white',
                outline: 'none', transition: 'border-color 0.2s', boxSizing: 'border-box'
              }}
            />
          </div>

          {error && (
            <div style={{padding: '10px 14px', borderRadius: '8px', background: '#fef2f2', border: '1px solid #fecaca', color: 'var(--danger)', fontSize: '13px', fontWeight: 600}}>
              {error}
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary"
            style={{width: '100%', padding: '14px', marginTop: '16px', justifyContent: 'center', fontWeight: 600, fontSize: '16px'}}
            disabled={loading}
          >
            {loading ? '인증 중...' : '로그인'}
          </button>
        </form>
      </div>
    </div>
  );
}
