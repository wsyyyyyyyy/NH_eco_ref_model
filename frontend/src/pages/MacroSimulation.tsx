import { useState, useEffect } from 'react';
import { Settings2, RefreshCw, AlertTriangle, TrendingUp, BarChart2, Zap, CheckCircle, Info } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, ResponsiveContainer, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar } from 'recharts';
import { API_BASE_URL } from '../config';

export default function MacroSimulation() {
  const [params, setParams] = useState({
    interestRate: 0,
    exchangeRate: 0,
    inflation: 0,
    oilPrice: 0,
    gdpGrowth: 0
  });
  const [simulating, setSimulating] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<'bar' | 'heatmap' | 'tier' | 'radar'>('bar');
  const [selectedScenario, setSelectedScenario] = useState<string>('정상 상태');
  const [useRealData, setUseRealData] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      runSimulation();
    }, 350);
    return () => clearTimeout(timer);
  }, [params, useRealData]);

  const applyScenario = (name: string, newParams: typeof params) => {
    setSelectedScenario(name);
    setParams(newParams);
  };

  const runSimulation = () => {
    setSimulating(true);

    if (useRealData) {
      fetch(`${API_BASE_URL}/api/simulation/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          interest_rate: params.interestRate,
          exchange_rate: params.exchangeRate,
          inflation: params.inflation,
          oil_price: params.oilPrice,
          gdp_growth: params.gdpGrowth,
        }),
      })
        .then(res => res.json())
        .then(data => {
          setResults(data.results || []);
          setSimulating(false);
        })
        .catch(() => {
          setResults([]);
          setSimulating(false);
        });
      return;
    }

    setTimeout(() => {
      // 목업 모드: 거시경제 지표 민감도에 따른 단순 가중치 산출 (실모형 미연동 시 참고용)
      const intImpact = params.interestRate * 0.055;
      const fxImpact = params.exchangeRate * 0.038;
      const infImpact = params.inflation * 0.042;
      const oilImpact = params.oilPrice * 0.025;
      const gdpImpact = params.gdpGrowth * -0.65;

      const totalShock = intImpact + fxImpact + infImpact + oilImpact + gdpImpact;

      const simResults = [
        { industry: '제조업', name: '제조업', baseRisk: 2.15, base: 2.15, sensitivity: 1.15, oldModelRisk: 1.80 },
        { industry: '도매 및 소매업', name: '도매 및 소매업', baseRisk: 3.42, base: 3.42, sensitivity: 1.35, oldModelRisk: 2.90 },
        { industry: '건설업', name: '건설업', baseRisk: 5.80, base: 5.80, sensitivity: 1.85, oldModelRisk: 4.20 },
        { industry: '정보통신업', name: '정보통신업', baseRisk: 1.45, base: 1.45, sensitivity: 0.85, oldModelRisk: 1.20 },
        { industry: '부동산업', name: '부동산업', baseRisk: 4.90, base: 4.90, sensitivity: 1.65, oldModelRisk: 3.80 },
        { industry: '운수 및 창고업', name: '운수 및 창고업', baseRisk: 2.85, base: 2.85, sensitivity: 1.40, oldModelRisk: 2.50 },
        { industry: '숙박 및 음식점업', name: '숙박 및 음식점업', baseRisk: 4.10, base: 4.10, sensitivity: 1.55, oldModelRisk: 3.40 },
        { industry: '전문, 과학 및 기술', name: '전문, 과학 및 기술', baseRisk: 1.20, base: 1.20, sensitivity: 0.70, oldModelRisk: 1.10 },
      ].map(item => {
        const shockEffect = totalShock * item.sensitivity;
        const newRisk = Math.max(0.1, Number((item.baseRisk + shockEffect).toFixed(2)));
        const diff = Number((newRisk - item.baseRisk).toFixed(2));

        const oldShockEffect = totalShock * (item.sensitivity * 0.55);
        const oldNewRisk = Math.max(0.1, Number((item.oldModelRisk + oldShockEffect).toFixed(2)));

        return {
          ...item,
          newRisk,
          diff,
          oldNewRisk,
          gap: Number((newRisk - oldNewRisk).toFixed(2)),
          status: newRisk > 5.0 ? '위험' : newRisk > 3.0 ? '주의' : '안전'
        };
      });

      setResults(simResults);
      setSimulating(false);
    }, 250);
  };

  const getHeatmapColor = (diff: number) => {
    if (diff > 2.0) return '#ef4444';      
    if (diff > 1.0) return '#f87171';      
    if (diff > 0.3) return '#fca5a5';      
    if (diff > -0.3) return '#f1f5f9';     
    if (diff > -1.0) return '#a7f3d0';     
    return '#34d399';                      
  };

  const getHeatmapTextColor = (diff: number) => {
    if (diff > 1.0 || diff < -1.5) return '#ffffff';
    return 'var(--text-main)';
  };

  const highRiskIndustries = results.filter(r => r.newRisk >= 4.5 || r.diff >= 2.0);
  const midRiskIndustries = results.filter(r => (r.newRisk >= 2.5 && r.newRisk < 4.5) && r.diff < 2.0);
  const safeIndustries = results.filter(r => r.newRisk < 2.5 && r.diff < 2.0);

  return (
    <div className="flex-col" style={{gap: '24px'}}>
      <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px'}}>
        <div className="flex-col" style={{gap: '4px'}}>
          <h1 className="font-bold" style={{fontSize: '24px', margin: 0}}>매크로 스트레스 테스트 시뮬레이터</h1>
          <p className="font-regular" style={{color: 'var(--text-muted)'}}>거시경제 지표(금리, 환율, 유가 등) 변동에 따른 산업군별 부도 위험률 변화 다차원 분석</p>
        </div>
        <div className="flex-row" style={{gap: '12px', alignItems: 'center'}}>
          <button 
            onClick={() => setUseRealData(!useRealData)}
            style={{
              padding: '6px 14px',
              borderRadius: '20px',
              border: 'none',
              backgroundColor: useRealData ? '#10b981' : '#64748b',
              color: 'white',
              fontWeight: 700,
              fontSize: '13px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              boxShadow: '0 2px 6px rgba(0,0,0,0.1)'
            }}
          >
            {useRealData ? '🔌 실모형 연동 중 (LightGBM v1.0)' : '🧪 목업 모드 (테스트)'}
          </button>
          <button onClick={() => applyScenario('정상 상태', {interestRate: 0, exchangeRate: 0, inflation: 0, oilPrice: 0, gdpGrowth: 0})} className="btn btn-ghost">
            <RefreshCw size={18} /> 설정 초기화
          </button>
        </div>
      </div>

      {/* Historical Crisis Presets */}
      <div className="card flex-col" style={{gap: '12px', padding: '16px', background: 'linear-gradient(135deg, #ffffff 0%, #f8fafc 100%)', border: '1px solid var(--border)'}}>
        <div className="flex-row" style={{alignItems: 'center', gap: '8px'}}>
          <Zap size={18} color="var(--primary)" />
          <span className="font-bold" style={{fontSize: '14px', color: 'var(--text-main)'}}>⚡ 역사적 금융위기 시나리오 원클릭 프리셋 적용</span>
          <span className="font-regular" style={{fontSize: '12px', color: 'var(--text-muted)'}}>(과거 실제 위기 상황의 경제 지표를 즉시 로드하여 모의 스트레스 테스트를 수행합니다)</span>
        </div>
        <div className="flex-row" style={{gap: '12px', flexWrap: 'wrap'}}>
          <button 
            onClick={() => applyScenario('🔥 1997 IMF 외환위기', {interestRate: 80, exchangeRate: 80, inflation: 4.5, oilPrice: 15, gdpGrowth: -2.0})}
            className="btn"
            style={{
              padding: '10px 16px',
              fontSize: '13px',
              backgroundColor: selectedScenario === '🔥 1997 IMF 외환위기' ? 'var(--danger)' : 'white',
              color: selectedScenario === '🔥 1997 IMF 외환위기' ? 'white' : 'var(--text-main)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              cursor: 'pointer',
              fontWeight: 600,
              boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
            }}
          >
            🔥 1997 IMF 외환위기 재현
          </button>
          
          <button 
            onClick={() => applyScenario('📉 2008 글로벌 금융위기', {interestRate: -40, exchangeRate: 50, inflation: 2.0, oilPrice: -35, gdpGrowth: -3.5})}
            className="btn"
            style={{
              padding: '10px 16px',
              fontSize: '13px',
              backgroundColor: selectedScenario === '📉 2008 글로벌 금융위기' ? '#ea580c' : 'white',
              color: selectedScenario === '📉 2008 글로벌 금융위기' ? 'white' : 'var(--text-main)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              cursor: 'pointer',
              fontWeight: 600,
              boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
            }}
          >
            📉 2008 글로벌 금융위기
          </button>

          <button 
            onClick={() => applyScenario('📈 2024 3고 스태그플레이션', {interestRate: 50, exchangeRate: 40, inflation: 3.5, oilPrice: 20, gdpGrowth: -0.8})}
            className="btn"
            style={{
              padding: '10px 16px',
              fontSize: '13px',
              backgroundColor: selectedScenario === '📈 2024 3고 스태그플레이션' ? '#d97706' : 'white',
              color: selectedScenario === '📈 2024 3고 스태그플레이션' ? 'white' : 'var(--text-main)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              cursor: 'pointer',
              fontWeight: 600,
              boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
            }}
          >
            📈 고금리·고환율·고물가 스태그플레이션
          </button>

          <button 
            onClick={() => applyScenario('🌱 연착륙 및 금리인하 기대', {interestRate: -50, exchangeRate: -20, inflation: -1.5, oilPrice: -10, gdpGrowth: 1.2})}
            className="btn"
            style={{
              padding: '10px 16px',
              fontSize: '13px',
              backgroundColor: selectedScenario === '🌱 연착륙 및 금리인하 기대' ? 'var(--safe)' : 'white',
              color: selectedScenario === '🌱 연착륙 및 금리인하 기대' ? 'white' : 'var(--text-main)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              cursor: 'pointer',
              fontWeight: 600,
              boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
            }}
          >
            🌱 연착륙 및 금리인하 시나리오
          </button>
        </div>
      </div>

      <div className="grid-macro" style={{alignItems: 'stretch'}}>
        {/* Left: Sliders */}
        <div className="flex-col" style={{gap: '12px'}}>
          <div className="flex-row" style={{gap: '8px', alignItems: 'center'}}>
            <Settings2 size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>거시경제 지표 변동 시뮬레이터</h2>
          </div>

          <div className="card flex-col" style={{gap: '22px', flex: 1, justifyContent: 'space-between'}}>
            <div>
              <div className="flex-row" style={{justifyContent: 'space-between', marginBottom: '8px'}}>
                <span className="font-semibold" style={{fontSize: '14px'}}>기준 금리</span>
                <span className="font-bold" style={{color: params.interestRate > 0 ? 'var(--danger)' : params.interestRate < 0 ? 'var(--safe)' : 'var(--text-main)'}}>
                  {params.interestRate > 0 ? `+${params.interestRate}` : params.interestRate} bp
                </span>
              </div>
              <input type="range" min="-100" max="100" step="10" value={params.interestRate} onChange={e => { setSelectedScenario('사용자 맞춤 설정'); setParams({...params, interestRate: Number(e.target.value)}); }} className="range-slider" />
            </div>

            <div>
              <div className="flex-row" style={{justifyContent: 'space-between', marginBottom: '8px'}}>
                <span className="font-semibold" style={{fontSize: '14px'}}>환율 (원/달러)</span>
                <span className="font-bold" style={{color: params.exchangeRate > 0 ? 'var(--danger)' : params.exchangeRate < 0 ? 'var(--safe)' : 'var(--text-main)'}}>
                  {params.exchangeRate > 0 ? `+${params.exchangeRate}` : params.exchangeRate} 원
                </span>
              </div>
              <input type="range" min="-100" max="100" step="10" value={params.exchangeRate} onChange={e => { setSelectedScenario('사용자 맞춤 설정'); setParams({...params, exchangeRate: Number(e.target.value)}); }} className="range-slider" />
            </div>

            <div>
              <div className="flex-row" style={{justifyContent: 'space-between', marginBottom: '8px'}}>
                <span className="font-semibold" style={{fontSize: '14px'}}>물가 상승률</span>
                <span className="font-bold" style={{color: params.inflation > 0 ? 'var(--danger)' : params.inflation < 0 ? 'var(--safe)' : 'var(--text-main)'}}>
                  {params.inflation > 0 ? `+${params.inflation}` : params.inflation} %p
                </span>
              </div>
              <input type="range" min="-3" max="5" step="0.5" value={params.inflation} onChange={e => { setSelectedScenario('사용자 맞춤 설정'); setParams({...params, inflation: Number(e.target.value)}); }} className="range-slider" />
            </div>

            <div>
              <div className="flex-row" style={{justifyContent: 'space-between', marginBottom: '8px'}}>
                <span className="font-semibold" style={{fontSize: '14px'}}>국제 유가 (WTI)</span>
                <span className="font-bold" style={{color: params.oilPrice > 0 ? 'var(--danger)' : params.oilPrice < 0 ? 'var(--safe)' : 'var(--text-main)'}}>
                  {params.oilPrice > 0 ? `+${params.oilPrice}` : params.oilPrice} $
                </span>
              </div>
              <input type="range" min="-40" max="60" step="5" value={params.oilPrice} onChange={e => { setSelectedScenario('사용자 맞춤 설정'); setParams({...params, oilPrice: Number(e.target.value)}); }} className="range-slider" />
            </div>

            <div>
              <div className="flex-row" style={{justifyContent: 'space-between', marginBottom: '8px'}}>
                <span className="font-semibold" style={{fontSize: '14px'}}>실질 GDP 성장률</span>
                <span className="font-bold" style={{color: params.gdpGrowth < 0 ? 'var(--danger)' : params.gdpGrowth > 0 ? 'var(--safe)' : 'var(--text-main)'}}>
                  {params.gdpGrowth > 0 ? `+${params.gdpGrowth}` : params.gdpGrowth} %p
                </span>
              </div>
              <input type="range" min="-4" max="3" step="0.2" value={params.gdpGrowth} onChange={e => { setSelectedScenario('사용자 맞춤 설정'); setParams({...params, gdpGrowth: Number(e.target.value)}); }} className="range-slider" />
            </div>
          </div>
        </div>

        {/* Right: Multi-View Visualization Dashboard */}
        <div className="flex-col" style={{gap: '12px'}}>
          <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
            <div className="flex-row" style={{gap: '8px', alignItems: 'center'}}>
              <BarChart2 size={20} color="var(--primary)" />
              <h2 className="font-semibold" style={{margin: 0}}>산업군별 충격 파급도 다차원 분석</h2>
            </div>
            
            {/* View Mode Tabs */}
            <div className="flex-row" style={{gap: '4px', background: 'var(--border)', padding: '3px', borderRadius: '8px', flexWrap: 'wrap'}}>
              <button 
                onClick={() => setActiveTab('bar')}
                style={{
                  padding: '6px 12px',
                  fontSize: '12px',
                  fontWeight: 600,
                  border: 'none',
                  borderRadius: '6px',
                  backgroundColor: activeTab === 'bar' ? 'white' : 'transparent',
                  color: activeTab === 'bar' ? 'var(--primary)' : 'var(--text-muted)',
                  cursor: 'pointer',
                  boxShadow: activeTab === 'bar' ? '0 1px 2px rgba(0,0,0,0.1)' : 'none'
                }}
              >
                📊 가로형 비교 차트
              </button>
              <button 
                onClick={() => setActiveTab('heatmap')}
                style={{
                  padding: '6px 12px',
                  fontSize: '12px',
                  fontWeight: 600,
                  border: 'none',
                  borderRadius: '6px',
                  backgroundColor: activeTab === 'heatmap' ? 'white' : 'transparent',
                  color: activeTab === 'heatmap' ? 'var(--primary)' : 'var(--text-muted)',
                  cursor: 'pointer',
                  boxShadow: activeTab === 'heatmap' ? '0 1px 2px rgba(0,0,0,0.1)' : 'none'
                }}
              >
                🔥 충격 히트맵
              </button>
              <button 
                onClick={() => setActiveTab('tier')}
                style={{
                  padding: '6px 12px',
                  fontSize: '12px',
                  fontWeight: 600,
                  border: 'none',
                  borderRadius: '6px',
                  backgroundColor: activeTab === 'tier' ? 'white' : 'transparent',
                  color: activeTab === 'tier' ? 'var(--primary)' : 'var(--text-muted)',
                  cursor: 'pointer',
                  boxShadow: activeTab === 'tier' ? '0 1px 2px rgba(0,0,0,0.1)' : 'none'
                }}
              >
                🚨 3단 위험 매트릭스
              </button>
              <button 
                onClick={() => setActiveTab('radar')}
                style={{
                  padding: '6px 12px',
                  fontSize: '12px',
                  fontWeight: 600,
                  border: 'none',
                  borderRadius: '6px',
                  backgroundColor: activeTab === 'radar' ? 'white' : 'transparent',
                  color: activeTab === 'radar' ? 'var(--primary)' : 'var(--text-muted)',
                  cursor: 'pointer',
                  boxShadow: activeTab === 'radar' ? '0 1px 2px rgba(0,0,0,0.1)' : 'none'
                }}
              >
                🕸️ 산업 균형 레이더
              </button>
            </div>
          </div>

          <div className="card flex-col" style={{minHeight: '430px', flex: 1, justifyContent: 'space-between'}}>
            {simulating ? (
              <div style={{textAlign: 'center', padding: '140px 0'}}>
                <div className="spinner" style={{width: '40px', height: '40px', border: '3px solid var(--border)', borderTopColor: 'var(--primary)', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto'}} />
                <p className="font-medium" style={{marginTop: '16px', color: 'var(--text-muted)'}}>AI 엔진이 거시경제 지표 파급 효과 및 산업 네트워크 복합 리스크를 산출 중입니다...</p>
              </div>
            ) : (
              <>
                {/* TAB 1: Horizontal Comparison Bar Chart */}
                {activeTab === 'bar' && (
                  <div className="flex-col" style={{height: '100%', gap: '12px'}}>
                    <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
                      <span className="font-medium" style={{fontSize: '13px', color: 'var(--text-muted)'}}>
                        현재 적용 시나리오: <strong style={{color: 'var(--text-main)'}}>{selectedScenario}</strong>
                      </span>
                      <span className="badge badge-warning" style={{fontSize: '11px'}}>
                        평시 대비 부도율 변화량(diff) 시각화
                      </span>
                    </div>
                    <div style={{width: '100%', height: '320px'}}>
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart layout="vertical" data={results} margin={{ top: 10, right: 30, left: 20, bottom: 5 }}>
                          <CartesianGrid strokeDasharray="3 3" horizontal={true} vertical={false} stroke="#e5e7eb" />
                          <XAxis type="number" unit="%" tick={{fill: 'var(--text-muted)', fontSize: 12}} axisLine={{stroke: '#e5e7eb'}} tickLine={false} domain={[0, (dataMax: number) => Math.ceil(dataMax + 2)]} tickFormatter={(val) => `${Math.round(val)}`} />
                          <YAxis dataKey="industry" type="category" tick={{fill: 'var(--text-main)', fontSize: 13, fontWeight: 600}} axisLine={{stroke: '#e5e7eb'}} tickLine={false} width={80} />
                          <RechartsTooltip 
                            cursor={{fill: 'rgba(0,0,0,0.04)'}} 
                            content={({active, payload}) => {
                              if (active && payload && payload.length) {
                                const data = payload[0].payload;
                                return (
                                  <div style={{background: 'var(--bg-card)', padding: '12px 16px', border: '1px solid var(--border)', borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)'}}>
                                    <div className="font-bold" style={{fontSize: '14px', marginBottom: '6px'}}>{data.industry} 부도 위험률</div>
                                    <div style={{fontSize: '13px', color: 'var(--text-muted)'}}>• 평시 기준 부도율: <strong style={{color: 'var(--text-main)'}}>{data.baseRisk}%</strong></div>
                                    <div style={{fontSize: '13px', color: 'var(--danger)', marginTop: '2px'}}>• 충격 후 예상 부도율: <strong style={{fontSize: '15px'}}>{data.newRisk}%</strong></div>
                                    <div style={{fontSize: '12px', fontWeight: 700, marginTop: '6px', color: data.diff > 0 ? 'var(--danger)' : data.diff < 0 ? 'var(--safe)' : 'var(--text-muted)'}}>
                                      {data.diff > 0 ? `▲ 평시 대비 +${data.diff}%p 급증` : data.diff < 0 ? `▼ 평시 대비 ${data.diff}%p 감소` : '변동 없음'}
                                    </div>
                                  </div>
                                );
                              }
                              return null;
                            }}
                          />
                          <Legend verticalAlign="top" height={36} iconType="circle" wrapperStyle={{fontSize: '13px', fontWeight: 500}} />
                          <Bar dataKey="baseRisk" fill="#94a3b8" name="평시 기준 부도율 (Base Risk)" radius={[0, 4, 4, 0]} barSize={12} />
                          <Bar dataKey="newRisk" fill="var(--danger)" name="시뮬레이션 적용 부도율 (Simulated Risk)" radius={[0, 4, 4, 0]} barSize={12} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}

                {/* TAB 2: Executive Impact Heatmap */}
                {activeTab === 'heatmap' && (
                  <div className="flex-col" style={{gap: '14px', height: '100%'}}>
                    <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
                      <span className="font-medium" style={{fontSize: '13px', color: 'var(--text-muted)'}}>
                        거시경제 충격에 따른 산업군별 민감도 매트릭스 (<strong style={{color: '#dc2626'}}>붉은색일수록 치명적 파급 효과</strong>)
                      </span>
                      <div className="flex-row" style={{gap: '10px', alignItems: 'center', fontSize: '11px', fontWeight: 600}}>
                        <span style={{display: 'inline-block', width: '10px', height: '10px', backgroundColor: '#ef4444', borderRadius: '2px'}}></span> 고위험 (+2%p↑)
                        <span style={{display: 'inline-block', width: '10px', height: '10px', backgroundColor: '#fca5a5', borderRadius: '2px'}}></span> 주의 (+0.3%p↑)
                        <span style={{display: 'inline-block', width: '10px', height: '10px', backgroundColor: '#10b981', borderRadius: '2px'}}></span> 위험 감소
                      </div>
                    </div>
                    
                    <div style={{
                      display: 'grid', 
                      gridTemplateColumns: 'repeat(4, 1fr)', 
                      gap: '12px',
                      flex: 1,
                      alignContent: 'center'
                    }}>
                      {results.map((r, idx) => (
                        <div key={idx} className="card flex-col" style={{
                          padding: '16px 12px',
                          borderRadius: '12px',
                          backgroundColor: getHeatmapColor(r.diff),
                          color: getHeatmapTextColor(r.diff),
                          justifyContent: 'center',
                          alignItems: 'center',
                          textAlign: 'center',
                          gap: '6px',
                          border: '1px solid rgba(0,0,0,0.08)',
                          boxShadow: '0 2px 6px rgba(0,0,0,0.06)',
                          transition: 'all 0.2s',
                          cursor: 'default'
                        }}>
                          <span className="font-bold" style={{fontSize: '15px', lineHeight: 1.2}}>{r.industry}</span>
                          <div className="flex-row" style={{alignItems: 'center', gap: '4px', margin: '2px 0'}}>
                            <span className="font-black" style={{fontSize: '22px'}}>{r.newRisk.toFixed(2)}%</span>
                          </div>
                          <div style={{background: 'rgba(0,0,0,0.12)', padding: '3px 8px', borderRadius: '6px'}}>
                            <span className="font-bold" style={{fontSize: '12px', color: getHeatmapTextColor(r.diff)}}>
                              {r.diff > 0 ? `▲ 평시 대비 +${r.diff.toFixed(2)}%p` : r.diff < 0 ? `▼ 평시 대비 ${r.diff.toFixed(2)}%p` : '변동 없음'}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* TAB 2: 3-Tier Risk Matrix Cards */}
                {activeTab === 'tier' && (
                  <div className="flex-col" style={{gap: '14px', height: '100%'}}>
                    <span className="font-medium" style={{fontSize: '13px', color: 'var(--text-muted)'}}>
                      충격 후 부도 위험도 기준 산업군 자동 분류 매트릭스 (<strong style={{color: 'var(--danger)'}}>고위험 4.5%+</strong> / <strong style={{color: 'var(--warning)'}}>주의 2.5%+</strong> / <strong style={{color: 'var(--safe)'}}>안정 &lt;2.5%</strong>)
                    </span>
                    <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', flex: 1}}>
                      {/* High Risk Tier */}
                      <div className="flex-col" style={{background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '10px', padding: '12px', gap: '8px', overflowY: 'auto', maxHeight: '310px'}}>
                        <div className="flex-row" style={{alignItems: 'center', gap: '6px', borderBottom: '1px solid #fca5a5', paddingBottom: '8px'}}>
                          <AlertTriangle size={16} color="#b91c1c" />
                          <span className="font-bold" style={{color: '#b91c1c', fontSize: '13px'}}>🚨 고위험 감지 ({highRiskIndustries.length})</span>
                        </div>
                        {highRiskIndustries.length === 0 ? (
                          <span style={{fontSize: '12px', color: '#991b1b', textAlign: 'center', padding: '20px 0'}}>해당 없음 (안정)</span>
                        ) : (
                          highRiskIndustries.map((item, idx) => (
                            <div key={idx} className="card flex-col" style={{padding: '10px', gap: '4px', borderColor: '#fecaca', background: 'white'}}>
                              <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
                                <span className="font-bold" style={{fontSize: '14px', color: '#991b1b'}}>{item.industry}</span>
                                <span className="font-extrabold" style={{fontSize: '15px', color: '#b91c1c'}}>{item.newRisk}%</span>
                              </div>
                              <span style={{fontSize: '11px', fontWeight: 600, color: '#dc2626'}}>
                                평시({item.baseRisk}%) 대비 ▲+{item.diff}%p 급증
                              </span>
                            </div>
                          ))
                        )}
                      </div>

                      {/* Medium Risk Tier */}
                      <div className="flex-col" style={{background: '#fffbeb', border: '1px solid #fde68a', borderRadius: '10px', padding: '12px', gap: '8px', overflowY: 'auto', maxHeight: '310px'}}>
                        <div className="flex-row" style={{alignItems: 'center', gap: '6px', borderBottom: '1px solid #fcd34d', paddingBottom: '8px'}}>
                          <TrendingUp size={16} color="#b45309" />
                          <span className="font-bold" style={{color: '#b45309', fontSize: '13px'}}>⚠️ 주의 요망 ({midRiskIndustries.length})</span>
                        </div>
                        {midRiskIndustries.length === 0 ? (
                          <span style={{fontSize: '12px', color: '#92400e', textAlign: 'center', padding: '20px 0'}}>해당 없음</span>
                        ) : (
                          midRiskIndustries.map((item, idx) => (
                            <div key={idx} className="card flex-col" style={{padding: '10px', gap: '4px', borderColor: '#fde68a', background: 'white'}}>
                              <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
                                <span className="font-bold" style={{fontSize: '14px', color: '#92400e'}}>{item.industry}</span>
                                <span className="font-extrabold" style={{fontSize: '15px', color: '#d97706'}}>{item.newRisk}%</span>
                              </div>
                              <span style={{fontSize: '11px', fontWeight: 600, color: '#b45309'}}>
                                평시({item.baseRisk}%) 대비 {item.diff >= 0 ? `▲+${item.diff}` : `▼${item.diff}`}%p
                              </span>
                            </div>
                          ))
                        )}
                      </div>

                      {/* Safe Tier */}
                      <div className="flex-col" style={{background: '#ecfdf5', border: '1px solid #a7f3d0', borderRadius: '10px', padding: '12px', gap: '8px', overflowY: 'auto', maxHeight: '310px'}}>
                        <div className="flex-row" style={{alignItems: 'center', gap: '6px', borderBottom: '1px solid #6ee7b7', paddingBottom: '8px'}}>
                          <CheckCircle size={16} color="#047857" />
                          <span className="font-bold" style={{color: '#047857', fontSize: '13px'}}>🟢 안정권 유지 ({safeIndustries.length})</span>
                        </div>
                        {safeIndustries.length === 0 ? (
                          <span style={{fontSize: '12px', color: '#065f46', textAlign: 'center', padding: '20px 0'}}>해당 없음</span>
                        ) : (
                          safeIndustries.map((item, idx) => (
                            <div key={idx} className="card flex-col" style={{padding: '10px', gap: '4px', borderColor: '#a7f3d0', background: 'white'}}>
                              <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
                                <span className="font-bold" style={{fontSize: '14px', color: '#065f46'}}>{item.industry}</span>
                                <span className="font-extrabold" style={{fontSize: '15px', color: '#10b981'}}>{item.newRisk}%</span>
                              </div>
                              <span style={{fontSize: '11px', fontWeight: 600, color: '#047857'}}>
                                평시({item.baseRisk}%) 대비 {item.diff >= 0 ? `▲+${item.diff}` : `▼${item.diff}`}%p
                              </span>
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* TAB 3: Industry Radar Chart */}
                {activeTab === 'radar' && (
                  <div className="flex-col" style={{gap: '12px', height: '100%', alignItems: 'center', justifyContent: 'center'}}>
                    <span className="font-medium" style={{fontSize: '13px', color: 'var(--text-muted)', alignSelf: 'flex-start'}}>
                      전체 산업 생태계 부도 균형(Balance) 왜곡도 비교 레이더 (<strong style={{color: 'var(--danger)'}}>붉은 영역이 충격 후 왜곡 면적</strong>)
                    </span>
                    <div style={{width: '100%', height: '300px'}}>
                      <ResponsiveContainer width="100%" height="100%">
                        <RadarChart cx="50%" cy="50%" outerRadius="75%" data={results}>
                          <PolarGrid stroke="#e5e7eb" />
                          <PolarAngleAxis dataKey="industry" tick={{fill: 'var(--text-main)', fontSize: 13, fontWeight: 600}} />
                          <PolarRadiusAxis angle={30} domain={[0, 'auto']} />
                          <Radar name="평시 기준 부도율" dataKey="baseRisk" stroke="#94a3b8" fill="#94a3b8" fillOpacity={0.3} />
                          <Radar name="스트레스 적용 부도율" dataKey="newRisk" stroke="var(--danger)" fill="var(--danger)" fillOpacity={0.5} />
                          <Legend verticalAlign="top" height={36} wrapperStyle={{fontSize: '13px', fontWeight: 500}} />
                          <RechartsTooltip contentStyle={{backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)', borderRadius: '8px'}} />
                        </RadarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}

                {/* Bottom Actionable Insights Footer */}
                <div className="flex-row" style={{gap: '10px', background: 'var(--bg-main)', padding: '12px 16px', borderRadius: '8px', alignItems: 'flex-start', borderLeft: '4px solid var(--primary)', marginTop: '8px'}}>
                  <Info size={18} color="var(--primary)" style={{flexShrink: 0, marginTop: '1px'}} />
                  <span className="font-regular" style={{color: 'var(--text-muted)', fontSize: '13px', lineHeight: 1.4}}>
                    <strong>💡 AI 거시경제 스트레스 진단:</strong> 금리 및 환율 상승 시 대출 잔액과 PF 비중이 높은 <strong>건설업/부동산업</strong>이 가장 민감하게 반응합니다. 고위험군으로 분류된 업종에 대해서는 영업점 신규 여신 한도 심사를 자동으로 강화하도록 권장합니다.
                  </span>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
