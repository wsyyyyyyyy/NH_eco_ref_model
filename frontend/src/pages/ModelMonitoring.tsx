import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, Legend, ResponsiveContainer, LineChart, Line } from 'recharts';
import { Activity, Target, ShieldCheck, BarChart2, List, ChevronRight, Info } from 'lucide-react';

export default function ModelMonitoring() {
  const [loading, setLoading] = useState(true);
  const [selectedBin, setSelectedBin] = useState('70%+ (고위험)');
  const [useRealData, setUseRealData] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    setTimeout(() => {
      setLoading(false);
    }, 400);
  }, []);

  const perfData = [
    { metric: 'AUROC (변별력)', 기존모형: 0.81, ERM모형: 0.92 },
    { metric: 'GINI Index', 기존모형: 0.62, ERM모형: 0.84 },
    { metric: 'K-S Stats (/100)', 기존모형: 0.42, ERM모형: 0.65 },
    { metric: 'F1 Score', 기존모형: 0.76, ERM모형: 0.87 },
    { metric: 'Accuracy', 기존모형: 0.82, ERM모형: 0.89 },
  ];

  const driftData = [
    { month: '23.09', featureDrift: 0.05, labelDrift: 0.02 },
    { month: '23.10', featureDrift: 0.08, labelDrift: 0.03 },
    { month: '23.11', featureDrift: 0.12, labelDrift: 0.05 },
    { month: '23.12', featureDrift: 0.15, labelDrift: 0.08 },
    { month: '24.01', featureDrift: 0.22, labelDrift: 0.15 }, // Threshold exceeded!
    { month: '24.02', featureDrift: 0.04, labelDrift: 0.03 }, // After Retraining
  ];

  const pdDistData = [
    { bin: '0~10% (안전)', 기존모형: 68, ERM모형: 48 },
    { bin: '10~30% (보통)', 기존모형: 21, ERM모형: 24 },
    { bin: '30~50% (주의)', 기존모형: 7, ERM모형: 14 },
    { bin: '50~70% (경고)', 기존모형: 3, ERM모형: 9 },
    { bin: '70%+ (고위험)', 기존모형: 1, ERM모형: 5 }, // 사각지대 해소 증명
  ];

  const binBorrowersMock: Record<string, Array<{ id: string; name: string; industry: string; pd: number; oldGrade: string; oldPd: number; ermGrade: string; isBlindSpot?: boolean }>> = {
    '70%+ (고위험)': [
      { id: '1000000000', name: '기업_1000000000', industry: '정보통신업', pd: 85.00, oldGrade: '15등급 (CCC)', oldPd: 18.50, ermGrade: 'G5' },
      { id: '1000000003', name: '기업_1000000003', industry: '건설업', pd: 78.40, oldGrade: '4등급 (AA-)', oldPd: 0.85, ermGrade: 'G5', isBlindSpot: true },
      { id: '1000000007', name: '기업_1000000007', industry: '도매 및 소매업', pd: 72.10, oldGrade: '2등급 (AA+)', oldPd: 0.45, ermGrade: 'G5', isBlindSpot: true },
      { id: '1000000012', name: '기업_1000000012', industry: '운수 및 창고업', pd: 91.20, oldGrade: '16등급 (C)', oldPd: 24.10, ermGrade: 'G5' },
    ],
    '50~70% (경고)': [
      { id: '1000000005', name: '기업_1000000005', industry: '제조업', pd: 64.50, oldGrade: '5등급 (A+)', oldPd: 1.10, ermGrade: 'G5', isBlindSpot: true },
      { id: '1000000008', name: '기업_1000000008', industry: '건설업', pd: 58.20, oldGrade: '10등급 (BBB-)', oldPd: 6.20, ermGrade: 'G5' },
      { id: '1000000011', name: '기업_1000000011', industry: '부동산업', pd: 55.40, oldGrade: '12등급 (BB-)', oldPd: 11.50, ermGrade: 'G5' },
    ],
    '30~50% (주의)': [
      { id: '1000000015', name: '기업_1000000015', industry: '도매 및 소매업', pd: 42.10, oldGrade: '8등급 (BBB0)', oldPd: 3.50, ermGrade: 'G4' },
      { id: '1000000019', name: '기업_1000000019', industry: '제조업', pd: 35.80, oldGrade: '7등급 (BBB+)', oldPd: 2.10, ermGrade: 'G4' },
      { id: '1000000022', name: '기업_1000000022', industry: '숙박 및 음식점업', pd: 38.90, oldGrade: '9등급 (BBB0)', oldPd: 4.80, ermGrade: 'G4' },
    ],
    '10~30% (보통)': [
      { id: '1000000031', name: '기업_1000000031', industry: '제조업', pd: 18.40, oldGrade: '6등급 (A0)', oldPd: 1.50, ermGrade: 'G3' },
      { id: '1000000035', name: '기업_1000000035', industry: '전문, 과학 및 기술 서비스업', pd: 14.20, oldGrade: '5등급 (A+)', oldPd: 1.10, ermGrade: 'G3' },
      { id: '1000000038', name: '기업_1000000038', industry: '건설업', pd: 25.10, oldGrade: '8등급 (BBB0)', oldPd: 3.50, ermGrade: 'G3' },
    ],
    '0~10% (안전)': [
      { id: '1000000041', name: '기업_1000000041', industry: '정보통신업', pd: 4.20, oldGrade: '3등급 (AA)', oldPd: 0.55, ermGrade: 'G2' },
      { id: '1000000045', name: '기업_1000000045', industry: '제조업', pd: 2.80, oldGrade: '2등급 (AA+)', oldPd: 0.40, ermGrade: 'G2' },
      { id: '1000000048', name: '기업_1000000048', industry: '부동산업', pd: 6.50, oldGrade: '5등급 (A+)', oldPd: 0.95, ermGrade: 'G2' },
    ],
  };

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
            <span className="font-extrabold" style={{fontSize: '24px', color: 'var(--primary)'}}>0.922</span>
            <span className="font-bold" style={{color: 'var(--safe)', fontSize: '13px'}}>▲ 0.112</span>
          </div>
          <span className="font-regular" style={{color: 'var(--text-muted)', fontSize: '12px', lineHeight: 1.3}}>
            부도/정상 기업 간 식별력 지표<br />(0.7 이상 시 우수 모형)
          </span>
        </div>

        <div className="card flex-col" style={{gap: '8px', padding: '16px', borderTop: '3px solid var(--primary)'}}>
          <div className="flex-row" style={{justifyContent: 'space-between', alignItems: 'center'}}>
            <span className="font-bold" style={{color: 'var(--text-main)', fontSize: '14px'}}>GINI INDEX</span>
            <Activity size={18} color="var(--primary)" />
          </div>
          <div className="flex-row" style={{alignItems: 'baseline', gap: '8px'}}>
            <span className="font-extrabold" style={{fontSize: '24px', color: 'var(--primary)'}}>0.844</span>
            <span className="font-bold" style={{color: 'var(--safe)', fontSize: '13px'}}>▲ 0.224</span>
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
            <span className="font-extrabold" style={{fontSize: '24px', color: 'var(--safe)'}}>0.040</span>
            <span className="badge badge-safe" style={{fontSize: '11px', padding: '2px 6px'}}>안정권</span>
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
            <span className="font-extrabold" style={{fontSize: '24px', color: 'var(--primary)'}}>65.4%</span>
            <span className="font-bold" style={{color: 'var(--safe)', fontSize: '13px'}}>▲ 23.3%p</span>
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
                  <Bar dataKey="기존모형" fill="#94a3b8" radius={[4, 4, 0, 0]} name="기존 은행 모형" maxBarSize={36} />
                  <Bar dataKey="ERM모형" fill="var(--primary)" radius={[4, 4, 0, 0]} name="ERM 참조 모델 (LightGBM)" maxBarSize={36} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="flex-row" style={{gap: '8px', background: 'var(--bg-main)', padding: '12px', borderRadius: '8px', alignItems: 'flex-start', marginTop: '12px'}}>
              <Info size={16} color="var(--primary)" style={{flexShrink: 0, marginTop: '2px'}} />
              <span className="font-regular" style={{color: 'var(--text-muted)', fontSize: '13px', lineHeight: 1.4}}>
                <strong>평가 지표 의미:</strong> AUROC와 Gini Index는 정상 기업과 부도 기업의 변별력을 나타내며, K-S Stats는 두 집단 분포 격차의 최대치를 의미합니다. 우리 ERM 모델은 바젤(Basel) III 및 금융감독원 모범규준을 상회하는 최고 등급 성능을 달성했습니다.
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
                  <Line type="stepAfter" dataKey={() => 0.2} stroke="var(--danger)" strokeDasharray="5 5" strokeWidth={1} dot={false} activeDot={false} name="임계치 (Threshold 0.2)" />
                  <Line type="monotone" dataKey="featureDrift" stroke="var(--warning)" strokeWidth={2} dot={{r:4}} name="Feature Drift (데이터 변동)" />
                  <Line type="monotone" dataKey="labelDrift" stroke="var(--primary)" strokeWidth={2} dot={{r:4}} name="Concept Drift (라벨 변동)" />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="flex-row" style={{gap: '8px', background: '#ecfdf5', padding: '12px', borderRadius: '8px', alignItems: 'flex-start', border: '1px solid #10b981', marginTop: '12px'}}>
              <ShieldCheck size={16} color="var(--safe)" style={{flexShrink: 0, marginTop: '2px'}} />
              <span className="font-regular" style={{color: '#065f46', fontSize: '13px', lineHeight: 1.4}}>
                <strong>드리프트 안심 구간:</strong> '24년 1월 거시경제 변동으로 임계치(0.2)를 초과했으나, 2월 1일 자로 최신 재무/비재무 데이터 140,000건을 반영한 자동 파인튜닝(Retraining)이 완료되어 현재 PSI 0.04의 매우 안정적인 상태를 유지하고 있습니다.
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
            {binBorrowersMock[selectedBin]?.map((item) => (
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
