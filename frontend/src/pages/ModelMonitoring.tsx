import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, ResponsiveContainer, LineChart, Line } from 'recharts';
import { Activity, Target, ShieldCheck, BarChart2, List, ChevronRight, Info } from 'lucide-react';
import { API_BASE_URL } from '../config';

type Metrics = { train_auc: number; valid_auc: number; train_gini: number; valid_gini: number; train_ks: number; valid_ks: number; total_psi: number };
type DriftPoint = { month: string; psi: number };
type PdBin = { bin: string; 기존모형: number; ERM모형: number };
type BinBorrower = { id: string; name: string; industry: string; pd: number; oldGrade: string; oldPd: number; ermGrade: string; isBlindSpot?: boolean };

// 은행 실제 레거시 모형의 산출 부도확률(RZVL_POD) 원본 데이터로 직접 계산한 실측치.
// 이 필드는 2021.01~2021.11 구간만 값이 채워져 있고 그 이후는 소스 자체에서 0으로
// 고정되어 있어(원본 데이터 한계), 해당 11개월 표본(14.7만 건)에서 IS_BUDO_12M 실제
// 부도 결과 대비 AUROC/Gini/K-S를 계산한 값. 참고치가 아니라 실측값이다.
const LEGACY_BENCHMARK = { auroc: 0.823, gini: 0.646, ks: 0.499 };

export default function ModelMonitoring() {
  const [loading, setLoading] = useState(true);
  const [selectedBin, setSelectedBin] = useState('70%+ (고위험)');
  const [useRealData, setUseRealData] = useState(true);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [driftData, setDriftData] = useState<DriftPoint[]>([]);
  const [pdDistData, setPdDistData] = useState<PdBin[]>([]);
  const [binBorrowers, setBinBorrowers] = useState<BinBorrower[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE_URL}/api/monitoring/metrics`).then(r => r.json()),
      fetch(`${API_BASE_URL}/api/monitoring/drift`).then(r => r.json()),
      fetch(`${API_BASE_URL}/api/monitoring/pd_distribution`).then(r => r.json()),
    ])
      .then(([m, d, p]) => {
        setMetrics(m);
        setDriftData(d);
        setPdDistData(p);
      })
      .catch(err => console.error('Failed to load monitoring data:', err))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/monitoring/borrowers?${new URLSearchParams({ bin: selectedBin })}`)
      .then(r => r.json())
      .then(data => setBinBorrowers(Array.isArray(data) ? data : []))
      .catch(() => setBinBorrowers([]));
  }, [selectedBin]);

  const perfData = metrics ? [
    { metric: 'AUROC (변별력)', 기존모형: LEGACY_BENCHMARK.auroc, ERM모형: metrics.valid_auc },
    { metric: 'GINI Index', 기존모형: LEGACY_BENCHMARK.gini, ERM모형: metrics.valid_gini },
    { metric: 'K-S Stats', 기존모형: LEGACY_BENCHMARK.ks, ERM모형: metrics.valid_ks },
  ] : [];

  if (loading) return <div className="p-6">Loading Performance Metrics...</div>;

  return (
    <div className="flex-col" style={{gap: '24px'}}>
      <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px'}}>
        <div className="flex-col">
          <h1 className="font-bold" style={{fontSize: '24px', margin: 0}}>AI 리스크 평가 모형 (ERM) 성능 및 안정성 모니터링</h1>
          <p className="font-regular" style={{color: 'var(--text-muted)', marginTop: '4px'}}>금융 규제 기준(바젤/금감원) 핵심 평가 지표 실시간 감지 및 부도율 구간별 차주 드릴다운 분석</p>
        </div>
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
      </div>

      {/* Top 4 Official Financial Model Evaluation Metrics */}
      <div className="grid-4">
        <div className="card flex-col" style={{gap: '8px', padding: '16px', borderTop: '3px solid var(--primary)'}}>
          <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
            <span className="font-bold" style={{color: 'var(--text-main)', fontSize: '14px'}}>AUROC (변별력)</span>
            <Target size={18} color="var(--primary)" />
          </div>
          <div className="flex-row" style={{alignItems: 'baseline', gap: '8px'}}>
            <span className="font-extrabold" style={{fontSize: '24px', color: 'var(--primary)'}}>{metrics?.valid_auc.toFixed(3)}</span>
            <span className="font-bold" style={{color: 'var(--safe)', fontSize: '13px'}}>▲ {(metrics ? metrics.valid_auc - LEGACY_BENCHMARK.auroc : 0).toFixed(3)}</span>
          </div>
          <span className="font-regular" style={{color: 'var(--text-muted)', fontSize: '12px', lineHeight: 1.3}}>
            부도/정상 기업 간 식별력 지표<br />(0.7 이상 시 우수 모형, Valid 기준)
          </span>
        </div>

        <div className="card flex-col" style={{gap: '8px', padding: '16px', borderTop: '3px solid var(--primary)'}}>
          <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
            <span className="font-bold" style={{color: 'var(--text-main)', fontSize: '14px'}}>GINI INDEX</span>
            <Activity size={18} color="var(--primary)" />
          </div>
          <div className="flex-row" style={{alignItems: 'baseline', gap: '8px'}}>
            <span className="font-extrabold" style={{fontSize: '24px', color: 'var(--primary)'}}>{metrics?.valid_gini.toFixed(3)}</span>
            <span className="font-bold" style={{color: 'var(--safe)', fontSize: '13px'}}>▲ {(metrics ? metrics.valid_gini - LEGACY_BENCHMARK.gini : 0).toFixed(3)}</span>
          </div>
          <span className="font-regular" style={{color: 'var(--text-muted)', fontSize: '12px', lineHeight: 1.3}}>
            모형 누적 변별도 및 정확도<br />(2 × AUROC - 1 공식 산출)
          </span>
        </div>

        <div className="card flex-col" style={{gap: '8px', padding: '16px', borderTop: '3px solid var(--safe)'}}>
          <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
            <span className="font-bold" style={{color: 'var(--text-main)', fontSize: '14px'}}>PSI (인구안정성지수)</span>
            <ShieldCheck size={18} color="var(--safe)" />
          </div>
          <div className="flex-row" style={{alignItems: 'baseline', gap: '8px'}}>
            <span className="font-extrabold" style={{fontSize: '24px', color: 'var(--safe)'}}>{metrics?.total_psi.toFixed(4)}</span>
            <span className="badge badge-safe" style={{fontSize: '11px', padding: '2px 6px'}}>{(metrics?.total_psi ?? 0) < 0.1 ? '안정권' : (metrics?.total_psi ?? 0) < 0.25 ? '모니터링' : '재학습 필요'}</span>
          </div>
          <span className="font-regular" style={{color: 'var(--text-muted)', fontSize: '12px', lineHeight: 1.3}}>
            개발 시점 대비 데이터 일치도<br />(0.1 미만 시 매우 안정적)
          </span>
        </div>

        <div className="card flex-col" style={{gap: '8px', padding: '16px', borderTop: '3px solid var(--primary)'}}>
          <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
            <span className="font-bold" style={{color: 'var(--text-main)', fontSize: '14px'}}>K-S STATISTICS</span>
            <BarChart2 size={18} color="var(--primary)" />
          </div>
          <div className="flex-row" style={{alignItems: 'baseline', gap: '8px'}}>
            <span className="font-extrabold" style={{fontSize: '24px', color: 'var(--primary)'}}>{((metrics?.valid_ks ?? 0) * 100).toFixed(1)}%</span>
            <span className="font-bold" style={{color: 'var(--safe)', fontSize: '13px'}}>▲ {(((metrics?.valid_ks ?? 0) - LEGACY_BENCHMARK.ks) * 100).toFixed(1)}%p</span>
          </div>
          <span className="font-regular" style={{color: 'var(--text-muted)', fontSize: '12px', lineHeight: 1.3}}>
            부도-정상 누적분포 최대격차<br />(40% 이상 시 최고 등급 변별력)
          </span>
        </div>
      </div>

      {/* Row 1: Metrics & Drift */}
      <div className="grid-2" style={{alignItems: 'stretch'}}>
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px', alignItems: 'center'}}>
            <Target size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>금융 규제 핵심 평가 지표 비교</h2>
          </div>
          <div className="card flex-col" style={{flex: 1, justifyContent: 'space-between'}}>
            <div style={{width: '100%', height: '260px'}}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={perfData} margin={{ top: 20, right: 30, left: -20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                  <XAxis dataKey="metric" tick={{fill: 'var(--text-muted)', fontSize: 12}} axisLine={{stroke: '#e5e7eb'}} tickLine={false} />
                  <YAxis domain={[0, 1]} tick={{fill: 'var(--text-muted)', fontSize: 12}} axisLine={{stroke: '#e5e7eb'}} tickLine={false} />
                  <RechartsTooltip cursor={{fill: 'rgba(0,0,0,0.05)'}} contentStyle={{backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)', borderRadius: '8px'}} />
                  <Legend verticalAlign="bottom" height={36} iconType="circle" wrapperStyle={{fontSize: '13px', fontWeight: 500}} />
                  <Bar dataKey="기존모형" fill="#94a3b8" radius={[4, 4, 0, 0]} name="기존 은행 모형 (2021.01~11 실측)" maxBarSize={36} />
                  <Bar dataKey="ERM모형" fill="var(--primary)" radius={[4, 4, 0, 0]} name="ERM 참조 모델 (LightGBM)" maxBarSize={36} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="flex-row" style={{gap: '8px', background: 'var(--bg-main)', padding: '12px', borderRadius: '8px', alignItems: 'flex-start', marginTop: '12px'}}>
              <Info size={16} color="var(--primary)" style={{flexShrink: 0, marginTop: '2px'}} />
              <span className="font-regular" style={{color: 'var(--text-muted)', fontSize: '13px', lineHeight: 1.4}}>
                <strong>평가 지표 의미:</strong> AUROC와 Gini Index는 정상 기업과 부도 기업의 변별력을 나타내며, K-S Stats는 두 집단 분포 격차의 최대치를 의미합니다. 기존 은행 모형 수치는 실제 산출 부도확률(RZVL_POD)이 남아있는 2021.01~11 구간(14.7만 건) 실측값이며, ERM 모델은 그보다 훨씬 넓은 검증 구간에서도 이를 상회하는 성능을 달성했습니다.
              </span>
            </div>
          </div>
        </div>

        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{gap: '8px', alignItems: 'center'}}>
            <Activity size={20} color="var(--primary)" />
            <h2 className="font-semibold" style={{margin: 0}}>데이터/컨셉 드리프트 모니터링 (PSI)</h2>
          </div>
          <div className="card flex-col" style={{flex: 1, justifyContent: 'space-between'}}>
            <div style={{width: '100%', height: '260px'}}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={driftData} margin={{ top: 20, right: 30, left: -20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                  <XAxis dataKey="month" tick={{fill: 'var(--text-muted)', fontSize: 12}} dy={10} axisLine={{stroke: '#e5e7eb'}} tickLine={false} />
                  <YAxis tick={{fill: 'var(--text-muted)', fontSize: 12}} axisLine={{stroke: '#e5e7eb'}} tickLine={false} />
                  <RechartsTooltip contentStyle={{backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)', borderRadius: '8px'}} />
                  <Legend wrapperStyle={{fontSize: '13px', paddingTop: '16px'}} />
                  <Line type="stepAfter" dataKey={() => 0.25} stroke="var(--danger)" strokeDasharray="5 5" strokeWidth={1} dot={false} activeDot={false} name="재학습 필요 임계치 (0.25)" />
                  <Line type="monotone" dataKey="psi" stroke="var(--primary)" strokeWidth={2} dot={{r:4}} name={`PSI (기준월: ${driftData[0]?.month ?? '-'})`} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="flex-row" style={{gap: '8px', background: '#ecfdf5', padding: '12px', borderRadius: '8px', alignItems: 'flex-start', border: '1px solid #10b981', marginTop: '12px'}}>
              <ShieldCheck size={16} color="var(--safe)" style={{flexShrink: 0, marginTop: '2px'}} />
              <span className="font-regular" style={{color: '#065f46', fontSize: '13px', lineHeight: 1.4}}>
                <strong>실측 PSI 추이:</strong> 최초 데이터 시점({driftData[0]?.month ?? '-'}) 대비 최근({driftData[driftData.length - 1]?.month ?? '-'}) 예측 확률 분포의 PSI는 {driftData[driftData.length - 1]?.psi ?? 0}입니다. 2022년 거시경제 급변 이후 분포 이동이 발생해 지속적인 모니터링이 권장됩니다.
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Row 2: PD Distribution & Clickable Borrower List */}
      <div className="grid-2" style={{alignItems: 'stretch'}}>
        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
            <div className="flex-row" style={{gap: '8px', alignItems: 'center'}}>
              <BarChart2 size={20} color="var(--primary)" />
              <h2 className="font-semibold" style={{margin: 0}}>예측 부도율 구간별 (PD Bin) 분포 비교</h2>
            </div>
            <span className="font-medium" style={{fontSize: '12px', color: 'var(--primary)', backgroundColor: 'rgba(59, 130, 246, 0.1)', padding: '4px 8px', borderRadius: '6px'}}>
              💡 막대를 클릭하면 우측에 차주가 표시됩니다
            </span>
          </div>
          <div className="card" style={{flex: 1}}>
            <div style={{width: '100%', height: '340px'}}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={pdDistData} margin={{ top: 20, right: 30, left: -20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                  <XAxis dataKey="bin" tick={{fill: 'var(--text-muted)', fontSize: 12}} axisLine={{stroke: '#e5e7eb'}} tickLine={false} />
                  <YAxis tick={{fill: 'var(--text-muted)', fontSize: 12}} axisLine={{stroke: '#e5e7eb'}} tickLine={false} unit="%" />
                  <RechartsTooltip cursor={{fill: 'rgba(0,0,0,0.05)'}} contentStyle={{backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)', borderRadius: '8px'}} />
                  <Legend verticalAlign="bottom" height={36} iconType="circle" wrapperStyle={{fontSize: '13px', fontWeight: 500}} />
                  <Bar dataKey="기존모형" fill="#94a3b8" radius={[4, 4, 0, 0]} name="기존 모형 (안전 편향)" maxBarSize={36} cursor="pointer" onClick={(data: any) => { if (data && data.bin) setSelectedBin(data.bin); }} />
                  <Bar dataKey="ERM모형" fill="var(--danger)" radius={[4, 4, 0, 0]} name="ERM 모델 (고위험 식별)" maxBarSize={36} cursor="pointer" onClick={(data: any) => { if (data && data.bin) setSelectedBin(data.bin); }} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        <div className="flex-col" style={{gap: '12px', height: '100%'}}>
          <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
            <div className="flex-row" style={{gap: '8px', alignItems: 'center'}}>
              <List size={20} color="var(--primary)" />
              <h2 className="font-semibold" style={{margin: 0}}>
                [{selectedBin}] 구간 차주 목록
              </h2>
            </div>
            <span className="badge badge-danger" style={{fontSize: '12px', padding: '4px 8px'}}>
              클릭 시 상세 보고서 이동
            </span>
          </div>
          <div className="card flex-col" style={{flex: 1, gap: '10px', overflowY: 'auto', maxHeight: '380px'}}>
            {binBorrowers.map((item) => (
              <div 
                key={item.id} 
                className="flex-col" 
                onClick={() => navigate(`/borrower/${item.id}`)}
                style={{
                  gap: '12px',
                  padding: '16px', 
                  backgroundColor: 'var(--bg-main)', 
                  borderRadius: '10px', 
                  border: '1px solid var(--border)',
                  cursor: 'pointer',
                  transition: 'all 0.2s'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--primary)';
                  e.currentTarget.style.transform = 'translateY(-2px)';
                  e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--border)';
                  e.currentTarget.style.transform = 'translateY(0)';
                  e.currentTarget.style.boxShadow = 'none';
                }}
              >
                <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
                  <div className="flex-row" style={{alignItems: 'center', gap: '8px'}}>
                    <span className="font-bold" style={{color: 'var(--text-main)', fontSize: '15px'}}>{item.name}</span>
                    <span className="font-regular" style={{color: 'var(--text-muted)', fontSize: '13px'}}>({item.industry})</span>
                    {item.isBlindSpot && (
                      <span style={{backgroundColor: '#fee2e2', color: '#b91c1c', fontSize: '11px', fontWeight: 700, padding: '2px 6px', borderRadius: '4px'}}>
                        🚨 심사 사각지대
                      </span>
                    )}
                  </div>
                  <div className="flex-row" style={{alignItems: 'center', gap: '4px', color: 'var(--primary)', fontSize: '12px', fontWeight: 600}}>
                    상세 보고서 <ChevronRight size={16} />
                  </div>
                </div>

                {/* 4-Metric Comparison Grid */}
                <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', background: 'white', padding: '12px 14px', borderRadius: '8px', border: '1px solid var(--border)'}}>
                  <div className="flex-col" style={{gap: '4px', borderRight: '1px solid #f1f5f9', paddingRight: '10px'}}>
                    <span style={{fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600}}>🏛️ 기존신용평가모형 (Legacy)</span>
                    <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'baseline'}}>
                      <span style={{fontSize: '13px', fontWeight: 700, color: 'var(--text-main)'}}>등급: <span style={{color: '#475569'}}>{item.oldGrade}</span></span>
                      <span style={{fontSize: '13px', fontWeight: 600, color: '#64748b'}}>확률: {item.oldPd}%</span>
                    </div>
                  </div>

                  <div className="flex-col" style={{gap: '4px', paddingLeft: '4px'}}>
                    <span style={{fontSize: '11px', color: 'var(--primary)', fontWeight: 700}}>⚡ AI ERM 모형 (New)</span>
                    <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'baseline'}}>
                      <span style={{fontSize: '13px', fontWeight: 700, color: 'var(--text-main)'}}>
                        등급: <span className="badge badge-primary" style={{padding: '2px 6px', fontSize: '11px', fontWeight: 800, backgroundColor: ['G4','G5'].includes(item.ermGrade) ? '#fee2e2' : ['G3'].includes(item.ermGrade) ? '#fef3c7' : '#d1fae5', color: ['G4','G5'].includes(item.ermGrade) ? '#dc2626' : ['G3'].includes(item.ermGrade) ? '#d97706' : '#059669', border: 'none'}}>{item.ermGrade}</span>
                      </span>
                      <span style={{fontSize: '14px', fontWeight: 800, color: item.pd >= 30 ? 'var(--danger)' : item.pd >= 10 ? 'var(--warning)' : 'var(--safe)'}}>
                        확률: {item.pd.toFixed(2)}%
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
